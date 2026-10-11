"""Static upstream gate roles; this never executes source programs."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def main():
 src=ROOT/'evidence/cpu-compatibility-ledger-v4/LANE-LEDGER.json';l=json.loads(src.read_text());direct=helpers=0;nomains=[];positive_nomains=[];runtime_neg=[]
 for r in l['files']:
  p=Path(r['path']);test=r['path'].startswith('tests/');case=test and len(p.parts)==3
  r['official_gate_direct_test_case']=case;r['official_gate_nested_dependency_only']=test and not case;direct+=case;helpers+=test and not case
  r['file_execution_role']='official-direct-test-case' if case else 'nested-test-dependency' if test else 'demo/benchmark/eval/prelude separate obligation'
  r['official_checkup_path']='validation then book_run; no-main -> promise verdict; IO main -> Comp.io_run generated JS; pure main -> term_snf'
  if r['expected_negative']:r['diagnostic_comparison']='upstream-tidy-normalized (not byte-exact)'
  if case and r['expected_negative'] and r['expected_output'].startswith('Error:'):r['expected_negative_phase']='program-or-emission-not-checker';runtime_neg.append(r['path'])
  elif r['expected_negative']:r['expected_negative_phase']='checker-or-no-main-verdict'
  if case and not r['main_marker_per_upstream_gate'] and r['status']=='pending':
   nomains.append(r['path'])
   if not r['expected_negative']:positive_nomains.append(r['path'])
  r['gate_lanes_static']=(['checkup'] if not r['main_marker_per_upstream_gate'] or r['expected_negative'] else ['checkup']+r['candidate_compiled_lanes_per_upstream_gate']) if case else []
 l['classification_summary']={'all_source_files':len(l['files']),'official_direct_test_cases':direct,'nested_test_dependencies_not_cases':helpers,'pending_direct_no_main_cases':len(nomains),'pending_positive_no_main_verdict_cases':len(positive_nomains),'program_or_emission_negative_cases':runtime_neg,'IO_numeric_engine_note':'Comp.io_run emits/runs JS; IO checkup and standalone JS are not independent numeric engines','pending_positive_no_main_paths':positive_nomains}
 l['classification_basis']={'official_gate_sha256':hashlib.sha256((ROOT.parent/'bend-vulkan-feasibility/source/gates/test.ts').read_bytes()).hexdigest(),'derived_from_lane_ledger_sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
 assert direct==1576 and helpers==11 and len(positive_nomains)==24
 assert set(runtime_neg)=={'tests/io/cid_unknown.bend','tests/io/effect_ctr_name.bend','tests/io/main_foreign.bend','tests/reg/array_open_element.bend'}
 (src.parent/'CLASSIFIED-LANE-LEDGER.json').write_text(json.dumps(l,indent=2)+'\n');print(json.dumps(l['classification_summary'],indent=2))
if __name__=='__main__':main()
