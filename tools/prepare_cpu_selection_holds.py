"""Source-only proposed selection holds; never execute candidates or edit ledger."""
from pathlib import Path
import collections, hashlib, json

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'bend-vulkan-feasibility/source'
SEED=ROOT/'evidence/cpu-compatibility-ledger-v10/LEDGER.json'
OUT=ROOT/'evidence/cpu-selection-holds-v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
 if not ok:raise ValueError(msg)
def prepare():
 original=SEED.read_bytes();ledger=json.loads(original);held=[]
 for row in ledger['files']:
  if row['status']!='pending':continue
  p=SOURCE/row['path'];require(sha(p)==row['sha256'],'pinned source changed')
  raw=p.read_bytes();payloads=[l[2:] for l in raw.split(b'\n') if l.startswith(b'#|')]
  if payloads:continue
  held.append({'path':row['path'],'source_sha256':row['sha256'],'original_status':row['status'],'original_risk':row['risk'],
   'has_main_per_official_gate':row['main_marker_per_upstream_gate'],'has_golden_marker':False,'golden_marker_count':0,
   'reason':'no-source-oracle','selection_hold':True,'execution_enabled':False,'allowed_execution_stages':[],
   'proposed_contract':{'stdout':None,'stderr':None,'exit':None,'diagnostic':None,'status':'UNSPECIFIED-DO-NOT-INFER'},
   'release_requirements':['independent oracle/designated nonexecution-helper role','exact source-bound stage/mode contract','independent contract and resource review','separate execution authorization'],
   'note':'No marker is not an explicit empty marker. Do not invent empty stdout, successful exit, verdict golden or benchmark/demonstration oracle.'})
 require(len(held)==54 and sum(h['has_main_per_official_gate'] for h in held)==23,'independent54/23 scope changed')
 row=next(r for r in ledger['files'] if r['path']=='tests/run/nat_overflow.bend');require(row['status']=='pending' and not row['risk'],'overflow classification changed')
 raw=(SOURCE/row['path']).read_bytes();require(hashlib.sha256(raw).hexdigest()==row['sha256'],'overflow source changed')
 payloads=[l[2:] for l in raw.split(b'\n') if l.startswith(b'#|')]
 require(payloads==[b'bend: a Nat past the largest immediate 2^48-1',b'exit 1'],'overflow raw golden changed')
 error=payloads[0]+b'\n'
 held.append({'path':row['path'],'source_sha256':row['sha256'],'original_status':row['status'],'original_risk':row['risk'],
  'has_main_per_official_gate':row['main_marker_per_upstream_gate'],'has_golden_marker':True,'golden_marker_count':2,
  'golden_payload_lines_hex':[p.hex() for p in payloads],'reason':'expected-runtime-failure-not-success-stdout','selection_hold':True,'execution_enabled':False,
  'allowed_execution_stages':[],'proposed_mode':'runtime-failure-CPU-NOT-admitted',
  'proposed_contract':{'check':{'exit':0,'stdout_hex':b'CHECK_OK\n'.hex(),'stderr_hex':''},
   'interp':{'exit':1,'stdout_hex':'','stderr_hex':error.hex()},
   'native-t1':{'exit':1,'stdout_hex':'','stderr_hex':error.hex(),'argv_flags':['--gpu','off','--threads','1']},
   'native-t2':{'exit':1,'stdout_hex':'','stderr_hex':error.hex(),'argv_flags':['--gpu','off','--threads','2']},
   'js':{'exit':1,'stdout_hex':'','stderr_hex':error.hex()},'emission_and_build':'Would require success and default C-byte parity before native work; no stage admitted by this proposal',
   'normalization':'NONE; source exit marker is process metadata, never stdout; exact lane-specific streams are a source-derived proposal requiring independent review'},
  'source_evidence':{'compiler_sha256':sha(SOURCE/'bend2/comp.ts'),'strict_probe_sha256':sha(ROOT/'tools/cpu_ledger_probe_strict.ts'),
   'references':['comp.ts:468 nat_chk throws overflow text','comp.ts:1299 exported io_run calls generated JS','comp.ts:3696–3713 C err_fail emits stderr/_exit1','comp.ts:6167–6203 JS io_exit catch -> io_errs(fd2)/exit1','comp.ts:6351–6400 IO loop rethrows overflow','cpu_ledger_probe_strict.ts final catch console.error/process.exitCode1'],
   'reasoning':'main.out computes Nat.mul(2^24,2^24)=2^48 before IO.print; overflow prevents any print. No lane was executed to confirm this source-derived contract.'},
  'release_requirements':['independent raw per-lane failure-contract review','fresh source/manifest/policy/argv-bound delta','qualified offline credential-free resource isolation','separate execution authorization'],
  'note':'Frozen expected_negative=false does not make an expected exit1 program a success-stdout case. Do not normalize output or treat timeout/signal as expected refusal.'})
 result={'schema':'bend-proposed-selection-holds-v1','review_only':True,'execution_enabled':False,'ledger_modified':False,'source_executions':0,
  'binding':{'baseline_path':str(SEED),'baseline_sha256':hashlib.sha256(original).hexdigest(),'pinned_commit':ledger['pinned_commit'],'hold_preparer_sha256':sha(__file__)},
  'counts':{'no_oracle':54,'no_oracle_with_main':23,'no_oracle_without_main':31,'runtime_failure':1,'total_proposed_holds':55,'ordinary_pending_records':810,'ordinary_pending_other_records':755,'safety_review_records_unchanged':249,'accounted_cases_unchanged':621},
  'held_records':held,'activation':'Not an active permit. Integrate deny filter only after review; unchanged strict harness currently has no oracle-presence/runtime-failure selection gate. All wider execution remains held.'}
 require(SEED.read_bytes()==original,'baseline changed during source review')
 OUT.mkdir(exist_ok=True);(OUT/'PROPOSED-HOLDS.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result['counts'],indent=2))

def screen_success_stdout_request(paths,manifest,ledger):
 """Pure future selection screen: denied records cannot enter stdout-success mode.

 No execution or status mutation. Checker/verdict modes need their own review;
 screening does not authorize otherwise eligible-looking records.
 """
 require(manifest.get('review_only') is True and manifest.get('execution_enabled') is False,'unreviewed holds state')
 raw_seed=SEED.read_bytes()
 require(hashlib.sha256(raw_seed).hexdigest()==manifest['binding']['baseline_sha256'] and ledger==json.loads(raw_seed),'holds/ledger ancestry changed')
 require(manifest==json.loads((OUT/'PROPOSED-HOLDS.json').read_text()),'hold manifest mutated')
 require(sha(__file__)==manifest['binding']['hold_preparer_sha256'],'selection policy changed')
 held={r['path']:r for r in manifest['held_records']};rows={r['path']:r for r in ledger['files']}
 require(len(paths)==len(set(paths)),'duplicate path')
 for rel in paths:
  require(rel in rows,'unknown inventory path');r=rows[rel]
  require(r['status']=='pending' and not r['risk'],'record already accounted or safety-held')
  p=SOURCE/rel;require(p.resolve()==SOURCE.resolve()/rel and sha(p)==r['sha256'],'noncanonical or changed source')
  require(rel not in held,'explicit source selection hold: '+rel)
  payloads=[l[2:] for l in p.read_bytes().split(b'\n') if l.startswith(b'#|')]
  require(bool(payloads),'missing oracle cannot become empty successful output')
  require(not any(l.startswith(b'exit ') and l!=b'exit 0' for l in payloads),'nonzero/unknown exit contract needs separate failure mode')
 return {'review_only':True,'execution_enabled':False,'screened_paths':paths,'not_an_execution_permit':True}

if __name__=='__main__':prepare()
