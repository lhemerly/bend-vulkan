"""Source-only admission/receipt adapter. No subprocess or execution API.

The reviewed manifest is a proposal, never a permit. This module prepares an
immutable delta and isolation specification for independent review only.
"""
from pathlib import Path
import argparse, collections, hashlib, json, re, shutil, zipfile

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'bend-vulkan-feasibility/source'
OUT=ROOT/'evidence/cpu-admission-adapter-v1'
SEED=ROOT/'evidence/cpu-compatibility-ledger-v10/LEDGER.json'
MANIFEST=OUT/'independent-review/PROPOSED-ADMISSION-MANIFEST.json'
REVIEW=OUT/'bend-cpu-source-admission-review.zip'
REVIEW_SHA='774650d4ae80a5b1a61aa93c23f5d302b2a3e717c60d67847dea6ca27149072e'
MODES={
 'bounded-stdout-cpu':['check','interp','upstream-c','fork-c','build-c','native-t1','native-t2','upstream-js','js'],
 'checker-only':['check'],
 'pure-interpreter-only':['check','interp'],
 'pure-interpreter-and-printer-refusal':['check','interp','upstream-c','fork-c','upstream-js'],
}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)
def diagnostic_tidy(s):return '\n'.join(l.rstrip(' \t') for l in s.split('\n')).strip()

