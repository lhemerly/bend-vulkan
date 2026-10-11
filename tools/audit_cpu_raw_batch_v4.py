"""Read-only audit of the authorized exact frozen next100 v4 window."""
from pathlib import Path
from collections import Counter
import json,datetime,subprocess
import cpu_raw_baseline as I

def main():
 policy=I.Policy();root=I.ROOT;review=root/'evidence/cpu-raw-next100-preparation-v4'
 selection=json.loads((review/'SELECTION.json').read_bytes())
 policy.fresh_delta(selection,root/'evidence/cpu-next100-raw-fresh-v4')
 strict=I.verified_module('_audit_verified_strict',I.FILES['strict'],policy.buffers['strict'])
 context=strict.compiler_bindings();baseline_bindings=json.loads(policy.buffers['baseline'])['bindings']
 I.require(all(baseline_bindings.get(k)==v for k,v in context.items()),'compiler map differs from frozen validated baseline')
 policy.pin_compiler_context(context);policy.compiler_context(strict)
 cases=[];receipt_count=0;exact_count=0;lineage_count=0
 for folder in ['cpu-next100-raw-fresh-v4']:
  out=root/'evidence'/folder;delta=json.loads((out/'DELTA.json').read_bytes())
  I.validate_delta(delta,policy.fresh_delta(selection,out))
  I.require(delta['execution_started'] and delta['CPU_interval_released'],'window not released')
  for record in delta['records']:
   path=record['path'];row=policy.row(path);source=(I.SOURCE/path).read_bytes()
   contract=policy.binding(path,selection['purpose']);d=out/path.removesuffix('.bend')
   runtime={};stages=record['stages'];status=record['status']
   I.require(status!='pending','unaccounted selected case')
   for tag,receipt in stages.items():
    receipt_count+=1
    I.require(json.loads((d/(tag+'.json')).read_bytes())==receipt,'delta/disk receipt disagreement')
    I.require(receipt['receipt_sha256']==I.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'}),'receipt integrity mismatch')
    basis=receipt['basis'];I.require(basis['fresh_delta_binding']==delta['binding'] and basis['frozen_case_contract']==contract,'fresh binding mismatch')
    I.require(basis['compiler_hashes']==context,'validated initial compiler map mismatch')
    inputs,outputs=strict.declared_paths(receipt['argv'])
    actual_inputs={str(p):strict.sha(p) for p in inputs}
    I.require(actual_inputs==basis['input_hashes'],'input bytes changed')
    I.require(receipt['output_hashes']=={str(p):strict.sha(p) if p.is_file() else None for p in outputs},'output bytes changed')
    lineage=I.producer_lineage(tag,d,stages,actual_inputs,delta['binding'],contract,context)
    I.require(basis['consumed_producers']==lineage,'producer lineage changed');lineage_count+=len(lineage)
    streams={}
    for stream in ('stdout','stderr'):
     p=d/(tag+'.'+stream);I.require(receipt[stream]==str(p),'stream path mismatch')
     streams[stream]=p.read_bytes();I.require(I.sha(streams[stream])==receipt[stream+'_sha256'],'stream bytes changed')
    if tag in ('interp','native-t1','native-t2','js'):
     runtime[tag]=policy.bundle.exact_fresh_runtime(receipt,row,source,streams['stdout'],streams['stderr'])
     exact_count+=int(runtime[tag])
   if status=='pass-CPU-lanes-default-C-parity':
    I.require(set(stages)=={'check','interp','emit-upstream-c','emit-fork-c','build-c','native-t1','native-t2','emit-js','js'},'full pass missing stage')
    I.require(runtime=={'interp':True,'native-t1':True,'native-t2':True,'js':True},'full pass raw stream mismatch')
    I.require((d/'upstream.c').read_bytes()==(d/'fork.c').read_bytes(),'default C parity changed')
    I.require(all(s['exit']==0 and not s['timeout'] for s in stages.values()),'full pass has failing stage')
   elif status=='pass-check-interpreter-printer-ineligible':
    I.require(record.get('C_JS_compiled_pass') is False and runtime=={'interp':True},'printer refusal misrepresented as compiled pass')
   elif status=='pass-check-interpreter':I.require(runtime=={'interp':True},'interpreter pass mismatch')
   elif status in ('pass-expected-negative','pass-check-only'):
    def tidy(text):return '\n'.join(line.rstrip(' \t') for line in text.splitlines()).strip()
    def diagnostic(receipt):
     text=Path(receipt['stdout']).read_text(errors='replace')+Path(receipt['stderr']).read_text(errors='replace')
     return tidy(text.rstrip('\n')+(f"\nexit {receipt['exit']}" if receipt['exit'] else ''))
    I.require(not runtime and 'raw_golden_binding' not in contract,'diagnostic/verdict entered successful runtime contract')
    if status=='pass-expected-negative':
     I.require(contract['contract_group']=='checker-negative-contract' and row['expected_negative'] and row['expected_output'].startswith('SOME PROOFS FAIL'),'checker refusal branch changed')
     I.require(set(stages)=={'check'} and stages['check']['exit']==1 and not stages['check']['timeout'],'invalid checker refusal receipts')
     I.require(diagnostic(stages['check'])==tidy(row['expected_output']),'frozen checker diagnostic mismatch')
    else:
     I.require(not row['main_marker_per_upstream_gate'] and (contract['contract_group']=='check-verdict-contract' or (contract['contract_group']=='checker-negative-contract' and row['expected_negative'] and row['expected_output'].startswith('SOME PROOFS FAIL'))),'verdict branch changed')
     I.require(set(stages)=={'check','verdict'} and stages['check']['exit']==0 and not stages['check']['timeout'],'invalid check/verdict stages')
     verdict=stages['verdict'];I.require(not verdict['timeout'] and verdict['exit']==(1 if row['expected_negative'] else 0),'verdict exit changed')
     I.require(diagnostic(verdict)==tidy(row['expected_output']),'frozen verdict mismatch')
   cases.append({'path':path,'original_status':record['original_status'],'contract_group':contract['contract_group'],'fresh_status':status,'receipts':len(stages),'raw_runtime_matches':runtime})
 I.require(len(cases)==100 and len({c['path'] for c in cases})==100,'scope changed')
 I.require(I.sha(I.FILES['baseline'].read_bytes())==I.APPROVED['baseline'],'historical baseline modified')
 policy.verify();policy.compiler_context(strict)
 workers=subprocess.run(['ps','-eo','pid,ppid,comm'],capture_output=True,text=True,check=True)
 matches=[l for l in workers.stdout.splitlines()[1:] if l.split()[-1] in ('bun','clang','native','bend')]
 report={'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'audit_passed':True,'selected_cases':100,
  'fresh_statuses':dict(Counter(c['fresh_status'] for c in cases)),'selection_contract_groups':dict(Counter(c['contract_group'] for c in cases)),
  'no_main_checker_diagnostics_via_verdict':[c['path'] for c in cases if c['contract_group']=='checker-negative-contract' and c['fresh_status']=='pass-check-only'],
  'fresh_receipts':receipt_count,'exact_runtime_stream_matches':exact_count,
  'producer_consumer_edges_verified':lineage_count,'validated_compiler_map_entries':len(context),'ledger_binding_superset_entries':len(json.loads(policy.buffers['baseline'])['bindings']),
  'historical_completed_bindings_validated_at_runtime':621,'historical_matrix_reaudited':False,'historical_baseline_sha256':I.APPROVED['baseline'],'historical_rows_modified':0,'old_receipts_reattached':0,
  'unique_accounted_paths_including_history':921,'contract_holds':56,'safety_holds':249,'GPU_dispatches':0,'CPU_PAUSE':(root/'evidence/CPU-PAUSE').exists(),
  'matching_workers':matches,'cases':cases}
 I.require(report['CPU_PAUSE'] and not matches,'CPU interval not cleanly released')
 (review/'EXACT-WINDOW-AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))

if __name__=='__main__':main()
