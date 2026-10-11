"""Fail-closed cached CPU receipts and separate byte-exact runtime streams."""
from pathlib import Path
import hashlib,json,os,resource,shutil,subprocess,time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'bend-vulkan-feasibility/source'

class StaleReceipt(RuntimeError):pass

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
_binding_hashes={}
def binding_sha(p):
 # Avoid rereading large tool executables per row; mutations change stat identity.
 p=Path(p).resolve();s=p.stat();key=(str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
 if key not in _binding_hashes:_binding_hashes[key]=sha(p)
 return _binding_hashes[key]
def limits():
 resource.setrlimit(resource.RLIMIT_CPU,(15,20));resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024));os.umask(0o077)

def compiler_bindings():
 paths=[SOURCE/'bend2/bend.ts',SOURCE/'bend2/comp.ts',SOURCE/'bend2/base.bend',SOURCE/'gates/test.ts',ROOT/'evidence/upstream/bend.ts',ROOT/'tools/cpu_compatibility_strict.py',Path(__file__)]
 paths+=list((ROOT/'fork/compiler').glob('*.ts'))
 # Both compilers load foreign/effect source during emission and IO checkup.
 # Bind the full permitted effect trees, including additions/removals.
 for folder in [SOURCE/'bend2/effs',ROOT/'evidence/upstream/effs']:
  paths += [p for p in folder.rglob('*') if p.is_file() and p.suffix in ['.c','.js']]
 # Reviewed future foreign fixture twins live outside the builtin effect folder.
 paths += [p for p in SOURCE.rglob('*') if p.is_file() and p.suffix in ['.c','.js']]
 paths += [ROOT/'tools/cpu_ledger_probe_strict.ts',ROOT/'tools/cpu_resume.py']
 for tool in ['bun','clang']:
  found=shutil.which(tool)
  if not found:raise FileNotFoundError(tool)
  paths.append(Path(found).resolve())
 return {str(p.resolve()):binding_sha(p) for p in sorted(set(paths))}

def declared_paths(args):
 """Outputs are explicit positional emitter destinations or clang's -o target."""
 outputs=[]
 if len(args)>=5 and args[2] in ['upstream-c','fork-c','upstream-js']:outputs=[Path(args[4]).resolve()]
 elif '-o' in args:outputs=[Path(args[args.index('-o')+1]).resolve()]
 excluded={str(p) for p in outputs};inputs=[]
 tool=shutil.which(args[0])
 if not tool:raise FileNotFoundError(args[0])
 inputs.append(Path(tool).resolve())
 for arg in args[1:]:
  p=Path(arg)
  if p.is_file() and str(p.resolve()) not in excluded:inputs.append(p.resolve())
 return sorted(set(inputs)),outputs

def run_step(d,tag,args,timeout):
 d=Path(d).resolve();args=list(map(str,args));meta=d/(tag+'.json')
 inputs,outputs=declared_paths(args)
 env={'PATH':os.environ['PATH'],'LANG':'C','BEND_LIB':str(ROOT/'evidence/cpu-compatibility-ledger-v1/no-hub')}
 basis={'argv':args,'cwd':str(d),'timeout_seconds':timeout,'environment':env,'input_hashes':{str(p):sha(p) for p in inputs},'compiler_hashes':compiler_bindings(),'resource_limits':{'CPU_soft':15,'CPU_hard':20,'file_bytes':2*1024*1024},'declared_outputs':list(map(str,outputs))}
 if meta.exists():
  r=json.loads(meta.read_text());unsigned={k:v for k,v in r.items() if k!='receipt_sha256'}
  if r.get('receipt_sha256')!=digest(unsigned):raise StaleReceipt(f'{tag}: receipt integrity mismatch')
  if r.get('basis')!=basis or r.get('argv')!=args:raise StaleReceipt(f'{tag}: argv/input/source/compiler/environment changed')
  expected_paths=[str(d/(tag+'.stdout')),str(d/(tag+'.stderr'))]
  if [r.get('stdout'),r.get('stderr')]!=expected_paths:raise StaleReceipt(f'{tag}: stream path changed')
  for key in ['stdout','stderr']:
   p=Path(r[key])
   if not p.is_file() or sha(p)!=r[key+'_sha256']:raise StaleReceipt(f'{tag}: {key} content changed')
  if set(r.get('output_hashes',{}))!=set(map(str,outputs)):raise StaleReceipt(f'{tag}: declared outputs changed')
  for p,h in r['output_hashes'].items():
   exists=Path(p).is_file()
   if (h is None and exists) or (h is not None and (not exists or sha(p)!=h)):raise StaleReceipt(f'{tag}: generated artifact changed')
  return r
 start=time.monotonic();stdout=d/(tag+'.stdout');stderr=d/(tag+'.stderr');timed=False
 with stdout.open('wb') as so,stderr.open('wb') as se:
  try:p=subprocess.run(args,stdout=so,stderr=se,timeout=timeout,cwd=d,env=env,preexec_fn=limits);code=p.returncode
  except subprocess.TimeoutExpired:timed=True;code=None
 # Source/tool replacement during execution is never a reusable receipt.
 if {str(p):sha(p) for p in inputs}!=basis['input_hashes'] or compiler_bindings()!=basis['compiler_hashes']:raise StaleReceipt(f'{tag}: input changed while running')
 r={'schema':'bend-cpu-receipt-v2','basis':basis,'argv':args,'exit':code,'timeout':timed,'timeout_seconds':timeout,'elapsed_seconds':time.monotonic()-start,'stdout':str(stdout),'stderr':str(stderr),'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr),'output_hashes':{str(p):sha(p) if p.is_file() else None for p in outputs}}
 r['receipt_sha256']=digest(r);tmp=meta.with_suffix('.tmp.json');tmp.write_text(json.dumps(r,indent=2)+'\n');tmp.replace(meta);return r

def runtime_exact(step,want):
 """Expected text is the #| assertion plus one terminal newline."""
 expected=(want+'\n').encode()
 return not step['timeout'] and step['exit']==0 and Path(step['stdout']).read_bytes()==expected and Path(step['stderr']).read_bytes()==b''
