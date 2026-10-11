"""Private per-call Vulkan transport. Admission is false until independent review.
No shader/network/model discovery; exact prepared module and worker identities only.
"""
from pathlib import Path
import hashlib, json, os, struct, subprocess, sys, tempfile, time, fcntl
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from run_examples import guard
from abi import expected_words

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dispatch(config,fid,x,order,caller):
 if config.get('schema')!='bend-fork-vulkan-transport-v1': raise RuntimeError('transport contract mismatch')
 # Caller constants are embedded in program.c, not supplied through its config/env.
 # Validate both config declarations and actual bytes before admission/worker/device.
 for key in ('schema','plan_schema','plan_sha256','shader_source_sha256','shader_sha256'):
  if caller.get(key)!=config.get(key):raise RuntimeError('calling program/config identity mismatch: '+key)
 for key in ('plan','shader_source','shader'):
  if digest(config[key])!=caller[key+'_sha256']:raise RuntimeError('calling program artifact bytes mismatch: '+key)
 plan=json.loads(Path(config['plan']).read_text())
 if plan.get('schema')!=caller['plan_schema']:raise RuntimeError('calling program plan version mismatch')
 if not config.get('admitted',False): raise RuntimeError('Vulkan transport awaits reviewed generated-shader gate')
 if config.get('words')!=24 or config.get('groups')!=1 or config.get('local_size')!=[128,1,1]: raise RuntimeError('bounded dispatch contract mismatch')
 if fid not in config['roots'] or not 0<=x<=0xffffffff or order not in (0,1): raise RuntimeError('invalid root/input/order')
 for key in ('shader','worker','plan'):
  if digest(config[key])!=config[key+'_sha256']: raise RuntimeError(key+' identity mismatch')
 # Shared finite gate budget: no launch outside its admitted time/count window.
 with open(config['budget_file'],'r+') as budget_file:
  fcntl.flock(budget_file,fcntl.LOCK_EX);budget=json.load(budget_file)
  if time.monotonic()>=budget['deadline_monotonic'] or budget['reserved_calls']>=budget['max_calls']:
   raise RuntimeError('finite GPU gate budget exhausted')
  budget['reserved_calls']+=1;budget_file.seek(0);budget_file.truncate();json.dump(budget,budget_file);budget_file.flush()
 dev=config['device'];guard(dev)
 # Fresh process/allocation per call. Initialize every word, not just READY/DONE.
 initial=[0]*24;initial[0]=fid;initial[1]=x;initial[11]=order
 # Gate receipts are retained even on worker failure, instead of temporary cleanup.
 d=Path(tempfile.mkdtemp(prefix='call-',dir=config['receipt_directory']))
 inp=d/'input.bin';out=d/'output.bin';inp.write_bytes(struct.pack('<24I',*initial))
 receipt={'fid':fid,'input':x,'order':order,'caller':caller,'device':dev,
   'worker_sha256':config['worker_sha256'],'shader_sha256':config['shader_sha256'],
   'input_sha256':digest(inp),'status':'prepared','reserved_call':budget['reserved_calls']}
 (d/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
 try:
  expected_worker_parent=os.getpid() # Capture in controller BEFORE spawning worker.
  args=[config['worker'],config['shader'],str(inp),str(out),'24','1',*[str(dev[k]) for k in ('index','major','minor','vendor','product','sysfs')],str(expected_worker_parent)]
  p=subprocess.run(args,capture_output=True,timeout=3)
  (d/'native.stdout').write_bytes(p.stdout);(d/'native.stderr').write_bytes(p.stderr)
  receipt['native_exit_code']=p.returncode
  if p.returncode: raise RuntimeError('native worker rejected: '+p.stderr.decode(errors='replace')[:1000])
  raw=out.read_bytes()
  if len(raw)!=96: raise RuntimeError('native output byte count')
  words=list(struct.unpack('<24I',raw))
  if words[0]!=fid or words[1]!=x or words[11]!=order or words[3]!=0 or words[4]!=2 or words[20]!=words[2]:
   raise RuntimeError('device error/root observation mismatch')
  if words[21:24]!=[0,0,0]:raise RuntimeError('reserved output words changed')
  if words!=expected_words(plan,fid,x,order):raise RuntimeError('complete device buffer/checked CPU oracle mismatch')
  if b'canaries_intact=1' not in p.stdout: raise RuntimeError('native canary evidence missing')
  receipt.update(status='passed',output_sha256=digest(out),complete_words=24,canaries=4,groups=1)
  (d/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
  return words[2]
 except Exception as error:
  receipt.update(status='failed',error=str(error));(d/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');raise

def main():
 if len(sys.argv)!=10:raise RuntimeError('controller CONFIG ROOT_FID INPUT CALLER_SCHEMA PLAN_SCHEMA PLAN_SHA256 SHADER_SOURCE_SHA256 SHADER_SHA256 EXPECTED_PARENT_PID')
 if int(sys.argv[9])<=0 or os.getppid()!=int(sys.argv[9]):raise RuntimeError('original controller parent mismatch/adoption')
 config=json.loads(Path(sys.argv[1]).read_text());order=int(os.environ.get('BEND_FORK_ORDER','0'))
 caller=dict(zip(('schema','plan_schema','plan_sha256','shader_source_sha256','shader_sha256'),sys.argv[4:9]))
 result=dispatch(config,int(sys.argv[2]),int(sys.argv[3]),order,caller)
 sys.stdout.buffer.write(struct.pack('<I',result))
if __name__=='__main__':
 try:main()
 except Exception as error:
  print('fork Vulkan: '+str(error),file=sys.stderr);sys.exit(2)
