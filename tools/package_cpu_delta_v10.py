"""Archive a bounded new receipt batch without recompressing prior history."""
import hashlib, io, json, pathlib, tarfile, zipfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/cpu-compatibility-ledger-v10'
ZIP=ROOT/'library-compact/bend-cpu-compatibility-checkpoint.zip'
source=ROOT.parent/'bend-vulkan-feasibility/source'
rows=json.loads((OUT/'LEDGER.json').read_text())['batch_selection']
files={str(p.relative_to(ROOT)):p for p in OUT.rglob('*') if p.is_file() and p.name!='LIBRARY-PACKAGE.json'}
for rel in ['evidence/cpu-strict-next100-v10-selection.json','evidence/BASELINE-CPU-RELEASE.json','evidence/BASELINE-MILESTONES.json','tools/audit_cpu_batch_v10.py','tools/package_cpu_delta_v10.py']:
 files[rel]=ROOT/rel
for rel in rows:files['upstream-examples/'+rel]=source/rel
delta=OUT/'RAW-v10.tar.xz'
manifest={}
with tarfile.open(delta,'w|xz',preset=1) as tar:
 for name,p in sorted(files.items()):
  data=p.read_bytes();manifest[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
  info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o600;info.mtime=0;tar.addfile(info,io.BytesIO(data))
tmp=ZIP.with_suffix('.next.zip')
with zipfile.ZipFile(ZIP) as old,zipfile.ZipFile(tmp,'w',zipfile.ZIP_STORED) as new:
 previous=json.loads(old.read('RAW-FILE-HASHES.json'))['raw_files']
 for info in old.infolist():
  if info.filename=='README.md':continue
  new.writestr(info,old.read(info.filename))
 new.write(delta,'raw-evidence-v10.tar.xz')
 new.writestr('RAW-FILE-HASHES-v10.json',json.dumps({'raw_archive':'raw-evidence-v10.tar.xz','raw_files':manifest},indent=2)+'\n')
 merged={**previous,**manifest}
 new.writestr('LATEST-RAW-FILE-HASHES.json',json.dumps({'raw_files':merged,'extraction_order':['raw-evidence.tar.xz','raw-evidence-v10.tar.xz'],'note':'v10 overrides only shared dashboard/release files; earlier ledgers and receipts remain immutable in the base archive.'},indent=2)+'\n')
 supplement=ROOT/'library-compact/bend-cpu-safety-source-supplement.zip'
 new.write(supplement,supplement.name)
 new.writestr('SOURCE-SUPPLEMENT-LIBRARY.json',(ROOT/'evidence/cpu-safety-source-supplement-v1/LIBRARY.json').read_bytes())
 new.writestr('README.md','''# Latest CPU checkpoint:621 accounted, one exact-stream failure retained

Extract raw-evidence.tar.xz, then raw-evidence-v10.tar.xz into the SAME folder. The delta adds all current100-case raw receipts, the621-row immutable ledger, original selected sources and current release/dashboard. Prior histories are retained unchanged. RAW-FILE-HASHES.json describes the base; RAW-FILE-HASHES-v10.json describes the delta; LATEST-RAW-FILE-HASHES.json describes the resulting tree. Verify hashes after extraction. Resume from evidence/cpu-compatibility-ledger-v10/LEDGER.json only.

Read evidence/cpu-compatibility-ledger-v10/CHECKPOINT.md and RESULT.json.100 cases attempted:52 runtime/C-parity passes,40 expected checker refusals, one positive no-main verdict, six printer-ineligible C/JS NOT passed, one failure-interpreter.536 fresh receipts; no timeout or GPU. Prior521 rows unchanged; actual strict paused-resume validated621 bindings. Cumulative312 full runtime/C-parity,1248 exact runtime stream checks.810 pending and249 risk records remain. CPU interval released, CPU_PAUSE present.

word_match_cover_key's raw original golden contains a trailing space that the frozen inventory stripped. Its stdout matches the raw source golden; strict contract rejects the frozen expectation. Failure retained, C/JS unexecuted; no numerical defect asserted and no harness/policy modified.

source-triage/ preserves the earlier249-record source-only triage. bend-cpu-safety-source-supplement.zip now supplies all30 exact candidate bodies, pinned prelude/import/foreign closure, Apache-2.0 license and Git-verified provenance. Its separate private Library identity is recorded in SOURCE-SUPPLEMENT-LIBRARY.json. Candidates remain UNADMITTED and UNEXECUTED pending independent review. No safety record was selected in this batch.
''')
tmp.replace(ZIP)
with zipfile.ZipFile(ZIP) as z:assert z.testzip() is None
meta={'path':str(ZIP),'bytes':ZIP.stat().st_size,'sha256':hashlib.sha256(ZIP.read_bytes()).hexdigest(),'raw_files':len(merged),'base_raw_files':len(previous),'new_delta_files':len(manifest),'unique_accounted_cases':621,'fresh_step_receipts':536,'preserved_failures':1,'source_review_supplement_included':True}
(OUT/'LIBRARY-PACKAGE.json').write_text(json.dumps(meta,indent=2)+'\n')
delta.unlink()
print(json.dumps(meta,indent=2))