class AdmissionAdapter:
 def __init__(self):
  require(sha(REVIEW)==REVIEW_SHA,'independent review archive changed')
  self.manifest_bytes=MANIFEST.read_bytes();self.manifest=json.loads(self.manifest_bytes)
  with zipfile.ZipFile(REVIEW) as z:
   require(z.read('PROPOSED-ADMISSION-MANIFEST.json')==self.manifest_bytes,'manifest not the exact independently reviewed archive member')
   for name,h in json.loads(z.read('SHA256SUMS.json')).items():
    expected=h if isinstance(h,str) else h['sha256']
    require(hashlib.sha256(z.read(name)).hexdigest()==expected,'review member hash changed: '+name)
  require(self.manifest.get('review_only') is True and self.manifest.get('execution_enabled') is False and self.manifest.get('admission_applied') is False,'review-only state required')
  require(self.manifest.get('schema')=='bend-proposed-admission-manifest-v1','unknown manifest schema')
  self.seed_bytes=SEED.read_bytes();self.seed=json.loads(self.seed_bytes)
  require(self.manifest['reviewed_commit']==self.seed['pinned_commit'],'commit changed')
  require(sha(SOURCE/'bend2/base.bend')==self.manifest['base_sha256'],'prelude changed')
  # Read hash-binding logic only; never invoke run_step or load a Bend module.
  from strict_cpu_receipts import compiler_bindings, binding_sha
  self.compiler_bindings=compiler_bindings;self.binding_sha=binding_sha
  self.context=compiler_bindings()
  self.entries={};rows={r['path']:r for r in self.seed['files']}
  for entry in self.manifest['entries']:
   rel=entry.get('path');require(isinstance(rel,str),'missing path')
   p=SOURCE/rel
   require(not Path(rel).is_absolute() and '..' not in Path(rel).parts and p.resolve()==SOURCE.resolve()/rel and p.is_file() and not p.is_symlink(),'noncanonical source path')
   require(rel not in self.entries,'duplicate admission path')
   require(entry.get('mode') in MODES,'missing or unknown mode')
   require(entry.get('reviewed_stage_names')==MODES[entry['mode']],'wrong allowed stages')
   require(sha(p)==entry['sha256']==rows[rel]['sha256'],'source hash changed')
   require(rows[rel]['status']=='pending-safety-review' and bool(rows[rel]['risk']),'risk record unexpectedly admitted')
   lines=p.read_text().splitlines();imports=[l for l in lines if re.match(r'^\s*import\b',l)]
   require(all(l.strip()=='import Base' for l in imports),'Base-only immutable import restriction')
   require(entry['own_imports']==(['Base'] if imports else []),'reviewed imports changed')
   contract=entry.get('expected_contract');require(isinstance(contract,dict),'missing golden')
   raw=b'\n'.join(l[2:] for l in p.read_bytes().split(b'\n') if l.startswith(b'#|'))
   if entry['mode']=='checker-only':
    require(contract.get('exit')==1 and isinstance(contract.get('diagnostic'),str),'checker contract missing')
    require(diagnostic_tidy(raw.decode())==contract['diagnostic'],'checker golden changed')
   else:
    require(contract.get('exit')==0 and contract.get('stderr_utf8')=='','runtime contract changed')
    require(raw+b'\n'==contract.get('stdout_utf8','').encode(),'raw runtime golden changed')
   self.entries[rel]=entry
  require(collections.Counter(e['mode'] for e in self.entries.values())=={'bounded-stdout-cpu':17,'checker-only':11,'pure-interpreter-only':1,'pure-interpreter-and-printer-refusal':1},'exact30 mode counts changed')
  self.binding={'manifest_sha256':hashlib.sha256(self.manifest_bytes).hexdigest(),'review_archive_sha256':REVIEW_SHA,'adapter_sha256':sha(__file__),'baseline_ledger_sha256':hashlib.sha256(self.seed_bytes).hexdigest(),'compiler_dependency_hashes':self.context,'source_only':True,'execution_enabled':False}

 def lookup(self,path,source_hash,mode,golden):
  e=self.entries.get(path)
  require(e is not None,'unreviewed path')
  require((source_hash,mode,golden)==(e['sha256'],e['mode'],e['expected_contract']),'path/hash/mode/golden mismatch')
  require(sha(SOURCE/path)==source_hash,'source changed after lookup')
  require(MANIFEST.read_bytes()==self.manifest_bytes and self.binding_sha(SEED)==self.binding['baseline_ledger_sha256'],'manifest/baseline mutated')
  require(self.compiler_bindings()==self.context and sha(__file__)==self.binding['adapter_sha256'],'dependency/adapter mutated')
  return e

 def receipt_binding(self,entry,stage):
  require(stage in MODES[entry['mode']],'stage not admitted')
  return digest({'adapter_binding':self.binding,'path':entry['path'],'source_sha256':entry['sha256'],'mode':entry['mode'],'golden':entry['expected_contract'],'stage':stage,'argv':self.stage_argv(entry,stage)})

 def stage_argv(self,entry,stage):
  """Immutable CPU-only argv recipe; output location is a proposal, not created."""
  require(stage in MODES[entry['mode']],'unadmitted stage')
  d=OUT/'planned-disposable'/hashlib.sha256(entry['path'].encode()).hexdigest()[:20]
  bun=str(Path(shutil.which('bun') or '/missing-bun').resolve())
  clang=str(Path(shutil.which('clang') or '/missing-clang').resolve())
  if stage in ('check','interp'):return [bun,str(ROOT/'tools/cpu_ledger_probe_strict.ts'),stage,str(SOURCE/entry['path'])]
  if stage in ('upstream-c','fork-c','upstream-js'):
   dest={'upstream-c':'upstream.c','fork-c':'fork.c','upstream-js':'program.js'}[stage]
   return [bun,str(ROOT/'tools/cpu_ledger_probe_strict.ts'),stage,str(SOURCE/entry['path']),str(d/dest)]
  if stage=='build-c':return [clang,'-O1','-std=c11',str(d/'upstream.c'),'-lm','-o',str(d/'native')]
  if stage in ('native-t1','native-t2'):return [str(d/'native'),'--gpu','off','--threads','1' if stage=='native-t1' else '2']
  return [bun,str(d/'program.js')]

 def classify(self,entry,receipts):
  """Pure classifier for future independently verified isolated receipts.

  This is not an executor or an admission permit. Unexpected checker success
  cannot promote checker-only; printer observation never promotes compilation.
  """
  self.lookup(entry['path'],entry['sha256'],entry['mode'],entry['expected_contract'])
  allowed=MODES[entry['mode']]
  require(set(receipts).issubset(allowed),'unreviewed stage receipt')
  for name,r in receipts.items():
   require(r.get('binding_sha256')==self.receipt_binding(entry,name),'stale/unbound path/hash/mode/golden/stage receipt')
   require(r.get('stage')==name and r.get('isolated_execution_verified') is True,'unverified isolation receipt')
   require(r.get('argv')==self.stage_argv(entry,name),'CPU-only argv changed')
   require(r.get('receipt_sha256')==digest({k:v for k,v in r.items() if k!='receipt_sha256'}),'receipt changed')
   require(isinstance(r.get('stdout_hex'),str) and isinstance(r.get('stderr_hex'),str),'missing raw streams')
   require(r.get('timeout') is False,'timeout remains failure')
  check=receipts.get('check')
  if check is None:return 'incomplete-NOT-passed'
  if entry['mode']=='checker-only':
   require(set(receipts)=={'check'},'checker-only must never enter another stage')
   text=bytes.fromhex(check['stdout_hex']).decode()+bytes.fromhex(check['stderr_hex']).decode()
   text+='\nexit '+str(check['exit']) if check['exit'] else ''
   return 'pass-expected-negative' if check['exit']==1 and diagnostic_tidy(text)==entry['expected_contract']['diagnostic'] else 'failure-checker-only-NO-promotion'
  if check['exit']!=0 or bytes.fromhex(check['stderr_hex'])!=b'' or bytes.fromhex(check['stdout_hex'])!=b'CHECK_OK\n':return 'failure-check-NO-promotion'
  interp=receipts.get('interp')
  if interp is None:return 'incomplete-NOT-passed'
  def exact(r):return r['exit']==0 and bytes.fromhex(r['stdout_hex'])==entry['expected_contract']['stdout_utf8'].encode() and bytes.fromhex(r['stderr_hex'])==b''
  if not exact(interp):return 'failure-interpreter'
  if entry['mode']=='pure-interpreter-only':return 'pass-check-interpreter-C_JS-not-applicable'
  if entry['mode']=='pure-interpreter-and-printer-refusal':
   if any(s not in receipts for s in allowed):return 'incomplete-C_JS-NOT-passed'
   for name in ('upstream-c','fork-c','upstream-js'):
    r=receipts[name];text=bytes.fromhex(r['stdout_hex'])+bytes.fromhex(r['stderr_hex'])
    if r['exit']!=1 or re.search(rb"Error: main's type .* cannot be printed",text) is None:return 'failure-printer-observation-NO-build-or-runtime'
   return 'pass-check-interpreter-printer-ineligible-C_JS-NOT-passed'
  if any(s not in receipts for s in allowed):return 'incomplete-NOT-passed'
  for name in ('upstream-c','fork-c','build-c','upstream-js'):
   if receipts[name]['exit']!=0:return 'failure-emission-or-build'
  c1=receipts['upstream-c'].get('artifact_sha256');c2=receipts['fork-c'].get('artifact_sha256')
  require(isinstance(c1,str) and re.fullmatch('[0-9a-f]{64}',c1) is not None and c1==c2,'default C parity missing or unequal')
  return 'pass-CPU-lanes-default-C-parity' if all(exact(receipts[n]) for n in ('native-t1','native-t2','js')) else 'failure-CPU-lane'

 def next_stage(self,entry,receipts):
  """Return a review-plan transition only; never launch a process."""
  self.lookup(entry['path'],entry['sha256'],entry['mode'],entry['expected_contract'])
  stages=MODES[entry['mode']]
  require(list(receipts)==stages[:len(receipts)],'stage order/closure changed')
  state=self.classify(entry,receipts)
  if state.startswith(('failure','pass-')):return None
  if entry['mode']=='checker-only':return 'check' if not receipts else None
  for name,r in receipts.items():
   if entry['mode']=='pure-interpreter-and-printer-refusal' and name in ('upstream-c','fork-c','upstream-js'):
    text=bytes.fromhex(r['stdout_hex'])+bytes.fromhex(r['stderr_hex'])
    require(r['exit']==1 and re.search(rb"Error: main's type .* cannot be printed",text) is not None,'printer observation cannot promote on unexpected success/refusal')
   else:require(r['exit']==0,'failed intermediate stage cannot promote')
  if 'interp' in receipts:
   r=receipts['interp'];require(bytes.fromhex(r['stdout_hex'])==entry['expected_contract']['stdout_utf8'].encode() and bytes.fromhex(r['stderr_hex'])==b'','wrong interpreter bytes cannot promote')
  if 'fork-c' in receipts and entry['mode']=='bounded-stdout-cpu':
   a=receipts['upstream-c'].get('artifact_sha256');b=receipts['fork-c'].get('artifact_sha256')
   require(isinstance(a,str) and re.fullmatch('[0-9a-f]{64}',a) is not None and a==b,'C parity required before build')
  for name in ('native-t1','native-t2','js'):
   if name in receipts:
    r=receipts[name];require(bytes.fromhex(r['stdout_hex'])==entry['expected_contract']['stdout_utf8'].encode() and bytes.fromhex(r['stderr_hex'])==b'','wrong runtime bytes cannot promote')
  return stages[len(receipts)] if len(receipts)<len(stages) else None

 def prepare(self):
  mounts=[SOURCE/'bend2',ROOT/'evidence/upstream/bend.ts',ROOT/'fork/compiler',ROOT/'tools/cpu_ledger_probe_strict.ts']
  mounts += [SOURCE/p for p in self.entries]
  bun=Path(shutil.which('bun') or '/missing-bun').resolve();clang=Path(shutil.which('clang') or '/missing-clang').resolve()
  mounts.append(bun)
  isolation={'status':'UNQUALIFIED-REVIEW-ONLY-NO-EXECUTION','backend':'bubblewrap','bwrap_binary':shutil.which('bwrap'),
   'namespace_flags':['--unshare-all','--die-with-parent','--new-session','--clearenv'],
   'readonly_system_mounts':['/usr','/lib','/lib64'],
   'readonly_project_mounts':[str(p) for p in mounts],
   'root_policy':'empty private root; create parent dirs; bind ONLY listed sources/tools and system libraries; no whole-root/home/project/.git/credential mounts',
   'writable_mounts':['per-case disposable output directory only','private tmpfs /tmp'],
   'devices':'minimal synthetic /dev; NO GPU/render/GUI/audio devices; private /proc',
   'environment':{'PATH':'/usr/bin:/bin','LANG':'C','BEND_LIB':'/nonexistent-offline-no-hub','HOME':'/nonexistent-no-home'},
   'stdin':'DEVNULL; close inherited descriptors','native_argv':['<bound-output>/native','--gpu','off','--threads','1 or2 exactly'],
   'forbidden_flags':['--gpu-build'],'CPU_soft_seconds':15,'CPU_hard_seconds':20,'wall_seconds':{'probe':15,'build':30,'native_JS':5},'file_bytes':2097152,'core_bytes':0,
   'memory':'Require separately delegated/private cgroup RSS limit (proposal2GiB) and pids.max128 before any stage; DO NOT use low RLIMIT_AS: native reserves8GiB virtual space. Never modify PMI/Leira/shared cgroups.',
   'cleanup':'Separate host process group; timeout/failure/finally SIGTERM then SIGKILL whole group; private PID namespace init must reap descendants; bwrap dies with parent. Verify no worker before release; remove disposable writable directory.',
   'qualification_required':['namespace capability under current permissions','offline network denial','no credentials/host paths/devices visible','toolchain/runtime image hashes','private delegated RSS+pids control availability','process-tree timeout/parent-death cleanup','internal pipes/threads/SIGPIPE compatibility'],
   'execution_permitted':False,'execution_transport_implemented':False}
  records=[]
  seedrows={r['path']:r for r in self.seed['files']}
  for rel,e in self.entries.items():
   self.lookup(rel,e['sha256'],e['mode'],e['expected_contract'])
   records.append({'path':rel,'source_sha256':e['sha256'],'allowed_mode':e['mode'],'golden':e['expected_contract'],'original_risk':seedrows[rel]['risk'],'original_status':seedrows[rel]['status'],'delta_status':'proposed-unadmitted-NOT-executed','allowed_stages':MODES[e['mode']],'planned_argv':{s:self.stage_argv(e,s) for s in MODES[e['mode']]},'stage_binding_sha256':{s:self.receipt_binding(e,s) for s in MODES[e['mode']]},'stages':{}})
  delta={'schema':'bend-source-admission-delta-v1','binding':self.binding,'records':records,'baseline_ancestry':{'path':str(SEED),'sha256':sha(SEED),'accounted_cases':621,'rows_modified':0,'receipts_reused_as_fresh':0},'isolation':isolation,'execution_enabled':False,'candidate_executions':0,'GPU_dispatches':0}
  (OUT/'PROPOSED-DELTA.json').write_text(json.dumps(delta,indent=2)+'\n')
  (OUT/'ISOLATION-REVIEW.json').write_text(json.dumps(isolation,indent=2)+'\n')
  print(json.dumps({'proposed_records':len(records),'mode_counts':dict(collections.Counter(e['mode'] for e in self.entries.values())),'candidate_executions':0,'baseline_rows_modified':0,'execution_enabled':False,'isolation_qualified':False},indent=2))

if __name__=='__main__':
 parser=argparse.ArgumentParser(description='Prepare source-only proposed admission; no execution supported')
 parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
 if not args.prepare:parser.error('--prepare required; candidate execution is disabled')
 AdmissionAdapter().prepare()
