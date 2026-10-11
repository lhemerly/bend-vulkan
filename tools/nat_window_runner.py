"""Review-only Nat gate runner. Default freezes/dry checks; execution needs assigned approval.
Explicit Python test seam has no CLI/environment route. Never builds or probes Vulkan.
"""
from pathlib import Path
import argparse,ctypes,fcntl,hashlib,json,math,os,signal,stat,struct,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'fork/runtime'));sys.path.insert(0,str(ROOT/'tools'))
from nat_arena import simulate
from nat_oracle import evaluate,integer
from nat_controller import validate_budget
from run_examples import guard
CANDIDATE=ROOT/'evidence/nat-admission-candidate-v1'
NAMES=['target','distinct_sub','sparse_root_FID','two_io_handoffs','root_order_a','root_order_b']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def matrix():
 rows=[]
 def direct(case,depth,order):rows.append(dict(kind='direct',case=case,depth=depth,order=order,calls=1))
 for depth in range(6):
  for order in [0,1]:direct('target',depth,order)
 for order in [0,1]:direct('target',5,order)
 for depth in [1,5]:
  for order in [0,1]:direct('distinct_sub',depth,order)
 for order in [0,1]:direct('sparse_root_FID',5,order)
 for threads in [1,2]:
  for order in [0,1]:rows.append(dict(kind='host',case='target',threads=threads,order=order,calls=1))
 for case in NAMES[3:]:
  for threads,order in [(1,0),(2,1)]:rows.append(dict(kind='host',case=case,threads=threads,order=order,calls=2))
 assert sum(r['calls'] for r in rows)==36
 return rows

def freeze(destination):
 manifest=json.loads((CANDIDATE/'FINAL-MANIFEST.json').read_text());assert [x['case'] for x in manifest['fixtures']]==NAMES
 paths=set()
 for name in NAMES:
  d=CANDIDATE/name;cfg=json.loads((d/'nat-transport.json').read_text())
  if cfg['admitted'] is not False or cfg['device'] is not None or cfg['budget_file'] is not None:raise RuntimeError('candidate config already admitted')
  for p in d.rglob('*'):
   if p.is_file():paths.add(p.resolve())
  for b in cfg['caller']['runtime_bindings']:paths.add(Path(b['path']).resolve())
 for p in [CANDIDATE/'FINAL-MANIFEST.json',Path(__file__),ROOT/'fork/runtime/nat_worker_prepare.py',ROOT/'fork/runtime/nat_host_bridge.c',ROOT/'fork/compiler/capture.ts',ROOT/'fork/compiler/nat_emitter.ts',ROOT/'fork/compiler/nat_ir.ts',ROOT/'fork/compiler/nat_regenerate.ts',ROOT/'fork/nat_transport_cli.ts']:paths.add(p.resolve())
 sources={'target':ROOT.parent/'bend-vulkan-feasibility/source/tests/run/gpu_mark.bend','distinct_sub':ROOT/'evidence/nat-corrected-cpu-v2/distinct_sub.bend','sparse_root_FID':ROOT/'evidence/fork-cpu-routing-nat-corrected-v1/sparse_root_FID/sparse_root_FID.bend'}
 for name in NAMES[3:]:sources[name]=ROOT/('evidence/fork-cpu-routing-nat-corrected-v1/'+name+'/'+name+'.bend')
 for name,p in sources.items():
  if sha(p)!=json.loads((CANDIDATE/name/'source-identity.json').read_text())['source_sha256']:raise RuntimeError('source file identity mismatch')
  paths.add(p.resolve())
 tools=[Path(p).resolve(strict=True) for p in ['/usr/bin/python3','/usr/bin/glslangValidator','/usr/bin/spirv-val','/usr/bin/cc','/usr/bin/clang']]
 paths.update(tools)
 driver_files=[Path('/usr/share/vulkan/icd.d/radeon_icd.json'),Path('/usr/lib/libvulkan_radeon.so'),Path('/usr/lib/libvulkan.so.1')]
 if json.loads(driver_files[0].read_text())['ICD']['library_path']!='libvulkan_radeon.so':raise RuntimeError('unexpected frozen ICD library selection')
 paths.update(p.resolve(strict=True) for p in driver_files)
 aliases=[dict(path=p, resolved=str(Path(p).resolve(strict=True)),sha256=sha(p)) for p in ['/usr/bin/python3','/usr/bin/glslangValidator','/usr/bin/spirv-val','/usr/bin/cc','/usr/bin/clang',*[str(p) for p in driver_files]]]
 spec=dict(schema='bend-nat-final-window-v1',admitted=False,assigned_window=None,max_calls=36,max_seconds=660,host_reserve_seconds=20,direct_reserve_seconds=10,matrix=matrix(),files=[dict(path=str(p),sha256=sha(p)) for p in sorted(paths)],tools=[str(p) for p in tools],device=None,driver_files=[dict(path=str(p),sha256=sha(p)) for p in driver_files],tool_driver_aliases=aliases,driver=None,warning='Driver/device/absolute deadline require independently reviewed assigned approval; frozen native binaries are dispatch-capable, controller configs disabled.')
 Path(destination).write_text(json.dumps(spec,indent=2)+'\n');return spec

