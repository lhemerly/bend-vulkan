"""Source-only generation/freeze; no historical field or candidate execution."""
import collections,hashlib,json,pathlib,zipfile
import raw_golden_contract as G
ROOT=pathlib.Path(__file__).resolve().parents[1];SOURCE=ROOT.parent/'bend-vulkan-feasibility/source'
OUT=ROOT/'evidence/cpu-raw-golden-sidecar-v1';OUT.mkdir(exist_ok=True)
review=OUT/'bend-cpu-golden-byte-review.zip';review_sha='1e5188112a3314adb0f758d7fe66e2e608d214ac787fc399867f75b37edc3f50'
G.require(G.sha_bytes(review.read_bytes())==review_sha,'independent review changed')
with zipfile.ZipFile(review) as z:
 for name,h in json.loads(z.read('SHA256SUMS.json')).items():
  expected=h if isinstance(h,str) else h['sha256'];G.require(G.sha_bytes(z.read(name))==expected,'review member changed')
 expected_groups=json.loads(z.read('PENDING-CONTRACT-GROUPS.json'))
baseline=ROOT/'evidence/cpu-compatibility-ledger-v10/LEDGER.json';baseline_bytes=baseline.read_bytes();ledger=json.loads(baseline_bytes)
inventory=ROOT/'evidence/compatibility-roadmap-v1/INVENTORY.json';inventory_bytes=inventory.read_bytes();inventory_rows={r['path']:r for r in json.loads(inventory_bytes)['files']}
records=[];pending=collections.defaultdict(list)
for row in ledger['files']:
 G.require(inventory_rows[row['path']]['sha256']==row['sha256'] and inventory_rows[row['path']]['expected_output']==row['expected_output'],'frozen inventory field drift')
 rec=G.source_record(row,(SOURCE/row['path']).read_bytes());records.append(rec)
 if row['status']=='pending':pending[rec['contract_group']].append(row['path'])
G.require({k:set(v) for k,v in pending.items()}=={k:set(v) for k,v in expected_groups.items()},'independently reviewed810 contract groups changed')
G.require(len(records)==1680,'source count changed')
sidecar={'schema':'bend-lossless-raw-golden-sidecar-v1','pinned_commit':ledger['pinned_commit'],'policy':G.POLICY,
 'read_only_source_provenance':True,'execution_enabled':False,'safety_admission_granted':False,
 'ordinary_pending_groups':dict(pending),'records':records}
sidecar_bytes=(json.dumps(sidecar,indent=2)+'\n').encode();(OUT/'RAW-GOLDEN-SIDECAR.json').write_bytes(sidecar_bytes)
freeze={'schema':'bend-raw-golden-freeze-v1','sidecar_sha256':G.sha_bytes(sidecar_bytes),'parser_policy_sha256':G.sha_bytes((ROOT/'tools/raw_golden_contract.py').read_bytes()),
 'builder_sha256':G.sha_bytes(pathlib.Path(__file__).read_bytes()),'inventory_sha256':G.sha_bytes(inventory_bytes),'baseline_ledger_sha256':G.sha_bytes(baseline_bytes),
 'review_archive_sha256':review_sha,'source_count':1680,'ordinary_pending_group_counts':{k:len(v) for k,v in pending.items()},
 'source_executions':0,'status_changes':0,'review_only':True,'execution_enabled':False}
G.require(baseline.read_bytes()==baseline_bytes and inventory.read_bytes()==inventory_bytes,'historical artifact changed while freezing')
(OUT/'SIDECAR-FREEZE.json').write_text(json.dumps(freeze,indent=2)+'\n')
print(json.dumps(freeze,indent=2))
