"""Read and audit completed receipts; never execute Bend or a candidate binary."""
import collections, datetime, hashlib, json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from strict_cpu_receipts import digest, runtime_exact
OUT=ROOT/'evidence/cpu-compatibility-ledger-v10'
ledger=json.loads((OUT/'LEDGER.json').read_text())
seed=json.loads((ROOT/'evidence/cpu-compatibility-ledger-v9/LEDGER.json').read_text())
old={r['path']:r for r in seed['files']}
selected=set(ledger['batch_selection'])
rows=[r for r in ledger['files'] if r['path'] in selected]
assert len(rows)==100 and all(not r['risk'] for r in rows)
assert all(r['status'] not in ('pending','pending-safety-review') for r in rows)
inherited=[r for r in ledger['files'] if old[r['path']]['status'].startswith('pass-')]
assert len(inherited)==521
assert all(r==old[r['path']] for r in inherited)
receipts=[]
failures=[]
timeouts=[]
exact=0
for r in rows:
 if not r['status'].startswith('pass-'):failures.append({'path':r['path'],'status':r['status']})
 for tag,s in r['stages'].items():
  assert s['schema']=='bend-cpu-receipt-v2'
  assert s['receipt_sha256']==digest({k:v for k,v in s.items() if k!='receipt_sha256'})
  assert pathlib.Path(s['stdout']).is_relative_to(OUT)
  for stream in ('stdout','stderr'):
   assert hashlib.sha256(pathlib.Path(s[stream]).read_bytes()).hexdigest()==s[stream+'_sha256']
  assert json.loads(pathlib.Path(s['stdout']).with_suffix('.json').read_text())==s
  for p,h in s['output_hashes'].items():assert (hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() if pathlib.Path(p).is_file() else None)==h
  receipts.append({'path':r['path'],'tag':tag,'receipt_sha256':s['receipt_sha256'],'exit':s['exit'],'timeout':s['timeout']})
  if s['timeout']:timeouts.append({'path':r['path'],'tag':tag})
 if r['status']=='pass-CPU-lanes-default-C-parity':
  for tag in ('interp','native_t1','native_t2','js'):
   assert runtime_exact(r['stages'][tag],r['expected_output']);exact+=1
full=sum(r['status']=='pass-CPU-lanes-default-C-parity' for r in ledger['files'])
new=collections.Counter(r['status'] for r in rows)
result={'status':'COMPLETE-with-recorded-failures' if failures else 'PASS-required-obligations',
 'new_cases_attempted':100,'inherited_pass_rows_preserved_byte_for_byte':521,
 'unique_accounted_cases':521+len(rows),'new_classifications':dict(new),
 'fresh_step_receipts':len(receipts),'failures':failures,'timeouts':timeouts,'GPU_dispatches':0,
 'cumulative_full_runtime_C_parity':full,'cumulative_exact_runtime_stream_checks':full*4,
 'new_exact_runtime_stream_checks':exact,'remaining_counts':ledger['summary']['statuses'],
 'raw_ledger_sha256':hashlib.sha256((OUT/'LEDGER.json').read_bytes()).hexdigest(),
 'CPU_interval_released':True,'fresh_receipts':receipts}
(OUT/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
(OUT/'EXACT-STREAM-AUDIT.json').write_text(json.dumps({'fresh_receipt_integrity_checked':len(receipts),'inherited_rows_unchanged':521,'new_successful_runtime_stream_checks':exact,'cumulative_successful_runtime_stream_checks':full*4,'failures_preserved':failures,'normalization_of_runtime_streams':False},indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='fresh_receipts'},indent=2))
