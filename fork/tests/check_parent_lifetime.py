"""CPU-only Linux subreaper adoption race and normal cancellation regression."""
from pathlib import Path
import subprocess,json,sys,os
r=Path(__file__).resolve().parents[2];sys.path.insert(0,str(r/'fork/runtime'));from prepare import prepare
out=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-parent-lifetime-gate');out.mkdir(exist_ok=False)
g=r/'evidence/fork-parent-binding-regression/host_twice/generated';prepare(g)
transport=(r/'fork/runtime/transport.c').read_text();helper=transport[transport.index('static int fork_bind_parent'):transport.index('static uint32_t fork_vulkan')]
worker=(g/'worker.c').read_text();workerhelper=worker[worker.index('static int worker_bind_parent'):worker.index('int main(int argc')]
source='''#define _GNU_SOURCE
#include <unistd.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
'''+helper+workerhelper+'''
int old_bind(pid_t expected){(void)expected;pid_t parent=getppid();return parent==1||prctl(PR_SET_PDEATHSIG,SIGKILL)||getppid()!=parent;}
void adoption(int which){
 int release[2],report[2];assert(!pipe(release)&&!pipe(report));pid_t parent=fork();assert(parent>=0);
 if(!parent){pid_t original=getpid();pid_t child=fork();assert(child>=0);if(!child){close(release[1]);char token;assert(read(release[0],&token,1)==1);int rejected=which==0?fork_bind_parent(original):which==1?worker_bind_parent(original):old_bind(original);_exit(rejected?0:3);}assert(write(report[1],&child,sizeof child)==sizeof child);_exit(0);}
 close(report[1]);close(release[0]);pid_t child;assert(read(report[0],&child,sizeof child)==sizeof child);int status;assert(waitpid(parent,&status,0)==parent&&WIFEXITED(status));
 assert(write(release[1],"x",1)==1);assert(waitpid(child,&status,0)==child&&WIFEXITED(status));assert(WEXITSTATUS(status)==(which==2?3:0));
 close(report[0]);close(release[1]);
}
void cancellation(int which){
 int report[2];assert(!pipe(report));pid_t parent=fork();assert(parent>=0);
 if(!parent){pid_t original=getpid();pid_t child=fork();assert(child>=0);if(!child){assert(!(which==0?fork_bind_parent(original):worker_bind_parent(original)));pid_t self=getpid();assert(write(report[1],&self,sizeof self)==sizeof self);for(;;)pause();}for(;;)pause();}
 close(report[1]);pid_t child;assert(read(report[0],&child,sizeof child)==sizeof child);assert(!kill(parent,SIGKILL));int status;assert(waitpid(parent,&status,0)==parent);assert(waitpid(child,&status,0)==child&&WIFSIGNALED(status)&&WTERMSIG(status)==SIGKILL);close(report[0]);
}
int main(){assert(!prctl(PR_SET_CHILD_SUBREAPER,1));adoption(0);adoption(1);adoption(2);cancellation(0);cancellation(1);puts("Host/worker original-PID adoption rejects; old mutant accepts; both normal parent cancellation paths kill/reap children.");}
'''
(out/'lifetime.c').write_text(source)
for tag,cmd in [('build',['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',out/'lifetime.c','-o',out/'lifetime']),('run',[out/'lifetime']),('worker-correct-parent',[g/'worker','--parent-selftest',str(os.getpid())]),('worker-wrong-parent',[g/'worker','--parent-selftest','1'])]:
 p=subprocess.run(list(map(str,cmd)),capture_output=True,timeout=5);(out/(tag+'.stdout')).write_bytes(p.stdout);(out/(tag+'.stderr')).write_bytes(p.stderr);(out/(tag+'.json')).write_text(json.dumps({'command':list(map(str,cmd)),'exit_code':p.returncode})+'\n');assert p.returncode==(2 if tag=='worker-wrong-parent' else 0),(tag,p.stderr)
(out/'RESULT.json').write_text(json.dumps({'scope':'CPU-only exact host/worker binding helper regression','subreaper_adoption_rejected':['host','worker'],'old_bug_mutant_reproduced':True,'normal_cancellation_killed_reaped':['host child','native worker child'],'GPU_dispatches':0},indent=2)+'\n');print('CPU subreaper race, old mutant, cancellation, actual worker parent selftests PASS')