def verify_files(spec):
 if spec.get('schema')!='bend-nat-final-window-v1' or spec.get('matrix')!=matrix() or spec.get('max_calls')!=36 or spec.get('max_seconds')!=660:raise RuntimeError('frozen matrix/scope mismatch')
 paths=[x['path'] for x in spec['files']]
 if len(paths)!=len(set(paths)) or str(Path(__file__).resolve()) not in paths:raise RuntimeError('invalid frozen file set')
 for item in spec['tool_driver_aliases']:
  if str(Path(item['path']).resolve(strict=True))!=item['resolved'] or sha(item['path'])!=item['sha256']:raise RuntimeError('tool/driver alias changed')
 for item in spec['files']:
  if sha(item['path'])!=item['sha256']:raise RuntimeError('frozen identity changed: '+item['path'])


def bind_parent(expected):
 if not integer(expected,1,2**31-1) or os.getppid()!=expected:raise RuntimeError('runner original parent mismatch/adoption')
 if ctypes.CDLL(None).prctl(1,signal.SIGTERM,0,0,0) or os.getppid()!=expected:raise RuntimeError('runner parent adoption race')

def host_preflight(approval):
 # Must fail before any candidate subprocess in a namespace lacking host visibility.
 if os.stat('/proc/self/ns/pid').st_ino!=0xEFFFFFFC or os.readlink('/proc/self')!=str(os.getpid()):raise RuntimeError('verified host PID/proc scope required before GPU')
 dev=approval['device'];node=Path(dev['node']);st=node.stat()
 if node.parent!=Path('/dev/dri') or not node.name.startswith('renderD') or not stat.S_ISCHR(st.st_mode):raise RuntimeError('visible explicit render character node required')
 driver=approval['driver']
 if not isinstance(driver,dict) or not driver.get('files'):raise RuntimeError('frozen driver identities required')
 if str((Path(dev['sysfs'])/'driver').resolve(strict=True))!=driver['sysfs_driver']:raise RuntimeError('driver association changed')
 for item in driver['files']:
  if sha(item['path'])!=item['sha256']:raise RuntimeError('driver bytes changed')
 return guard(dev)

def bounded_preflight(approval):
    # Separate owned CPU-only guard process bounds proc/sysfs inspection.
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from nat_window_runner import host_preflight;print(json.dumps(host_preflight(json.loads(sys.argv[2]))))"
    p=child_run(['/usr/bin/python3','-I','-c',code,str(ROOT/'tools'),json.dumps(approval)],dict(os.environ),3)
    if p.returncode:raise RuntimeError('host/render/driver preflight rejected: '+p.stderr.decode(errors='replace'))
    return json.loads(p.stdout)

def validate_approval(spec,approval,spec_path):
 if approval.get('schema')!='bend-nat-assigned-window-v1' or approval.get('admitted') is not True or not isinstance(approval.get('assigned_window'),str) or not approval['assigned_window'].strip():raise RuntimeError('independently assigned window required')
 if approval.get('spec_sha256')!=sha(spec_path):raise RuntimeError('approval/frozen spec mismatch')
 start=approval.get('start_monotonic');end=approval.get('deadline_monotonic');now=time.monotonic()
 if type(start) not in (int,float) or type(end) not in (int,float) or not math.isfinite(start) or not math.isfinite(end) or not 0<=start<=now<end or not 0<end-start<=660:raise RuntimeError('invalid assigned finite workload deadline')
 if approval.get('max_calls')!=36 or type(approval['max_calls']) is not int or not isinstance(approval.get('device'),dict) or not isinstance(approval.get('driver'),dict):raise RuntimeError('assigned budget/device/driver identity required')
 if approval['driver'].get('files')!=spec['driver_files']:raise RuntimeError('approval driver files differ from frozen ICD/driver/loader')
 if not isinstance(spec.get('device'),dict) or not isinstance(spec.get('driver'),dict):raise RuntimeError('actual frozen host device/driver identity required')
 # Canonical JSON equality retains integer/bool distinctions lost by dict ==.
 if json.dumps(approval['device'],sort_keys=True,allow_nan=False)!=json.dumps(spec['device'],sort_keys=True,allow_nan=False):raise RuntimeError('approval device differs from exact frozen host identity')
 if approval['driver'].get('sysfs_driver')!=spec['driver'].get('sysfs_driver'):raise RuntimeError('approval driver association differs from frozen host identity')
 return end

