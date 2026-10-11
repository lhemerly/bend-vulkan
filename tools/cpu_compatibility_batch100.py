"""Resumable CPU-only checkpoint; explicit safe allowlist, all other files pending."""
from pathlib import Path
import argparse,hashlib,json,os,resource,subprocess,time,re
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parent/'bend-vulkan-feasibility/source';PROBE=ROOT/'tools/cpu_ledger_probe.ts'
RUN=['gpu_mark','gpu_trig','fork_shapes','expr_interpreter','closures_hof','bit_walking','binary_search','insertion_sort','if_elif_desugar','inline_applied_fun','float_arithmetic','float_specials']
CHECK=['unit_ctor_mismatch','typed_let_mismatch','unbound_old_builtin','type_in_type','u32_literal_own_u32','type_family_eval','unit_paren_sugar','wrap_not_successor']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tidy(s):return '\n'.join(l.rstrip(' \t') for l in s.splitlines()).strip()
def limits():
 resource.setrlimit(resource.RLIMIT_CPU,(15,20));resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024));os.umask(0o077)
def run_step(d,tag,args,timeout):
 meta=d/(tag+'.json')
 if meta.exists():return json.loads(meta.read_text())
 start=time.monotonic();stdout=d/(tag+'.stdout');stderr=d/(tag+'.stderr');timed=False
 with stdout.open('wb') as so,stderr.open('wb') as se:
  try:p=subprocess.run(list(map(str,args)),stdout=so,stderr=se,timeout=timeout,cwd=d,env={'PATH':os.environ['PATH'],'LANG':'C','BEND_LIB':str(ROOT/'evidence/cpu-compatibility-ledger-v1/no-hub')},preexec_fn=limits);code=p.returncode
  except subprocess.TimeoutExpired:timed=True;code=None
 result={'argv':list(map(str,args)),'exit':code,'timeout':timed,'timeout_seconds':timeout,'elapsed_seconds':time.monotonic()-start,'stdout':str(stdout),'stderr':str(stderr),'stdout_sha256':sha(stdout),'stderr_sha256':sha(stderr)};meta.write_text(json.dumps(result,indent=2)+'\n');return result
def text(step):return Path(step['stdout']).read_text(errors='replace')+Path(step['stderr']).read_text(errors='replace')
def probe(d,tag,mode,p,dest=None):return run_step(d,tag,['bun',PROBE,mode,p,*([dest] if dest else [])],15)
def checkpoint(out,ledger):
 ledger['summary']={'files':len(ledger['files']),'statuses':dict((s,sum(x['status']==s for x in ledger['files'])) for s in sorted({x['status'] for x in ledger['files']})),'GPU_dispatches':0};tmp=out/'LEDGER.tmp.json';tmp.write_text(json.dumps(ledger,indent=2)+'\n');tmp.replace(out/'LEDGER.json')
