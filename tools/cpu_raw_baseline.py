"""Separate strict baseline delta with pre-dispatch approved raw-golden binding.

Default is prepare-only. Historical sources/harness/rows/receipts never change.
No safety-review admission is supported by this runner.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,re,resource,signal,subprocess,sys,time,types

ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parent/'bend-vulkan-feasibility/source'
GOLD=ROOT/'evidence/cpu-raw-golden-sidecar-v1'
FILES={'freeze':GOLD/'SIDECAR-FREEZE.json','sidecar':GOLD/'RAW-GOLDEN-SIDECAR.json',
 'parser':ROOT/'tools/raw_golden_contract.py','baseline':ROOT/'evidence/cpu-compatibility-ledger-v10/LEDGER.json',
 'inventory':ROOT/'evidence/compatibility-roadmap-v1/INVENTORY.json','strict':ROOT/'tools/strict_cpu_receipts.py',
 'resume':ROOT/'tools/cpu_resume.py','probe':ROOT/'tools/cpu_ledger_probe_strict.ts'}
APPROVED={'freeze':'155022a9d3684404a33193f04e0d4e1e421ff3b957fb3235072c0e7911f0b348',
 'sidecar':'236d0f53803af158dde60760ba0fc2e08cd09dee5f0b00e66474e0990084a8c7',
 'parser':'f4466c8ffec38f18ef745c57e2376dba1d1d3b1b963045ed5890e86f24ac6ae7',
 'baseline':'a1a500c6c1c4aad7c79f9086e3381420b13dbd179c5558dc6b97659923dcaa1d',
 'inventory':'c538a9737e7fa0e01bda2ab962827cdaf4ed87ad63eea109acf51abe63b3837e',
 'strict':'19791e7d9792cad15c5ec6dbc15a27f143af2936f48f7f417be46174a6defb37',
 'resume':'bd707f71a12c3a9277746e6fe39337056f7814269536240350c5a48dc7e86345',
 'probe':'4fa319428e7bb4484782e40f7ddbf135701fa5a397e43110220d8421a01748a9'}
FILES['persistence']=ROOT/'tools/cpu_delta_store.py'
APPROVED['persistence']='d0bc2f72e9028cc09b87999e19f8d499bed672cc60229893746d178bcfbbb1e5'
WORD='tests/compile/word_match_cover_key.bend'
def sha(b):return hashlib.sha256(b).hexdigest()
def digest(x):return sha(json.dumps(x,sort_keys=True,separators=(',',':')).encode())
def require(ok,msg):
 if not ok:raise ValueError(msg)
def verified_module(name,path,data):
 # Execute exactly verified captured Python bytes, never a later disk read or
 # pre-existing module/pycache. Only approved pure/helper code is loaded.
 module=types.ModuleType(name);module.__file__=str(path)
 exec(compile(data,str(path),'exec'),module.__dict__);return module

class Policy:
 def __init__(self,files=FILES,pins=APPROVED,source=SOURCE):
  self.files=dict(files);self.pins=dict(pins);self.source=Path(source);self._verified_files={};self.buffers=self.verify()
  self.G=verified_module('_approved_raw_golden',self.files['parser'],self.buffers['parser'])
  self.freeze=json.loads(self.buffers['freeze'])
  require(self.freeze['sidecar_sha256']==self.pins['sidecar'] and self.freeze['parser_policy_sha256']==self.pins['parser'] and self.freeze['inventory_sha256']==self.pins['inventory'] and self.freeze['baseline_ledger_sha256']==self.pins['baseline'],'approved freeze disagreement')
  self.bundle=self.G.FrozenBundle(self.buffers['sidecar'],self.freeze,self.buffers['parser'],self.buffers['inventory'],self.buffers['baseline'])
  ledger=json.loads(self.buffers['baseline']);self._rows={r['path']:json.dumps(r,sort_keys=True).encode() for r in ledger['files']}
  self._groups={r['path']:r['contract_group'] for r in json.loads(self.buffers['sidecar'])['records']}
  self.policy_sha=sha(Path(__file__).read_bytes())
 def verify(self):
  data={}
  for name,path in self.files.items():
   p=Path(path);require(p.resolve()==p,'policy dependency realpath changed')
   s=p.stat();identity=(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
   if name in self._verified_files:
    saved,contents=self._verified_files[name];require(saved==identity,'approved '+name+' file identity changed BEFORE dispatch/import');data[name]=contents
   else:
    data[name]=p.read_bytes();require(sha(data[name])==self.pins[name],'approved '+name+' hash changed BEFORE dispatch/import')
    after=p.stat();require(identity==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'policy file changed while hashing')
    self._verified_files[name]=(identity,data[name])
  return data
 def row(self,path):
  require(path in self._rows,'unknown baseline path');return json.loads(self._rows[path])
 def pin_compiler_context(self,context):
  require(not hasattr(self,'_compiler_context_bytes'),'compiler context already pinned')
  self._compiler_context_bytes=json.dumps(context,sort_keys=True).encode()
 def compiler_context(self,strict):
  require(hasattr(self,'_compiler_context_bytes'),'validated initial compiler context absent')
  initial=json.loads(self._compiler_context_bytes)
  require(strict.compiler_bindings()==initial,'compiler/effect/tool context changed since initial validation')
  return initial
 def bind_ancestry(self,selection):
  ancestry=selection.get('audited_ancestry')
  if ancestry is None:return
  require(ancestry['baseline_sha256']==self.pins['baseline'],'ancestry baseline changed')
  artifacts=ancestry['artifacts']
  base_roles={'word_delta','next100_delta','terminal_audit','results_archive','independent_review_archive'}
  v3_roles=base_roles|{'v3_delta','v3_terminal_audit'}
  v4_roles=v3_roles|{'v4_delta','v4_terminal_audit'}
  require(set(artifacts) in (base_roles,v3_roles,v4_roles,v4_roles|{'v5_partial_delta','v5_partial_audit'}),'incomplete audited ancestry')
  for role,item in artifacts.items():
   rel=Path(item['path']);p=ROOT/rel
   require(not rel.is_absolute() and '..' not in rel.parts and p.resolve()==p,'ancestry artifact realpath changed')
   name='ancestry_'+role
   if name in self.files:require(self.files[name]==p and self.pins[name]==item['sha256'],'ancestry rebound')
   else:self.files[name]=p;self.pins[name]=item['sha256']
  if 'v5_partial_delta' in artifacts:
   hold=selection['resource_hold_anchor'];rel=Path(hold['path']);p=ROOT/rel
   require(not rel.is_absolute() and '..' not in rel.parts and p.resolve()==p,'resource hold realpath changed')
   if 'pressure_hold' in self.files:require(self.files['pressure_hold']==p and self.pins['pressure_hold']==hold['sha256'],'resource hold rebound')
   else:self.files['pressure_hold']=p;self.pins['pressure_hold']=hold['sha256']
  self.verify()
  completed=set()
  for role in ('word_delta','next100_delta'):
   delta=json.loads(self._verified_files['ancestry_'+role][1])
   require(delta['execution_started'] and delta['CPU_interval_released'],'ancestor execution incomplete')
   require(delta['baseline_ancestry']['sha256']==self.pins['baseline'],'ancestor seed changed')
   for record in delta['records']:
    require(record['status'].startswith('pass-') and record['stages'],'ancestor case not audited terminal pass')
    require(record['baseline_row_sha256']==digest(self.row(record['path'])),'ancestor frozen row changed')
    completed.add(record['path'])
  audit=json.loads(self._verified_files['ancestry_terminal_audit'][1])
  require(audit['audit_passed'] and audit['selected_cases']==len(completed)==101,'ancestor audit scope changed')
  require({r['path'] for r in audit['cases']}==completed,'ancestor audit paths changed')
  if 'v3_delta' in artifacts:
   delta=json.loads(self._verified_files['ancestry_v3_delta'][1])
   require(delta['execution_started'] and delta['CPU_interval_released'],'v3 ancestor execution incomplete')
   require(delta['baseline_ancestry']['sha256']==self.pins['baseline'],'v3 ancestor seed changed')
   v3_paths=set()
   for record in delta['records']:
    require(record['status'].startswith('pass-') and record['stages'],'v3 ancestor case not audited terminal pass')
    require(record['baseline_row_sha256']==digest(self.row(record['path'])),'v3 ancestor frozen row changed')
    v3_paths.add(record['path'])
   audit=json.loads(self._verified_files['ancestry_v3_terminal_audit'][1])
   require(audit['audit_passed'] and audit['selected_cases']==len(v3_paths)==len(delta['records'])==100,'v3 ancestor audit scope changed')
   require({r['path'] for r in audit['cases']}==v3_paths,'v3 ancestor audit paths changed')
   require(not completed.intersection(v3_paths),'v3 ancestor overlaps earlier deltas')
   completed.update(v3_paths);require(len(completed)==201,'completed overlay scope changed')
  if 'v4_delta' in artifacts:
   delta=json.loads(self._verified_files['ancestry_v4_delta'][1])
   require(delta['execution_started'] and delta['CPU_interval_released'],'v4 ancestor execution incomplete')
   require(delta['baseline_ancestry']['sha256']==self.pins['baseline'],'v4 ancestor seed changed')
   v4_paths=set()
   for record in delta['records']:
    require(record['status'].startswith('pass-') and record['stages'],'v4 ancestor case not audited terminal pass')
    require(record['baseline_row_sha256']==digest(self.row(record['path'])),'v4 ancestor frozen row changed')
    v4_paths.add(record['path'])
   audit=json.loads(self._verified_files['ancestry_v4_terminal_audit'][1])
   require(audit['audit_passed'] and audit['selected_cases']==len(v4_paths)==len(delta['records'])==100,'v4 ancestor audit scope changed')
   require({r['path'] for r in audit['cases']}==v4_paths,'v4 ancestor audit paths changed')
   require(not completed.intersection(v4_paths),'v4 ancestor overlaps earlier deltas')
   completed.update(v4_paths);require(len(completed)==301,'completed overlay scope changed')
  if 'v5_partial_delta' in artifacts:
   delta=json.loads(self._verified_files['ancestry_v5_partial_delta'][1])
   require(delta['execution_started'] and delta['CPU_interval_released'] and delta['baseline_ancestry']['sha256']==self.pins['baseline'],'partial ancestor not closed against seed')
   records=delta['records'];paths=[r['path'] for r in records]
   require(len(paths)==len(set(paths))==100 and paths==delta['selection']['selection'],'partial ancestor selection changed')
   terminal=set();pending=[];partial=[]
   for record in records:
    require(record['baseline_row_sha256']==digest(self.row(record['path'])),'partial ancestor frozen row changed')
    if record['status']=='pending':
     pending.append(record['path'])
     if record['stages']:partial.append(record)
    else:
     require(record['status'].startswith('pass-') and record['stages'],'partial ancestor terminal status changed')
     terminal.add(record['path'])
   require(len(terminal)==13 and len(pending)==87 and len(partial)==1 and list(partial[0]['stages'])==['check','interp'],'partial ancestor accounting changed')
   require(not completed.intersection(paths),'partial ancestor overlaps completed history')
   audit=json.loads(self._verified_files['ancestry_v5_partial_audit'][1])
   require(audit['audit_passed'] and audit['batch_complete'] is False and audit['terminal_cases']==13 and audit['attempted_cases']==14 and audit['remaining_uncompleted_cases']==87,'partial audit accounting changed')
   require({r['path']:r['fresh_status'] for r in audit['cases']}=={r['path']:r['status'] for r in records},'partial audit case statuses changed')
   require(selection['selection']==pending,'selection must be exact pending partial remainder')
   require(selection.get('partial_receipt_reuse_policy')=='none-fresh-case-execution' and selection.get('pressure_qualification_required') is True,'fresh partial-case execution and pressure review required')
   completed.update(terminal);require(len(completed)==314,'completed overlay scope changed')
  require(not completed.intersection(selection['selection']),'already-completed delta path selected')
  source_pins=selection['source_sha256_by_path']
  require(set(source_pins)==set(selection['selection']),'reviewed source pin scope changed')
  require(all(self.row(p)['sha256']==h for p,h in source_pins.items()),'reviewed source hash changed')
 def eligible(self,path,purpose):
  row=self.row(path);require(not row['risk'],'249 safety-review records remain held')
  if purpose=='word-match-fresh-qualification':
   require(path==WORD and row['status']=='failure-interpreter','only retained Word failure may be freshly qualified')
  else:require(purpose=='next-safe100' and row['status']=='pending','already-accounted/unknown-purpose source held')
  group=self._groups[path];require(group not in ('missing-golden-contract','runtime-negative-contract-review'),'56 missing-oracle/runtime-negative contracts held')
  p=self.source/path;require(not Path(path).is_absolute() and '..' not in Path(path).parts and p.resolve()==self.source.resolve()/path,'source realpath changed')
  data=p.read_bytes();require(sha(data)==row['sha256'],'source changed')
  lines=data.decode().splitlines()
  require(all(l.strip()=='import Base' for l in lines if re.match(r'^\s*import\b',l)),'unchanged exact Base-only/no-import guard')
  require(not re.search(r'\b(?:File|Process|TCP|UDP|TLS|HTTP|Window|Audio|GFX|Gfx|App|Chan)\.',data.decode()),'external effect/source review held')
  require(set(re.findall(r'\bIO\.([A-Za-z_][\w]*)',data.decode()))<= {'print','write','bind','pure','pass'},'unreviewed IO held')
  return row,data,group
 def binding(self,path,purpose):
  self.verify();require(sha(Path(__file__).read_bytes())==self.policy_sha,'integration policy changed')
  row,source,group=self.eligible(path,purpose)
  binding={'approved_pins':dict(self.pins),'integration_policy_sha256':self.policy_sha,'path':path,'source_sha256':row['sha256'],
   'frozen_row_sha256':digest(row),'contract_group':group,'frozen_diagnostic':row['expected_output'],'purpose':purpose}
  if group=='positive-runtime-contract-candidate':binding['raw_golden_binding']=self.bundle.context(row,source)
  return binding
 def fresh_delta(self,selection,out):
  self.bind_ancestry(selection);self.verify();paths=selection['selection'];purpose=selection['purpose']
  require(len(paths)==len(set(paths)) and 0<len(paths)<=100,'duplicate/empty/oversized selection')
  require(purpose!='word-match-fresh-qualification' or paths==[WORD],'Word-only qualification scope')
  records=[]
  for path in paths:
   r,_,group=self.eligible(path,purpose)
   records.append({'path':path,'source_sha256':r['sha256'],'original_status':r['status'],'original_risk':r['risk'],
    'contract_group':group,'status':'pending','stages':{},'baseline_row_sha256':digest(r)})
  return {'schema':'bend-strict-raw-golden-delta-v1','binding':{'approved_pins':dict(self.pins),'integration_policy_sha256':self.policy_sha,
   'selection_sha256':digest(selection),'output_directory':str(out)},'selection':selection,'baseline_ancestry':{'sha256':self.pins['baseline'],'rows_modified':0,'receipts_reattached':0},
   'records':records,'GPU_dispatches':0,'execution_started':False}
 def dispatch(self,path,purpose,delta_row,callback,*args):
  # Exact approved file/source/raw contract verification before EVERY dispatch.
  binding=self.binding(path,purpose);require(delta_row['baseline_row_sha256']==binding['frozen_row_sha256'],'mutable row substituted for frozen history')
  result=callback(binding,*args);self.binding(path,purpose);return result

def load_helpers(policy):
 policy.verify()
 strict=verified_module('strict_cpu_receipts',FILES['strict'],policy.buffers['strict'])
 # cpu_resume's only project import resolves to this verified captured module.
 sys.modules['strict_cpu_receipts']=strict
 resume=verified_module('_approved_cpu_resume',FILES['resume'],policy.buffers['resume'])
 # Historical context is validated under its ORIGINAL helper/context. Fresh
 # integration pins are not attached to, or used to reseal, any old row.
 initial=strict.compiler_bindings()
 resume.validate_resume(json.loads(policy.buffers['baseline']),SOURCE,initial)
 policy.pin_compiler_context(initial);policy.compiler_context(strict)
 return strict,resume

def validate_delta(delta,proposed):
 require(delta['binding']==proposed['binding'] and delta['selection']==proposed['selection'],'delta bindings changed')
 require(delta['schema']==proposed['schema'] and delta['baseline_ancestry']==proposed['baseline_ancestry'],'delta ancestry changed')
 require(len(delta['records'])==len(proposed['records']),'delta selection size changed')
 for actual,frozen in zip(delta['records'],proposed['records']):
  for key in ('path','source_sha256','original_status','original_risk','contract_group','baseline_row_sha256'):
   require(actual.get(key)==frozen[key],'delta immutable selection field changed: '+key)
  require(isinstance(actual.get('stages'),dict),'invalid delta stages')

def require_pressure_qualification(selection,permit):
 if selection.get('pressure_qualification_required'):
  require(permit.get('resource_pressure_qualification_granted') is True and permit.get('resource_admission_granted') is True and permit.get('CPU_baseline_only') is True,'pressure hold remains: explicit CPU-only resource qualification required')
  require(permit.get('supersedes_resource_hold_sha256')==selection['resource_hold_anchor']['sha256'],'CPU-only qualification must identify the held resource decision')

def limits():
 resource.setrlimit(resource.RLIMIT_CPU,(15,20));resource.setrlimit(resource.RLIMIT_FSIZE,(2097152,2097152));resource.setrlimit(resource.RLIMIT_CORE,(0,0));os.umask(0o077)
 # No RLIMIT_AS: native reserves8GiB virtual space.
def producer_lineage(tag,d,stages,input_hashes,delta_binding,contract,context):
 dependencies={'build-c':('emit-upstream-c','upstream.c'),
  'native-t1':('build-c','native'),'native-t2':('build-c','native'),
  'js':('emit-js','program.js')}
 if tag not in dependencies:return {}
 producer,artifact=dependencies[tag];path=str(d/artifact)
 receipt=stages.get(producer);require(isinstance(receipt,dict),'missing producer receipt: '+producer)
 require(receipt.get('receipt_sha256')==digest({k:v for k,v in receipt.items() if k!='receipt_sha256'}),'producer receipt changed')
 require(receipt.get('exit')==0 and receipt.get('timeout') is False,'producer did not succeed')
 basis=receipt.get('basis',{})
 require(basis.get('fresh_delta_binding')==delta_binding and basis.get('frozen_case_contract')==contract and basis.get('compiler_hashes')==context,'producer context changed')
 output=receipt.get('output_hashes',{}).get(path)
 require(output is not None and input_hashes.get(path)==output,'consumer artifact differs from producer output: '+producer)
 return {path:{'producer_stage':producer,'producer_receipt_sha256':receipt['receipt_sha256'],'artifact_sha256':output}}

HOST_GUARD=None

def configure_host_guard(args):
 global HOST_GUARD
 HOST_GUARD=None
 if not args.idle_host_guard_state:return
 require(args.execute and args.authorization and args.authorization_sha256 and args.idle_host_policy_sha256,'guard requires exact reviewed grant')
 permit_path=Path(args.authorization).resolve();require(permit_path.is_relative_to((ROOT/'evidence').resolve()),'guard authorization outside evidence')
 raw=permit_path.read_bytes();require(sha(raw)==args.authorization_sha256,'guard authorization changed');permit=json.loads(raw)
 require(permit.get('idle_host_policy_review_passed') is True and permit.get('CPU_window_granted') is True and permit.get('idle_host_policy_sha256')==args.idle_host_policy_sha256,'idle-host stage guard not granted')
 state_directory=Path(args.idle_host_guard_state).resolve();require(state_directory.is_relative_to((ROOT/'evidence').resolve()),'guard state outside evidence')
 source=ROOT/'tools/cpu_correctness_host_guard_v2.py';body=source.read_bytes();require(sha(body)==permit.get('idle_guard_source_sha256'),'stage guard source changed')
 module=types.ModuleType('cpu_idle_host_guard');module.__file__=str(source);exec(compile(body,str(source),'exec'),module.__dict__)
 HOST_GUARD=module.IdleGuard(state_directory,args.idle_host_policy_sha256,args.authorization_sha256)
 require_host_activity()

def require_host_activity():
 if HOST_GUARD is None:return
 try:HOST_GUARD.check()
 except Exception as exc:
  try:(ROOT/'evidence/CPU-PAUSE').touch()
  except Exception as pause_error:raise RuntimeError('idle-host refusal; pause write failed: '+repr(pause_error)) from exc
  raise

def run_step(policy,strict,delta_binding,contract,d,tag,args,timeout,stages=None):
 context=policy.compiler_context(strict)
 d=Path(d).resolve();args=list(map(str,args));inputs,outputs=strict.declared_paths(args)
 input_hashes={str(p):strict.sha(p) for p in inputs}
 lineage=producer_lineage(tag,d,stages or {},input_hashes,delta_binding,contract,context)
 env={'PATH':os.environ['PATH'],'LANG':'C','BEND_LIB':str(ROOT/'evidence/cpu-compatibility-ledger-v1/no-hub')}
 basis={'argv':args,'cwd':str(d),'timeout_seconds':timeout,'environment':env,'input_hashes':input_hashes,
  'compiler_hashes':context,'consumed_producers':lineage,'resource_limits':{'CPU_soft':15,'CPU_hard':20,'file_bytes':2097152,'core_bytes':0},
  'declared_outputs':list(map(str,outputs)),'fresh_delta_binding':delta_binding,'frozen_case_contract':contract}
 if 'raw_golden_binding' in contract:basis['raw_golden_binding']=contract['raw_golden_binding']
 if HOST_GUARD is not None:basis['idle_host_guard_binding']={'policy_sha256':HOST_GUARD.policy_sha,'grant_sha256':HOST_GUARD.grant_sha}
 meta=d/(tag+'.json');stdout=d/(tag+'.stdout');stderr=d/(tag+'.stderr')
 if meta.exists():
  r=json.loads(meta.read_text());require(r.get('basis')==basis,'old/stale receipt cannot reattach new golden binding')
  require(r.get('receipt_sha256')==digest({k:v for k,v in r.items() if k!='receipt_sha256'}),'receipt changed')
  require(r['stdout']==str(stdout) and r['stderr']==str(stderr),'receipt stream path changed')
  require(sha(stdout.read_bytes())==r['stdout_sha256'] and sha(stderr.read_bytes())==r['stderr_sha256'],'receipt streams changed')
  require(r['output_hashes']=={str(p):strict.sha(p) if p.is_file() else None for p in outputs},'output artifact changed')
  policy.compiler_context(strict)
  return r
 require(not stdout.exists() and not stderr.exists(),'unbound leftover stream cannot become fresh')
 start=time.monotonic();timed=False;p=None
 with stdout.open('xb') as so,stderr.open('xb') as se:
  try:
   policy.compiler_context(strict)
   require({str(p):strict.sha(p) for p in inputs}==input_hashes,'consumer input changed before dispatch')
   require_host_activity() # Fresh physical-host check immediately before EVERY new stage.
   p=subprocess.Popen(args,cwd=d,env=env,stdin=subprocess.DEVNULL,stdout=so,stderr=se,close_fds=True,start_new_session=True,preexec_fn=limits)
   try:code=p.wait(timeout=timeout)
   except subprocess.TimeoutExpired:timed=True;code=None
  finally:
   if p is not None:
    for sig in (signal.SIGTERM,signal.SIGKILL):
     try:os.killpg(p.pid,sig)
     except ProcessLookupError:pass
    p.wait()
 policy.compiler_context(strict)
 require({str(p):strict.sha(p) for p in inputs}==basis['input_hashes'],'input changed during stage')
 require(producer_lineage(tag,d,stages or {},input_hashes,delta_binding,contract,context)==lineage,'producer lineage changed during stage')
 r={'schema':'bend-cpu-raw-golden-receipt-v1','basis':basis,'argv':args,'exit':code,'timeout':timed,'timeout_seconds':timeout,'elapsed_seconds':time.monotonic()-start,
  'stdout':str(stdout),'stderr':str(stderr),'stdout_sha256':sha(stdout.read_bytes()),'stderr_sha256':sha(stderr.read_bytes()),
  'output_hashes':{str(p):strict.sha(p) if p.is_file() else None for p in outputs}}
 r['receipt_sha256']=digest(r);meta.write_text(json.dumps(r,indent=2)+'\n');return r

def execute_case(policy,strict,delta,record,out,checkpoint=None):
 path=record['path'];purpose=delta['selection']['purpose'];frozen,_,group=policy.eligible(path,purpose)
 d=out/path.removesuffix('.bend');d.mkdir(parents=True,exist_ok=True)
 def step(tag,args,timeout=15):
  require(not (ROOT/'evidence/CPU-PAUSE').exists(),'CPU scheduling pause present')
  r=policy.dispatch(path,purpose,record,lambda binding:run_step(policy,strict,delta['binding'],binding,d,tag,args,timeout,record['stages']))
  record['stages'][tag]=r
  if checkpoint is not None:checkpoint()
  return r
 def probe(tag,mode,dest=None):return step(tag,['bun',FILES['probe'],mode,SOURCE/path,*([dest] if dest else [])])
 def text(r):return Path(r['stdout']).read_text(errors='replace')+Path(r['stderr']).read_text(errors='replace')
 def tidy(s):return '\n'.join(l.rstrip(' \t') for l in s.splitlines()).strip()
 def exact(r):return policy.bundle.exact_fresh_runtime(r,frozen,(SOURCE/path).read_bytes(),Path(r['stdout']).read_bytes(),Path(r['stderr']).read_bytes())
 check=probe('check','check')
 if check['timeout']:return 'timeout-check'
 if check['exit']==0 and not frozen['main_marker_per_upstream_gate']:
  verdict=probe('verdict','verdict');actual=tidy(text(verdict).rstrip('\n')+(f'\nexit {verdict["exit"]}' if verdict['exit'] else ''))
  return 'pass-check-only' if not verdict['timeout'] and actual==tidy(frozen['expected_output']) and verdict['exit']==(1 if frozen['expected_negative'] else 0) else 'failure-check-only'
 if frozen['expected_negative'] and frozen['expected_output'].startswith('SOME PROOFS FAIL'):
  actual=tidy(text(check).rstrip('\n')+(f'\nexit {check["exit"]}' if check['exit'] else ''))
  return 'pass-expected-negative' if check['exit']==1 and actual==tidy(frozen['expected_output']) else 'failure-expected-diagnostic'
 if check['exit']!=0:return 'failure-check'
 require(group=='positive-runtime-contract-candidate','nonruntime contract cannot enter success mode')
 interp=probe('interp','interp')
 if not exact(interp):return 'timeout-interpreter' if interp['timeout'] else 'failure-interpreter'
 if not frozen['candidate_compiled_lanes_per_upstream_gate']:return 'pass-check-interpreter'
 a=probe('emit-upstream-c','upstream-c',d/'upstream.c');b=probe('emit-fork-c','fork-c',d/'fork.c')
 if a['timeout'] or b['timeout']:return 'timeout-emission'
 if a['exit'] or b['exit']:return 'pass-check-interpreter-printer-ineligible' if re.search(r"Error: main's type .* cannot be printed",text(a)) else 'failure-emission'
 if (d/'upstream.c').read_bytes()!=(d/'fork.c').read_bytes():return 'failure-default-C-parity'
 build=step('build-c',['clang','-O1','-std=c11',d/'upstream.c','-lm','-o',d/'native'],30)
 if build['timeout'] or build['exit']:return 'timeout-C-build' if build['timeout'] else 'failure-C-build'
 ok=True
 for threads in (1,2):ok=exact(step('native-t'+str(threads),[d/'native','--gpu','off','--threads',str(threads)],5)) and ok
 js=probe('emit-js','upstream-js',d/'program.js')
 if js['timeout'] or js['exit']:ok=False
 else:ok=exact(step('js',['bun',d/'program.js'],5)) and ok
 return 'pass-CPU-lanes-default-C-parity' if ok else 'timeout-CPU-lane' if any(s['timeout'] for s in record['stages'].values()) else 'failure-CPU-lane'

def main():
 a=argparse.ArgumentParser();a.add_argument('--selection',required=True);a.add_argument('--output',required=True);a.add_argument('--execute',action='store_true');a.add_argument('--authorization');a.add_argument('--authorization-sha256');a.add_argument('--idle-host-guard-state');a.add_argument('--idle-host-policy-sha256');args=a.parse_args();configure_host_guard(args)
 require(re.fullmatch('[A-Za-z0-9_-]+',args.output) is not None,'output must be one fresh evidence directory')
 selection_path=(ROOT/'evidence'/args.selection).resolve();require(selection_path.is_relative_to((ROOT/'evidence').resolve()),'selection outside evidence')
 policy=Policy();selection=json.loads(selection_path.read_text());out=ROOT/'evidence'/args.output;proposed=policy.fresh_delta(selection,out)
 strict,_=load_helpers(policy);out.mkdir(exist_ok=True);delta_path=out/'DELTA.json'
 storage=verified_module('_approved_delta_store',policy.files['persistence'],policy.buffers['persistence']);store=storage.Store(out)
 if delta_path.exists():
  delta=store.load();validate_delta(delta,proposed)
 else:delta=proposed;store.save(delta)
 if not args.execute:
  print(json.dumps({'prepared_records':len(delta['records']),'historical_completed_bindings_validated':621,'baseline_rows_modified':0,'execution_started':False,'CPU_PAUSE':(ROOT/'evidence/CPU-PAUSE').exists()},indent=2));return
 require(args.authorization and args.authorization_sha256,'independent reviewed authorization required')
 permit_path=Path(args.authorization).resolve();require(permit_path.is_relative_to((ROOT/'evidence').resolve()),'authorization outside evidence')
 permit_bytes=permit_path.read_bytes();require(sha(permit_bytes)==args.authorization_sha256,'authorization hash changed');permit=json.loads(permit_bytes)
 require(not permit.get('idle_host_policy_sha256') or HOST_GUARD is not None,'required exact idle-host stage guard omitted')
 require(permit.get('binding_review_passed') is True and permit.get('CPU_window_granted') is True and permit.get('delta_binding')==delta['binding'],'binding review/CPU scheduling authorization absent')
 require_pressure_qualification(selection,permit)
 require(not (ROOT/'evidence/CPU-PAUSE').exists(),'CPU scheduling pause present')
 try:
  delta['execution_started']=True;store.save(delta)
  for record in delta['records']:
   if record['status']=='pending':record['status']=execute_case(policy,strict,delta,record,out,lambda:store.save(delta))
   else:
    # Never skip an unvalidated existing delta record. Re-entering case logic
    # checks every stage basis/input/output and exact raw oracle from this delta.
    require(record['stages'],'terminal delta missing receipts');expected=record['status'];record['status']=execute_case(policy,strict,delta,record,out,lambda:store.save(delta));require(record['status']==expected,'delta classification changed on resume')
   if record['status']=='pass-check-interpreter-printer-ineligible':record['C_JS_compiled_pass']=False
   store.save(delta);print(record['path'],record['status'],flush=True)
 finally:
  (ROOT/'evidence/CPU-PAUSE').touch();delta['CPU_interval_released']=True;store.save(delta)

if __name__=='__main__':main()