def capacity(budget_path,calls,deadline,reserve):
 if deadline-time.monotonic()<reserve:raise RuntimeError('whole invocation and cleanup cannot fit workload deadline')
 with open(budget_path) as f:
  fcntl.flock(f,fcntl.LOCK_EX);b=json.load(f);validate_budget(b,time.monotonic())
  if b['max_calls']-b['reserved_calls']<calls:raise RuntimeError('whole invocation handoff capacity absent')
  return b['reserved_calls']

def child_run(args,env,timeout):
 # Own a fresh process group; cancellation kills/reaps only this invocation.
 parent=os.getpid()
 def child_parent():
  if os.getppid()!=parent or ctypes.CDLL(None).prctl(1,signal.SIGKILL,0,0,0) or os.getppid()!=parent:os._exit(2)
 p=subprocess.Popen(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,preexec_fn=child_parent)
 try:
  # Child exec keeps original parent; controller/native chain separately binds PID.
  return finish(p,args,timeout)
 finally:
  try:os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  p.wait()
def finish(p,args,timeout):
 try:stdout,stderr=p.communicate(timeout=timeout)
 except BaseException:
  try:os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  p.communicate();raise
 return subprocess.CompletedProcess(args,p.returncode,stdout,stderr)

def check_receipts(config,row):
 dirs=sorted(Path(config['receipt_directory']).glob('call-*'),key=lambda d:(d/'receipt.json').stat().st_mtime_ns)
 if len(dirs)!=row['calls']:raise RuntimeError('exact full receipt count mismatch')
 observed=[];plan=json.loads(Path(config['plan']).read_text())
 for d in dirs:
  rec=json.loads((d/'receipt.json').read_text());raw=(d/'output.bin').read_bytes()
  if len(raw)!=3088 or rec.get('status')!='validated' or rec.get('native_exit')!=0 or rec.get('clean_native_exit_and_EOF') is not True or rec.get('caller')!=config['caller'] or rec.get('output_sha256')!=hashlib.sha256(raw).hexdigest():raise RuntimeError('receipt status/identity/framing/exit mismatch')
  root,arg,order=rec['root'],rec['full_Nat_argument'],rec['order']
  if order!=row['order'] or not integer(arg,0,5) or root not in plan['roots']:raise RuntimeError('receipt root/order/argument mismatch')
  expected=simulate(plan,root,arg,order)
  if raw!=struct.pack('<772I',*expected) or expected[9]!=evaluate(plan,root,arg):raise RuntimeError('full772-word/scalar oracle mismatch')
  initial=[0]*772;initial[:6]=[1,root,arg,63,31,192];initial[13]=order;initial[-4:]=expected[-4:]
  if (d/'input.bin').read_bytes()!=struct.pack('<772I',*initial):raise RuntimeError('exact initial receipt mismatch')
  observed.append((root,arg));
 if row['kind']=='direct' and observed!=[(config['roots'][0],row['depth'])]:raise RuntimeError('direct receipt argument mismatch')
 if row['kind']=='host':
  expected_args={'target':[2],'two_io_handoffs':[2,1],'root_order_a':[1,2],'root_order_b':[2,1]}[row['case']]
  identity=json.loads((CANDIDATE/row['case']/'source-identity.json').read_text())
  expected_pairs=list(zip([g['root_id'] for g in identity['gateways']],expected_args))
  if observed!=expected_pairs:raise RuntimeError('host receipt root/argument sequence mismatch')
 return observed