def main():
 a=argparse.ArgumentParser();a.add_argument('--output',default='cpu-compatibility-ledger-v3');args=a.parse_args();out=ROOT/'evidence'/args.output;out.mkdir(exist_ok=True)
 manifest=json.loads((ROOT/'evidence/compatibility-roadmap-v1/INVENTORY.json').read_text());ledger_path=out/'LEDGER.json';bindings={str(p):sha(p) for p in [PROBE,Path(__file__),SOURCE/'bend2/bend.ts',SOURCE/'bend2/comp.ts',SOURCE/'bend2/base.bend',ROOT/'fork/compiler/capture.ts',ROOT/'evidence/cpu-batch-100-selection.json',ROOT/'evidence/cpu-compatibility-ledger-v2/LEDGER.json']}
 if ledger_path.exists():
  ledger=json.loads(ledger_path.read_text());assert ledger['bindings']==bindings,'runner/source changed: use fresh checkpoint directory'
 else:
  files=[]
  for row in manifest['files']:
   p=SOURCE/row['path'];assert sha(p)==row['sha256'];s=p.read_text();risk=[]
   if row['path'].startswith(('tests/io/','tests/gfx/','demos/io','demos/app_')):risk.append('interactive/IO/environment namespace')
   if re.search(r'\b(?:IO\.(?:read|write|open|system|exec)|Tcp\.|Http\.|Gfx\.|Audio\.)',s):risk.append('external effect source inspection required')
   if any(l.strip()!='import Base' for l in s.splitlines() if re.match(r'^\s*import\b',l)):risk.append('non-Base import closure review')
   files.append(dict(row,status='pending-safety-review' if risk else 'pending',risk=risk,stages={}))
  ledger={'schema':'bend-full-cpu-ledger-v1','pinned_commit':manifest['summary']['pinned_commit'],'bindings':bindings,'official_assertions_source':str(SOURCE/'gates/test.ts'),'files':files,'notes':['Every file accounted for; static eligibility is not execution.','Pinned library probe avoids original CLI telemetry/updates/hub credentials.','No foreign/non-Base imports or external effect programs executed in checkpoint.']};checkpoint(out,ledger)
 selected=json.loads((ROOT/'evidence/cpu-batch-100-selection.json').read_text())['selection']
 ledger['batch_selection']=selected
 if not ledger.get('previous_checkpoint'):
  previous=json.loads((ROOT/'evidence/cpu-compatibility-ledger-v2/LEDGER.json').read_text())
  for previous_row in previous['files']:
   if previous_row['status'].startswith('pass-'):
    idx=next(i for i,x in enumerate(ledger['files']) if x['path']==previous_row['path']);assert ledger['files'][idx]['sha256']==previous_row['sha256'];ledger['files'][idx]=previous_row
  ledger['previous_checkpoint']={'path':'cpu-compatibility-ledger-v2/LEDGER.json','sha256':sha(ROOT/'evidence/cpu-compatibility-ledger-v2/LEDGER.json')}
  checkpoint(out,ledger)
 for name in selected:
  if (ROOT/'evidence/CPU-PAUSE').exists():
   checkpoint(out,ledger);print('PAUSED: CPU-PAUSE present',flush=True);return
  row=next(x for x in ledger['files'] if x['path']==name)
  if row['status'] not in ['pending','pending-safety-review']:continue
  assert not row['risk'],(name,row['risk']);p=SOURCE/name;d=out/name.removesuffix('.bend');d.mkdir(parents=True,exist_ok=True);row['source_current_sha256']=sha(p);assert row['source_current_sha256']==row['sha256'];stages=row['stages'];check=probe(d,'check','check',p);stages['check']=check
  if check['timeout']:row['status']='timeout-check';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if row['expected_negative']:
   actual=tidy(text(check).rstrip('\n')+(f'\nexit {check["exit"]}' if check['exit'] else ''));row['diagnostic_exact_match']=actual==tidy(row['expected_output']);row['status']='pass-expected-negative' if check['exit']==1 and row['diagnostic_exact_match'] else 'failure-expected-diagnostic';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  if check['exit']!=0:row['status']='failure-check';checkpoint(out,ledger);print(name,row['status'],flush=True);continue
  interp=probe(d,'interp','interp',p);stages['interp']=interp;row['interpreter_output_match']=not interp['timeout'] and interp['exit']==0 and tidy(text(interp))==tidy(row['expected_output'])
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
   ok=ok and not step['timeout'] and step['exit']==0 and tidy(text(step))==tidy(row['expected_output'])
  js=probe(d,'emit-js','upstream-js',p,d/'program.js');stages['emit_js']=js
  if js['timeout'] or js['exit']:ok=False
  else:
   step=run_step(d,'js',['bun',d/'program.js'],5);stages['js']=step;ok=ok and not step['timeout'] and step['exit']==0 and tidy(text(step))==tidy(row['expected_output'])
  row['status']='pass-CPU-lanes-default-C-parity' if ok else 'failure-CPU-lane' if not any(x['timeout'] for x in stages.values()) else 'timeout-CPU-lane';checkpoint(out,ledger);print(name,row['status'],flush=True)
 print(json.dumps(ledger['summary']),flush=True)
if __name__=='__main__':main()
