/* Separate Nat bridge: original task stays live until successful commit.
 * Routing functions/tables are the accepted schema2 context-sensitive policy. */
#include <poll.h>
#include <signal.h>
#include <sys/prctl.h>
#include <sys/wait.h>
static int nat_bind_parent(pid_t expected) {
  return expected<=0||getppid()!=expected||prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=expected;
}
static bool nat_root_allowed(u32 fid) {switch(fid){NAT_ROOT_CASES default:return false;}}
static Term nat_handoff(Env e,Term t) {
  u64* H=e.mem;u64 tl=routing_tail(H,t),loc=term_loc(t);u32 gateway=(u32)term_aux(t);
  int root=routing_root(gateway);
  if(root<0||!routing_nat(gateway)||!nat_root_allowed((u32)root)||fid_arity(gateway)!=2||fid_arity((u32)root)!=2||(u32)H[tl+1]!=0)
    err_fail("Nat: invalid checked gateway/root/layout");
  routing_chain(H,t,false); /* Allows proven later gateways in serial contexts. */
  if(routing_effect[root])err_fail("Nat: nested gateway/unknown root execution");
  u64 argument=H[loc];
  if(argument>NAT_IMM)err_fail("Nat: full argument exceeds upstream immediate cap");
  if(argument>5u)err_fail("Nat: full argument exceeds supported depth five");
  if(root_done(H))err_fail("Nat: host root already published");
  const char* config=getenv("BEND_FORK_F32_CONFIG");
  if(!config||!*config)err_fail("Nat: prepared config required");
  const char* order_text=getenv("BEND_FORK_ORDER");u32 order=0;
  if(order_text&&*order_text){if(strcmp(order_text,"0")&&strcmp(order_text,"1"))err_fail("Nat: order must be zero or one");order=(u32)(order_text[0]-'0');}
  Term cont=H[tl];u32 idx=(u32)(H[tl+1]>>32);
  u64 payload=H[loc+1];if(payload>0xffffffffull||(payload&0x7f800000ull)==0x7f800000ull)err_fail("F32: invalid full finite payload");
  u64 task_snapshot[4]={H[loc],H[loc+1],H[loc+2],H[loc+3]};
  u64 root_word=H[H_ROOT_WORD],root_state=H[H_ROOT_DONE];
  char id[16],value[32],payload_text[32],ord[4],parent_id[32];
  snprintf(payload_text,sizeof payload_text,"%llu",(unsigned long long)payload);
  snprintf(id,sizeof id,"%u",(u32)root);snprintf(value,sizeof value,"%llu",(unsigned long long)argument);
  snprintf(ord,sizeof ord,"%u",order);const pid_t expected_parent=getpid();snprintf(parent_id,sizeof parent_id,"%ld",(long)expected_parent);
  int channel[2];if(pipe(channel))err_fail("Nat: controller pipe failed");
  pid_t child=fork();if(child<0){close(channel[0]);close(channel[1]);err_fail("Nat: controller fork failed");}
  if(child==0){
    if(nat_bind_parent(expected_parent))_exit(2);
    close(channel[0]);if(dup2(channel[1],STDOUT_FILENO)<0)_exit(2);close(channel[1]);
    /* Isolated stdlib bootstrap hashes every fixed controller dependency before
     * running it. Its paths/hash values are compiled caller constants. */
    execl("/usr/bin/python3","python3","-I","-c",NAT_BOOTSTRAP,NAT_CONTROLLER,NAT_RUNTIME_BINDINGS,
      config,id,value,payload_text,ord,NAT_CALLER_JSON,parent_id,(char*)NULL);_exit(2);
  }
  close(channel[1]);struct pollfd poller={.fd=channel[0],.events=POLLIN};
  unsigned char bytes[3089];size_t count=0;int failed=0,status=0;
  struct timespec began,current;clock_gettime(CLOCK_MONOTONIC,&began);
  for(;;){clock_gettime(CLOCK_MONOTONIC,&current);
    long ms=(current.tv_sec-began.tv_sec)*1000+(current.tv_nsec-began.tv_nsec)/1000000;
    if(ms>=5000||poll(&poller,1,(int)(5000-ms))<=0){failed=1;break;}
    ssize_t n=read(channel[0],bytes+count,sizeof bytes-count);
    if(n==0)break;
    if(n<0||(count+=(size_t)n)>=sizeof bytes){failed=1;break;}
  }
  close(channel[0]);if(failed)kill(child,SIGKILL);
  /* Closing stdout early does not commit; successful child exit is required. */
  for(;;){pid_t got=waitpid(child,&status,WNOHANG);if(got==child)break;
    if(got<0){failed=1;break;}clock_gettime(CLOCK_MONOTONIC,&current);
    long ms=(current.tv_sec-began.tv_sec)*1000+(current.tv_nsec-began.tv_nsec)/1000000;
    if(ms>=5000){kill(child,SIGKILL);waitpid(child,&status,0);failed=1;break;}
    struct timespec tick={0,1000000};nanosleep(&tick,NULL);
  }
  if(failed||count!=3088||!WIFEXITED(status)||WEXITSTATUS(status)!=0)
    err_fail("Nat: controller framing/lifetime/exit failure; no fallback");
  u32 words[772];for(u32 i=0;i<772;i++)words[i]=(u32)bytes[i*4]|(u32)bytes[i*4+1]<<8|(u32)bytes[i*4+2]<<16|(u32)bytes[i*4+3]<<24;
  if(words[0]!=1||words[1]!=(u32)root||words[2]!=(u32)argument||words[3]!=63||words[4]!=31||words[5]!=192||words[10]!=0||words[11]!=1||words[12]!=words[9]||words[13]!=order||words[14]!=(u32)payload||words[15]
    ||words[768]!=0xa17ecafeu||words[769]!=0x5a5aa5a5u||words[770]!=0xdeadbeefu||words[771]!=0xc001d00du)
    err_fail("Nat: invalid validated receipt header/observer/canaries");
  /* Recheck the still-owned task and continuation immediately before mutation. */
  if(H[loc]!=task_snapshot[0]||H[loc+1]!=task_snapshot[1]||H[loc+2]!=task_snapshot[2]||H[loc+3]!=task_snapshot[3]||H[H_ROOT_WORD]!=root_word||H[H_ROOT_DONE]!=root_state)
    err_fail("Nat: original task/root ownership changed during dispatch");
  routing_chain(H,t,false);
  Term result[1]={(Term)words[9]};
  if(getenv("BEND_FORK_TRACE"))fprintf(stderr,"Nat validated handoff gateway=%u root=%u arg=%llu words=772\n",gateway,(u32)root,(unsigned long long)argument);
  heap_free(e,cls_fit(4),loc);
  return task_deliver(H,cont,idx,result,1);
}