def revoke_all(configured,budget,summary):
 """Independent best-effort writes; malformed input never prevents budget expiry."""
 errors=[];attempts=[]
 charged=36
 try:
  original=json.loads(budget.read_text())
  if not integer(original['reserved_calls'],0,36):raise ValueError('invalid charged-call field')
  charged=original['reserved_calls']
 except Exception as error:errors.append({'path':str(budget),'phase':'budget-read','error':str(error)})
 # A known invalid/expired budget is written even if its old contents are corrupt.
 attempts.append({'path':str(budget),'kind':'budget','revoked':False})
 try:
  budget.write_text(json.dumps({'deadline_monotonic':0,'max_calls':charged,'reserved_calls':charged})+'\n');attempts[-1]['revoked']=True
 except Exception as error:errors.append({'path':str(budget),'phase':'budget-write','error':str(error)})
 for path in configured:
  cfg={'admitted':False,'device':None,'budget_file':None}
  try:
   original=json.loads(path.read_text())
   if not isinstance(original,dict):raise ValueError('config is not an object')
   cfg.update(original);cfg.update(admitted=False,device=None,budget_file=None)
  except Exception as error:errors.append({'path':str(path),'phase':'config-read','error':str(error)})
  attempts.append({'path':str(path),'kind':'config','revoked':False})
  try:path.write_text(json.dumps(cfg,indent=2)+'\n');attempts[-1]['revoked']=True
  except Exception as error:errors.append({'path':str(path),'phase':'config-write','error':str(error)})
 summary.update(cleanup_errors=errors,revocation_attempts=attempts,revoked=all(x['revoked'] for x in attempts),charged_calls=charged,dispatch_reservations=charged)
 if errors or not summary['revoked']:summary['status']='failed'
 return charged

