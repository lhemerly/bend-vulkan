/* CPU-only routing review prototype. Gateway mapping and effects are immutable
 * generated tables bound to the exact plan SHA. No device transport exists. */
static u64 routing_tail(u64* H, Term t) {
  u32 f=(u32)term_aux(t);u64 loc=term_loc(t);
  if(term_tag(t)!=TAG_TSK || f>=ROUTING_SEGMENTS || loc<HEAP_OFF
      || loc+2u+routing_arity[f]>corpus_size/8u || fid_arity(f)!=routing_arity[f])
    err_fail("routing: invalid dynamic task layout");
  return loc+routing_arity[f];
}
static void routing_join_state(u64* H,Term t) {
  u64 tl=routing_tail(H,t),loc=term_loc(t);u32 f=(u32)term_aux(t);
  u32 expected_count=routing_join_count(f);
  if(!expected_count || (u32)H[tl+1]!=expected_count)
    err_fail("routing: pending count differs from compiled join shape");
  for(u32 i=0;i<routing_arity[f];i++) {
    int expected=routing_child(f,i);Term child=H[loc+i];
    if(expected<0) {
      if(term_tag(child)==TAG_TSK)err_fail("routing: extra task outside compiled child slots");
      if(routing_reserved_result(f,i) && child!=TERM_HOLE)
        err_fail("routing: reserved child result slot is already published");
      continue;
    }
    if(term_tag(child)!=TAG_TSK)err_fail("routing: required compiled child task is missing");
    if((u32)term_aux(child)!=(u32)expected)
      err_fail("routing: dynamic child differs from compiled join proof");
    u64 ct=routing_tail(H,child);
    if(routing_effect[expected] || H[ct]!=t || (u32)(H[ct+1]>>32)!=i || (u32)H[ct+1]!=0)
      err_fail("routing: marked/unknown child or invalid continuation; CPU scheduling refused");
  }
}
static void routing_chain(u64* H, Term t, bool safe) {
  Term seen[64];u32 n=0;
  while(t!=TERM_HOLE) {
    if(n==64)err_fail("routing: continuation chain limit");
    for(u32 j=0;j<n;j++)if(seen[j]==t)err_fail("routing: cyclic continuation chain");
    seen[n++]=t;
    u64 tl=routing_tail(H,t);u32 f=(u32)term_aux(t);
    if(safe && routing_effect[f])err_fail("routing: future gateway or unknown execution; CPU scheduling refused");
    Term cont=H[tl];u32 idx=(u32)(H[tl+1]>>32);
    if(idx>65535u)err_fail("routing: invalid continuation result index");
    if(cont!=TERM_HOLE) {
      u64 ct=routing_tail(H,cont);u32 cf=(u32)term_aux(cont);
      if(!routing_parent(f,(int)cf,idx)) {
        if(getenv("BEND_FORK_TRACE"))fprintf(stderr,"routing invalid context child=%u parent=%u idx=%u\n",f,cf,idx);
        err_fail("routing: continuation link differs from compiled caller context");
      }
      if(idx+routing_resw[f]>routing_arity[cf])err_fail("routing: continuation slot outside checked layout");
      /* Serial call continuations await one callee, regardless of captured
       * words or result width. A fresh join instead owns its compiled child
       * count and task slots; gateway handoff under a join is unsupported. */
      if(routing_serial[cf]) {
        if((u32)H[ct+1]!=1u)err_fail("routing: serial ancestor remaining count must be one");
        u32 start=routing_arity[cf]-routing_frame_results[cf];
        for(u32 i=0;i<routing_arity[cf];i++) {
          if(i>=start && H[term_loc(cont)+i]!=TERM_HOLE)
            err_fail("routing: serial ancestor result slot is already published");
          if(i<start && term_tag(H[term_loc(cont)+i])==TAG_TSK)
            err_fail("routing: extra task in serial ancestor capture");
        }
      } else if(routing_join_count(cf)) {
        if(!safe)err_fail("routing: gateway has pending parallel ancestor; CPU handoff refused");
        routing_join_state(H,cont);
      } else err_fail("routing: unsupported ancestor lifecycle role");
    } else if(idx!=0 || !routing_parent(f,-1,idx))err_fail("routing: invalid compiled root continuation context");
    t=cont;
  }
}
static void routing_pending(u64* H,Term t) {
  if(root_done(H))err_fail("routing: pending scheduling with completed root");
  routing_chain(H,t,true);
  routing_join_state(H,t);
  u32 fid=(u32)term_aux(t),tasks=routing_join_count(fid);
  if(getenv("BEND_FORK_TRACE"))fprintf(stderr,"routing CPU pending fid=%u rem=%u plan=%s\n",fid,tasks,ROUTING_PLAN_SHA256);
}
static Term routing_reference(Env e,Term t) {
  u64* H=e.mem;u64 tl=routing_tail(H,t);u32 f=(u32)term_aux(t);
  int root=routing_root(f);
  if(root<0 || fid_arity(f)!=2 || fid_arity((u32)root)!=2 || (u32)H[tl+1]!=0)
    err_fail("routing: invalid gateway binding/layout");
  routing_chain(H,t,false);
  if(routing_effect[root])err_fail("routing: gateway root has nested gateway or unknown execution");
  u64 argument=H[term_loc(t)]; /* Never narrow before validating the full word. */
  if(routing_nat(f)) {
    if(argument>NAT_IMM)err_fail("routing: Nat exceeds upstream immediate cap");
    if(argument>5u)err_fail("routing: explicit Nat gateway exceeds supported depth five");
  } else if(argument>0xffffffffull)err_fail("routing: invalid full-word U32 argument");
  u64 payload=H[term_loc(t)+1u];
  if(payload>0xffffffffull)err_fail("routing F32: invalid full-word payload");
  u32 bits=(u32)payload;float x;memcpy(&x,&bits,sizeof x);
  if(!isfinite(x))err_fail("routing F32: nonfinite payload unsupported");
  if(root_done(H))err_fail("routing: root result already occupied");
  Term cont=H[tl];u32 idx=(u32)(H[tl+1]>>32);Term result[WL_RESW];
  if(getenv("BEND_FORK_TRACE"))fprintf(stderr,"routing CPU-reference handoff gateway=%u root=%u arg=%llu plan=%s\n",f,(u32)root,(unsigned long long)argument,ROUTING_PLAN_SHA256);
  /* Explicit reference handoff: isolated CPU evaluation of the selected root.
   * Only this owned handoff uses the upstream sequential evaluator. Host mode,
   * ordinary recursion and thread count remain unchanged. Entry frees this
   * original task once; its original continuation is restored by delivery. */
  H[tl]=TERM_HOLE;H[tl+1]=0;
  Term returned=work_loop(e,io_stk,term_tsk((u32)root,term_loc(t)),1);
  if(returned!=0 || !root_done(H) || err_seen(H))err_fail("routing: CPU-reference handoff failed");
  if(root_take(H,result)!=1)err_fail("routing: unexpected result width");
  return task_deliver(H,cont,idx,result,1);
}
