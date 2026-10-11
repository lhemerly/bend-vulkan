"""CPU-only integrated Nat worker/controller/host contract regression.

Positive receipts use an explicitly substituted CPU test controller or the
controller's keyword-only test backend. Production CLI offers no such route.
"""
from pathlib import Path
import copy,hashlib,json,os,re,shutil,struct,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'fork/runtime'))
from nat_controller import dispatch
from nat_arena import simulate,CANARIES
from nat_worker_prepare import prepare

def main(name):
 out=ROOT/'evidence'/name;out.mkdir(exist_ok=False);rows=[]
 env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')}
 def run(args,d,tag,extra=None,timeout=30):
  args=list(map(str,args));p=subprocess.run(args,capture_output=True,env={**env,**(extra or {})},timeout=timeout)
  (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
  (d/(tag+'.json')).write_text(json.dumps({'argv':args,'exit':p.returncode},indent=2)+'\n');return p
 source=ROOT.parent/'bend-vulkan-feasibility/source/tests/run/gpu_mark.bend'
 d=out/'target';d.mkdir();g=d/'generated'
 p=run(['bun',ROOT/'fork/nat_transport_cli.ts',source,g],d,'emit');assert p.returncode==0,p.stderr
 config=json.loads((g/'nat-transport.json').read_text());caller=config['caller'];plan=json.loads((g/'nat-plan.json').read_text());root=plan['roots'][0]
 p=run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',g/'program.c','-lpthread','-lm','-o',d/'host'],d,'build');assert p.returncode==0,p.stderr
 for threads in (1,2):
  p=run([d/'host','--gpu','off','--threads',threads],d,f'absent-t{threads}');assert (p.returncode,p.stdout,p.stderr)==(0,b'1212\n',b'')
  p=run([d/'host','--gpu','off','--threads',threads],d,f'CPU-reference-t{threads}',{'BEND_FORK_TRANSPORT':'cpu-reference'});assert (p.returncode,p.stdout,p.stderr)==(0,b'1212\n',b'')
  p=run([d/'host','--gpu','on','--threads',threads],d,f'real-controller-blocked-t{threads}',{'BEND_FORK_TRANSPORT':'nat-vulkan','BEND_FORK_NAT_CONFIG':str(g/'nat-transport.json')});assert p.returncode and p.stdout==b'' and b'admission disabled' in p.stderr
 rows.append({'case':'current native default/CPU-reference parity and real-controller blocked','threads':[1,2],'GPU_dispatches':0})
 p=run([d/'host','--gpu','off'],d,'off-veto',{'BEND_FORK_TRANSPORT':'nat-vulkan','BEND_FORK_NAT_CONFIG':'/must/not/be/read'});assert p.returncode and b'--gpu off vetoes' in p.stderr
 # Worker validates exact772-word framing/module/root then hits compiled veto.
 initial=[0]*772;initial[:6]=[1,root,2,63,31,192];initial[-4:]=CANARIES
 inp=d/'native-input.bin';inp.write_bytes(struct.pack('<772I',*initial));output=d/'native-output.bin'
 worker=Path(config['worker']);args=[worker,g/'nat.spv',inp,output,772,1,0,0,0,0,0,'/sys/devices/unselected',os.getpid()]
 p=run(args,d,'native-worker-blocked');assert p.returncode==2 and b'admission disabled' in p.stderr and not output.exists()
 for tag,extra in [('guard',['--guard-selftest']),('parent',['--parent-selftest',os.getpid()]),('adopted',['--parent-selftest',1]),('inventory',['--probe-inventory'])]:
  p=run([worker,*extra],d,'worker-'+tag);assert p.returncode==(0 if tag in ('guard','parent') else 2)
 rows.append({'case':'actual exact772-word worker compiled admission/selftests','GPU_dispatches':0})
 # A distinct valid SPIR-V must still reject unless reproduced from these GLSL.
 swapped=d/'valid-other.spv';swapped.write_bytes((ROOT/'evidence/nat-corrected-cpu-v2/renamed_base7/nat.spv').read_bytes())
 p=run(['spirv-val','--target-env','vulkan1.2',swapped],d,'valid-other');assert p.returncode==0
 mutant=d/'wrong-generation';mutant.mkdir()
 for file in ['source-identity.json','nat-plan.json','routing-plan.json','routing.c','default.c','nat.comp']:shutil.copyfile(g/file,mutant/file)
 shutil.copyfile(swapped,mutant/'nat.spv')
 try:prepare(mutant);raise AssertionError('arbitrary valid SPIR-V accepted')
 except ValueError as error:assert 'SPIR-V not generated from approved GLSL' in str(error)
 rows.append({'case':'valid SPIR-V swapped against approved GLSL rejected','GPU_dispatches':0})
 # Production admission/identity preflight must not reach any backend.
 for label,change in [('plan-swap',lambda c:c.update(plan=str(mutant/'nat-plan.json'))),('caller-forge',lambda c:c['caller'].update(shader_sha256='0'*64)),('geometry',lambda c:c.update(words=776))]:
  bad=copy.deepcopy(config);change(bad)
  if label=='plan-swap':
   bad['plan']=str(mutant/'nat-plan.json');(mutant/'nat-plan.json').write_text('{}\n')
  try:dispatch(bad,root,2,0,caller);raise AssertionError(label+'accepted')
  except (RuntimeError,ValueError):pass
 for value in (6,2**32+2,(1<<48)-1,1<<48,True):
  try:dispatch(config,root,value,0,caller);raise AssertionError('full Nat accepted')
  except RuntimeError:pass
 # Explicit CPU test backend checks the full receipt and worker-exit contract.
 for label in ('valid','short','extra','nonzero','record-mismatch','device-error','canary'):
  def backend(directory,initial,cfg):
   words=simulate(plan,root,2)
   if label=='record-mismatch':words[16+7]=1
   if label=='device-error':words[10]=4
   if label=='canary':words[-1]=0
   raw=struct.pack('<772I',*words)
   if label=='short':raw=raw[:-1]
   if label=='extra':raw+=b'x'
   (directory/'output.bin').write_bytes(raw)
   return subprocess.CompletedProcess([],2 if label=='nonzero' else 0,b'canaries_intact=1\n',b'')
  try:
   raw=dispatch(config,root,2,0,caller,test_backend=backend);assert label=='valid' and len(raw)==3088
  except RuntimeError:assert label!='valid'
  rows.append({'case':'controller explicit CPU backend '+label,'GPU_dispatches':0})
 # An isolated, hashed CPU test controller exercises the exact host bridge,
 # including failure after full bytes or early stdout close. It is not the
 # production controller and cannot be selected through an environment knob.
 shim=d/'CPU-test-controller.py';shim.write_text('''import json,os,sys,time,struct
sys.path.insert(0,RUNTIME)
from nat_arena import simulate
cfg=json.load(open(sys.argv[1]));mode=cfg['mode'];plan=json.load(open(cfg['plan']))
raw=struct.pack('<772I',*simulate(plan,int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4])))
if mode=='short':raw=raw[:-1]
if mode=='extra':raw+=b'x'
if mode=='bad-header':raw=bytes([0])+raw[1:]
if mode=='timeout':time.sleep(7)
sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()
if mode in ('close-nonzero','close-hang','close-success'):
 os.close(1);time.sleep(7 if mode=='close-hang' else .1);os._exit(0 if mode=='close-success' else 2)
os._exit(2 if mode=='nonzero' else 0)
'''.replace('RUNTIME',repr(str(ROOT/'fork/runtime'))))
 bindings=[{'path':str(shim),'sha256':hashlib.sha256(shim.read_bytes()).hexdigest()}]+[b for b in caller['runtime_bindings'] if b['path'].endswith(('nat_arena.py','nat_oracle.py'))]
 def substitute(c):
  for key,value in [('NAT_CONTROLLER',str(shim)),('NAT_RUNTIME_BINDINGS',json.dumps(bindings))]:
   c=re.sub(r'^#define '+key+r' .*$',lambda m:'#define '+key+' '+json.dumps(value),c,flags=re.M)
  return c
 globals='''
static bool nat_watch_active;static u64*nat_watch_H;static u64 nat_watch_loc,nat_watch_task[3],nat_watch_root,nat_watch_done;static unsigned nat_watch_frees;
static void nat_watch_exit(void){if(!nat_watch_active)return;bool same=nat_watch_frees==0&&nat_watch_H[H_ROOT_WORD]==nat_watch_root&&nat_watch_H[H_ROOT_DONE]==nat_watch_done;
for(unsigned i=0;i<3;i++)same &=nat_watch_H[nat_watch_loc+i]==nat_watch_task[i];fprintf(stderr,"NAT_FAILURE live_task_unchanged=%u frees=%u no_commit=%u\\n",same,nat_watch_frees,nat_watch_H[H_ROOT_DONE]==nat_watch_done);if(!same)_Exit(91);}
'''
 c=substitute((g/'program.c').read_text());a='INLINE void heap_free(Env e, u32 cls, u64 loc) {';assert c.count(a)==1
 c=c.replace(a,globals+a+'\n if(nat_watch_active&&loc==nat_watch_loc)nat_watch_frees++;')
 c=c.replace('static void err_fail(const char* msg) {','static void nat_watch_exit(void);\nstatic void err_fail(const char* msg) {')
 c=c.replace('  _exit(1);','  nat_watch_exit();\n  _exit(1);')
 a='  u64 root_word=H[H_ROOT_WORD],root_state=H[H_ROOT_DONE];';assert c.count(a)==1
 c=c.replace(a,a+'\n nat_watch_active=true;nat_watch_H=H;nat_watch_loc=loc;for(unsigned i=0;i<3;i++)nat_watch_task[i]=task_snapshot[i];nat_watch_root=root_word;nat_watch_done=root_state;nat_watch_frees=0;')
 a='  heap_free(e,cls_fit(3),loc);';assert c.count(a)==1
 c=c.replace(a,a+'\n if(nat_watch_frees!=1)err_fail("test: Nat task not freed once");fprintf(stderr,"NAT_COMMIT one_free=1 original_cont=%u original_idx=%u\\n",cont==TERM_HOLE?65535u:(u32)term_aux(cont),idx);nat_watch_active=false;')
 (d/'framing.c').write_text(c);p=run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',d/'framing.c','-lpthread','-lm','-o',d/'framing'],d,'framing-build');assert p.returncode==0,p.stderr
 for mode in ('valid','close-success','short','extra','bad-header','nonzero','close-nonzero','close-hang','timeout'):
  cfg=d/(mode+'.json');cfg.write_text(json.dumps({'mode':mode,'plan':str(g/'nat-plan.json')}))
  for threads in (1,2):
   p=run([d/'framing','--gpu','on','--threads',threads],d,f'framing-{mode}-t{threads}',{'BEND_FORK_TRANSPORT':'nat-vulkan','BEND_FORK_NAT_CONFIG':str(cfg)},timeout=8)
   if mode in ('valid','close-success'):assert p.returncode==0 and p.stdout==b'1212\n' and p.stderr.count(b'NAT_COMMIT one_free=1')==1,(mode,p.stderr)
   else:assert p.returncode==1 and p.stdout==b'' and b'NAT_FAILURE live_task_unchanged=1 frees=0 no_commit=1' in p.stderr,(mode,p.stderr)
   assert b'runtime error:' not in p.stderr
   rows.append({'case':'native framing '+mode,'threads':threads,'success':mode in ('valid','close-success'),'original_task_live_until_commit':True,'GPU_dispatches':0})
 # Preserve context-sensitive later-gateway policy, including two future
 # IO-separated handoffs: re-use the same explicit CPU fixture substitution.
 for name in ('two_io_handoffs','root_order_a','root_order_b'):
  folder=out/name;folder.mkdir();src=ROOT/'evidence/fork-cpu-routing-nat-corrected-v1'/name/(name+'.bend');gg=folder/'generated'
  p=run(['bun',ROOT/'fork/nat_transport_cli.ts',src,gg],folder,'emit');assert p.returncode==0,p.stderr
  (folder/'test.c').write_text(substitute((gg/'program.c').read_text()));p=run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',folder/'test.c','-lpthread','-lm','-o',folder/'host'],folder,'build');assert p.returncode==0,p.stderr
  cfg=folder/'CPU-test.json';cfg.write_text(json.dumps({'mode':'valid','plan':str(gg/'nat-plan.json')}))
  expected={'two_io_handoffs':b'12\n6\n','root_order_a':b'10\n12\n','root_order_b':b'12\n10\n'}[name]
  for threads in (1,2):
   p=run([folder/'host','--gpu','on','--threads',threads],folder,f't{threads}',{'BEND_FORK_TRANSPORT':'nat-vulkan','BEND_FORK_NAT_CONFIG':str(cfg),'BEND_FORK_TRACE':'1'});assert p.returncode==0 and p.stdout==expected and p.stderr.count(b'Nat validated handoff')==2,(name,p.stderr)
   rows.append({'case':'context-sensitive '+name,'threads':threads,'two_checked_handoffs':True,'CPU_test_fixture_only':True,'GPU_dispatches':0})
 (out/'RESULT.json').write_text(json.dumps({'scope':'production native admission disabled; positive handoff/controller seams are explicit CPU test fixtures','cases':rows,'GPU_dispatches':0},indent=2)+'\n')
 print('Nat worker generation/identity, controller full receipt, host framing/ownership and context-sensitive handoffs PASS',flush=True)
if __name__=='__main__':main(sys.argv[1])
