"""Resumable CPU-only checkpoint; explicit safe allowlist, all other files pending."""
from pathlib import Path
import argparse,hashlib,json,os,resource,subprocess,time,re
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parent/'bend-vulkan-feasibility/source';PROBE=ROOT/'tools/cpu_ledger_probe_strict.ts'
RUN=['gpu_mark','gpu_trig','fork_shapes','expr_interpreter','closures_hof','bit_walking','binary_search','insertion_sort','if_elif_desugar','inline_applied_fun','float_arithmetic','float_specials']
CHECK=['unit_ctor_mismatch','typed_let_mismatch','unbound_old_builtin','type_in_type','u32_literal_own_u32','type_family_eval','unit_paren_sugar','wrap_not_successor']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tidy(s):return '\n'.join(l.rstrip(' \t') for l in s.splitlines()).strip()
def limits():
 resource.setrlimit(resource.RLIMIT_CPU,(15,20));resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024));os.umask(0o077)
def text(step):return Path(step['stdout']).read_text(errors='replace')+Path(step['stderr']).read_text(errors='replace')
def probe(d,tag,mode,p,dest=None):return run_step(d,tag,['bun',PROBE,mode,p,*([dest] if dest else [])],15)
def checkpoint(out,ledger):
 context=compiler_bindings()
 for row in ledger['files']:
  if terminal(row) and not row.get('completed_binding'):bind_completed(row,SOURCE,ROOT,context)
 ledger['summary']={'files':len(ledger['files']),'statuses':dict((s,sum(x['status']==s for x in ledger['files'])) for s in sorted({x['status'] for x in ledger['files']})),'GPU_dispatches':0};tmp=out/'LEDGER.tmp.json';tmp.write_text(json.dumps(ledger,indent=2)+'\n');tmp.replace(out/'LEDGER.json')