def execute(spec_path,approval_path,output,expected_parent,*,test_backend=None):
 spec=json.loads(Path(spec_path).read_text());verify_files(spec);approval=json.loads(Path(approval_path).read_text());deadline=validate_approval(spec,approval,spec_path)
 out=Path(output);out.mkdir(exist_ok=False);budget=out/'budget.json';budget.write_text(json.dumps(dict(deadline_monotonic=deadline,reserved_calls=0,max_calls=36)))
 configured=[];summary=dict(status='preflight',GPU_dispatches=0,explicit_CPU_fixture=test_backend is not None,rows=[],assigned_window=approval['assigned_window']);lock=None
 old_handlers={};original_timer=signal.getitimer(signal.ITIMER_REAL);cancellation={'cleaning':False,'signals':[]}
 def cancelled(signum,frame):
  cancellation['signals'].append(signum)
  if cancellation['cleaning']:return
  cancellation['cleaning']=True
  raise RuntimeError('runner cancellation/parent lifetime loss')
 def save():(out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
 try:
  if test_backend is None:
   bind_parent(expected_parent)
   for sig in [signal.SIGTERM,signal.SIGINT,signal.SIGALRM]:old_handlers[sig]=signal.signal(sig,cancelled)
   if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):raise RuntimeError('runner requires unused lifetime timer')
   signal.setitimer(signal.ITIMER_REAL,max(0.001,deadline-time.monotonic()-5))
  # Exclusive lock is host-global per resolved render node, never per outputdir.
  lock=open('/tmp/bend-nat-exclusive-window.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  preflight=bounded_preflight if test_backend is None else test_backend.preflight
  summary['preflight']=preflight(approval);verify_files(spec)
  if deadline-time.monotonic()<20:raise RuntimeError('preflight consumed workload reserve')
  for index,row in enumerate(matrix()):
   verify_files(spec);reserve=20 if row['kind']=='host' else 10
   before=capacity(budget,row['calls'],deadline,reserve)
   summary['last_guard']=preflight(approval)
   capacity(budget,row['calls'],deadline,reserve) # Guard may consume the window.
   case=CANDIDATE/row['case'];cfg=json.loads((case/'nat-transport.json').read_text());cfg.update(admitted=True,device=approval['device'],budget_file=str(budget),receipt_directory=str(out/f'call-{index:02d}'/'receipts'))
   call=out/f'call-{index:02d}';call.mkdir();config_path=call/'config.json';config_path.write_text(json.dumps(cfg,indent=2)+'\n');configured.append(config_path)
   env={'PATH':'/usr/bin:/bin','LANG':'C','VK_DRIVER_FILES':'/usr/share/vulkan/icd.d/radeon_icd.json','VK_LOADER_LAYERS_DISABLE':'*'}
   if row['kind']=='host':
    env.update(BEND_FORK_TRANSPORT='nat-vulkan',BEND_FORK_NAT_CONFIG=str(config_path),BEND_FORK_ORDER=str(row['order']),BEND_FORK_TRACE='1');args=[str(case/'host'),'--gpu','on','--threads',str(row['threads'])]
   else:args=['/usr/bin/python3','-I',str(ROOT/'fork/runtime/nat_controller.py'),str(config_path),str(cfg['roots'][0]),str(row['depth']),str(row['order']),json.dumps(cfg['caller']),str(os.getpid())]
   if deadline-time.monotonic()<reserve:raise RuntimeError('expiry immediately before whole invocation launch')
   p=child_run(args,env,15 if row['kind']=='host' else 5) if test_backend is None else test_backend.run(row,cfg,budget,args,env)
   (call/'stdout.bin').write_bytes(p.stdout);(call/'stderr.txt').write_bytes(p.stderr)
   if p.returncode:raise RuntimeError('unsuccessful invocation exit')
   if row['kind']=='host':
    if p.stdout!=(case/('cpu-reference-t'+str(row['threads'])+'.stdout')).read_bytes() or p.stderr.count(b'Nat validated handoff')!=row['calls']:raise RuntimeError('whole host output/handoff mismatch')
   elif len(p.stdout)!=3088:raise RuntimeError('direct stdout framing mismatch')
   observed=check_receipts(cfg,row)
   if row['kind']=='direct':
    receipt=next(Path(cfg['receipt_directory']).glob('call-*'))
    if p.stdout!=(receipt/'output.bin').read_bytes():raise RuntimeError('direct stdout/receipt mismatch')
   charged=json.loads(budget.read_text())['reserved_calls']
   if charged-before!=row['calls']:raise RuntimeError('exact invocation dispatch reservation mismatch')
   summary['GPU_dispatches']=charged if test_backend is None else 0
   summary['rows'].append(dict(row,observed=observed,charged=charged));save()
   if deadline-time.monotonic()<5:raise RuntimeError('comparison consumed cleanup reserve')
  cancellation['cleaning']=True;summary['status']='passed'
 except BaseException as error:
  cancellation['cleaning']=True
  summary.update(status='failed',error=str(error));raise
 finally:
  # Install non-raising handlers before any cleanup operation. Repeated parent
  # death/user cancellation is recorded and deferred until all independent writes,
  # bounded guard, status output and lock release have been attempted.
  cancellation['cleaning']=True
  cleanup_signals=[signal.SIGTERM,signal.SIGINT,signal.SIGALRM]
  previous_mask=signal.pthread_sigmask(signal.SIG_BLOCK,cleanup_signals)
  deferred=cancellation['signals']
  def defer(signum,frame):deferred.append(signum)
  for sig in cleanup_signals:
   if sig not in old_handlers:old_handlers[sig]=signal.getsignal(sig)
   signal.signal(sig,defer)
  signal.setitimer(signal.ITIMER_REAL,0)
  signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask)
  try:
   charged=revoke_all(configured,budget,summary)
   try:summary['final_guard']=(bounded_preflight if test_backend is None else test_backend.preflight)(approval)
   except Exception as e:summary['final_guard_error']=str(e);summary['status']='failed'
   summary['validated_GPU_dispatches']=sum(r['calls'] for r in summary['rows']) if test_backend is None else 0
   summary['finished_monotonic']=time.monotonic();summary['within_workload_deadline']=summary['finished_monotonic']<=deadline
   summary['cleanup_deferred_signals']=deferred
   if deferred or not summary['within_workload_deadline']:summary['status']='failed'
   if test_backend is None and summary['status']!='passed':summary['GPU_dispatches']=None
   try:save()
   except Exception as error:
    summary['status']='failed';summary['cleanup_errors'].append({'phase':'result-write','error':str(error)})
    print(json.dumps(summary),file=sys.stderr)
  finally:
   try:
    if lock:lock.close()
   finally:
    try:
     for sig,handler in old_handlers.items():signal.signal(sig,handler)
    finally:signal.setitimer(signal.ITIMER_REAL,*original_timer)
 if summary['status']!='passed':raise RuntimeError('cleanup/final guard/deadline failed')
 return summary

def main():
 a=argparse.ArgumentParser();a.add_argument('--freeze',type=Path);a.add_argument('--spec',type=Path);a.add_argument('--approval',type=Path);a.add_argument('--output',type=Path);a.add_argument('--expected-parent',type=int);a.add_argument('--execute-assigned-window',action='store_true');args=a.parse_args()
 if args.freeze:freeze(args.freeze);print('Frozen only; admission disabled; GPU dispatches zero');return
 if not args.spec:a.error('--spec required')
 spec=json.loads(args.spec.read_text());verify_files(spec)
 if not args.execute_assigned_window:print('Dry identity/matrix checks PASS; no admission or GPU');return
 if not args.approval or not args.output or args.expected_parent is None:a.error('explicit assigned approval, new output and expected parent required')
 execute(args.spec,args.approval,args.output,args.expected_parent)
if __name__=='__main__':main()