def main():
 global SELECTION_PATH,SEED_PATH
 a=argparse.ArgumentParser();a.add_argument('--output',default='cpu-compatibility-ledger-v5');a.add_argument('--selection',default='cpu-strict-selection.json');a.add_argument('--seed',default='cpu-compatibility-ledger-v4/CLASSIFIED-LANE-LEDGER.json');a.add_argument('--rerun-selected',action='store_true');args=a.parse_args()
 if not re.fullmatch(r'[A-Za-z0-9_-]+',args.output):raise ValueError('output must be one evidence directory name')
 SELECTION_PATH=(ROOT/'evidence'/args.selection).resolve();SEED_PATH=(ROOT/'evidence'/args.seed).resolve()
 if not all(p.is_relative_to((ROOT/'evidence').resolve()) for p in [SELECTION_PATH,SEED_PATH]):raise ValueError('selection/seed must stay within project evidence')
 options={'selection':str(SELECTION_PATH),'seed':str(SEED_PATH),'rerun_selected':args.rerun_selected}
 out=ROOT/'evidence'/args.output;out.mkdir(exist_ok=True)
 manifest=json.loads((ROOT/'evidence/compatibility-roadmap-v1/INVENTORY.json').read_text());ledger_path=out/'LEDGER.json';bindings=ledger_bindings()
 if ledger_path.exists():
  ledger=json.loads(ledger_path.read_text())
  if ledger['bindings']!=bindings:raise StaleReceipt('runner/source/effect/compiler changed: use fresh checkpoint directory')
  if ledger.get('run_options',options)!=options:raise StaleReceipt('run options changed')
  validate_resume(ledger,SOURCE,compiler_bindings())
 else:
  files=[]
  for row in manifest['files']:
   p=SOURCE/row['path'];assert sha(p)==row['sha256'];s=p.read_text();risk=[]
   if row['path'].startswith(('tests/io/','tests/gfx/','demos/io','demos/app_')):risk.append('interactive/IO/environment namespace')
   if re.search(r'\b(?:IO\.(?:read|write|open|system|exec)|Tcp\.|Http\.|Gfx\.|Audio\.)',s):risk.append('external effect source inspection required')
   if any(l.strip()!='import Base' for l in s.splitlines() if re.match(r'^\s*import\b',l)):risk.append('non-Base import closure review')
   files.append(dict(row,status='pending-safety-review' if risk else 'pending',risk=risk,stages={}))
  ledger={'schema':'bend-full-cpu-ledger-v1','pinned_commit':manifest['summary']['pinned_commit'],'bindings':bindings,'run_options':options,'official_assertions_source':str(SOURCE/'gates/test.ts'),'files':files,'notes':['Every file accounted for; static eligibility is not execution.','Pinned library probe avoids original CLI telemetry/updates/hub credentials.','No foreign/non-Base imports or external effect programs executed in checkpoint.']};checkpoint(out,ledger)
 selected=json.loads(SELECTION_PATH.read_text())['selection']
 if len(selected)!=len(set(selected)):raise ValueError('duplicate selected source')
 ledger['batch_selection']=selected
 if not ledger.get('previous_checkpoint'):
  previous=json.loads(SEED_PATH.read_text())
  for previous_row in previous['files']:
   if previous_row['status'].startswith('pass-'):
    if previous_row.get('completed_binding'):validate_completed(previous_row,SOURCE,compiler_bindings())
    else:previous_row['legacy_archive']={'path':str(ROOT/'evidence/cpu-compatibility-ledger-v4/BASELINE220-ARCHIVE.zip'),'sha256':'b1765030fd639f00f6043abac62b2bd569935da481f66fcb536ce7c56f9f3c9f'}
    idx=next(i for i,x in enumerate(ledger['files']) if x['path']==previous_row['path']);assert ledger['files'][idx]['sha256']==previous_row['sha256'];ledger['files'][idx]=previous_row
  ledger['previous_checkpoint']={'path':'cpu-compatibility-ledger-v4/CLASSIFIED-LANE-LEDGER.json','sha256':sha(ROOT/'evidence/cpu-compatibility-ledger-v4/CLASSIFIED-LANE-LEDGER.json')}
  checkpoint(out,ledger)
 if args.rerun_selected and not ledger.get('rerun_initialized'):
  for name in selected:
   row=next(x for x in ledger['files'] if x['path']==name)
   if (out/name.removesuffix('.bend')).exists():raise StaleReceipt('fresh selected rerun directory already contains artifacts')
   row['rerun_of']={'status':row['status'],'source_sha256':row['sha256'],'seed_sha256':sha(SEED_PATH)}
   for key in ['completed_binding','legacy_archive','diagnostic_remediation','original_status','diagnostic_exact_match','interpreter_output_match','default_C_byte_equal','source_current_sha256']:row.pop(key,None)
   row['status']='pending';row['stages']={}
  ledger['rerun_initialized']=True;checkpoint(out,ledger)
 for name in selected:
  if (ROOT/'evidence/CPU-PAUSE').exists():
   checkpoint(out,ledger);print('PAUSED: CPU-PAUSE present',flush=True);return
  row=next(x for x in ledger['files'] if x['path']==name)
  if row['status'] not in ['pending','pending-safety-review']:
   validate_completed(row,SOURCE,compiler_bindings());continue
  assert not row['risk'],(name,row['risk']);p=SOURCE/name;d=out/name.removesuffix('.bend');d.mkdir(parents=True,exist_ok=True);row['source_current_sha256']=sha(p);assert row['source_current_sha256']==row['sha256'];stages=row['stages'];check=probe(d,'check','check',p);stages['check']=check
  if check['timeout']:row['status']='timeout-check';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if check['exit']==0 and not row['main_marker_per_upstream_gate']:
   verdict=probe(d,'verdict','verdict',p);stages['verdict']=verdict;actual=tidy(text(verdict).rstrip('\n')+(f'\nexit {verdict["exit"]}' if verdict['exit'] else ''));row['diagnostic_comparison']='upstream-tidy-normalized';row['status']='pass-check-only' if not verdict['timeout'] and actual==tidy(row['expected_output']) and verdict['exit']==(1 if row['expected_negative'] else 0) else 'failure-check-only';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if row['expected_negative'] and row['expected_output'].startswith('SOME PROOFS FAIL'):
   actual=tidy(text(check).rstrip('\n')+(f'\nexit {check["exit"]}' if check['exit'] else ''));row['diagnostic_exact_match']=actual==tidy(row['expected_output']);row['diagnostic_comparison']='upstream-tidy-normalized';row['status']='pass-expected-negative' if check['exit']==1 and row['diagnostic_exact_match'] else 'failure-expected-diagnostic';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if check['exit']!=0:row['status']='failure-check';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if not row['main_marker_per_upstream_gate']:
   verdict=probe(d,'verdict','verdict',p);stages['verdict']=verdict;row['diagnostic_comparison']='upstream-tidy-normalized';row['status']='pass-check-only' if not verdict['timeout'] and tidy(text(verdict))==tidy(row['expected_output']) and verdict['exit']==0 else 'failure-check-only';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if row['expected_negative']:
   row['status']='pending-runtime-negative-review';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  interp=probe(d,'interp','interp',p);stages['interp']=interp;row['interpreter_output_match']=runtime_exact(interp,row['expected_output'])
  if not row['interpreter_output_match']:row['status']='timeout-interpreter' if interp['timeout'] else 'failure-interpreter';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if not row['candidate_compiled_lanes_per_upstream_gate']:row['status']='pass-check-interpreter';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  upstream=probe(d,'emit-upstream-c','upstream-c',p,d/'upstream.c');fork=probe(d,'emit-fork-c','fork-c',p,d/'fork.c');stages.update(emit_upstream_c=upstream,emit_fork_c=fork)
  if any(x['timeout'] for x in [upstream,fork]):row['status']='timeout-emission';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if upstream['exit'] or fork['exit']:
   row['status']='pass-check-interpreter-printer-ineligible' if re.search(r"Error: main's type .* cannot be printed",text(upstream)) else 'failure-emission';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  row['default_C_byte_equal']=(d/'upstream.c').read_bytes()==(d/'fork.c').read_bytes()
  if not row['default_C_byte_equal']:row['status']='failure-default-C-parity';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  build=run_step(d,'build-c',['clang','-O1','-std=c11',d/'upstream.c','-lm','-o',d/'native'],30);stages['build_c']=build
  if build['timeout'] or build['exit']:row['status']='timeout-C-build' if build['timeout'] else 'failure-C-build';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  ok=True
  for threads in [1,2]:
   step=run_step(d,'native-t'+str(threads),[d/'native','--gpu','off','--threads',str(threads)],5);stages['native_t'+str(threads)]=step
   ok=ok and runtime_exact(step,row['expected_output'])
  js=probe(d,'emit-js','upstream-js',p,d/'program.js');stages['emit_js']=js
  if js['timeout'] or js['exit']:ok=False
  else:
   step=run_step(d,'js',['bun',d/'program.js'],5);stages['js']=step;ok=ok and runtime_exact(step,row['expected_output'])
  row['status']='pass-CPU-lanes-default-C-parity' if ok else 'failure-CPU-lane' if not any(x['timeout'] for x in stages.values()) else 'timeout-CPU-lane';checkpoint(out,ledger);print(name,row['status'],flush=True)
 print(json.dumps(ledger['summary']),flush=True)
from strict_cpu_receipts import run_step,runtime_exact,compiler_bindings,StaleReceipt
from cpu_resume import bind_completed,validate_completed,validate_resume,terminal
def ledger_bindings():
 paths=[PROBE,Path(__file__),SOURCE/'bend2/bend.ts',SOURCE/'bend2/comp.ts',SOURCE/'bend2/base.bend',ROOT/'fork/compiler/capture.ts',SELECTION_PATH,SEED_PATH,ROOT/'evidence/compatibility-roadmap-v1/INVENTORY.json',ROOT/'evidence/cpu-compatibility-ledger-v4/BASELINE220-ARCHIVE.zip']
 return {**{str(p):sha(p) for p in paths},**compiler_bindings()}
SELECTION_PATH=ROOT/'evidence/cpu-strict-selection.json'
SEED_PATH=ROOT/'evidence/cpu-compatibility-ledger-v4/CLASSIFIED-LANE-LEDGER.json'
if __name__=='__main__':main()
