"""Validate terminal rows before any resume skip, including inherited receipts."""
from pathlib import Path
import hashlib,json,zipfile
from strict_cpu_receipts import StaleReceipt,sha,digest,binding_sha

_archives={}
def verify_legacy_files(row,files,source_root,project_root):
 proof=row.get('legacy_archive')
 if not proof:return
 archive=Path(proof['path']);expected=proof['sha256']
 if not archive.is_file() or binding_sha(archive)!=expected:raise StaleReceipt('frozen legacy archive changed')
 key=(str(archive.resolve()),expected)
 if key not in _archives:_archives[key]=(zipfile.ZipFile(archive),{})
 z,hashes=_archives[key]
 for name,actual in files.items():
  p=Path(name)
  if p.is_relative_to(source_root):member='upstream-examples/'+str(p.relative_to(source_root))
  else:member=str(p.relative_to(project_root))
  if member not in hashes:
   try:hashes[member]=hashlib.sha256(z.read(member)).hexdigest()
   except KeyError:hashes[member]=None
  if hashes[member]!=actual:raise StaleReceipt(f'{row["path"]}: inherited artifact differs from frozen archive: {member}')

def terminal(row):
 return row['status'] not in ['pending','pending-safety-review','pending-runtime-negative-review']

def stage_records(row):
 records=list(row.get('stages',{}).values())
 if row.get('diagnostic_remediation'):records.append(row['diagnostic_remediation']['stage'])
 return records

def snapshot_files(row,source_root,project_root):
 files={};roots=[Path(source_root).resolve(),Path(project_root).resolve()]
 for s in stage_records(row):
  for k in ['stdout','stderr']:
   p=Path(s[k]);expected=s[k+'_sha256']
   if not p.is_file() or sha(p)!=expected:raise StaleReceipt(f'{row["path"]}: archived {k} changed')
   files[str(p.resolve())]=expected
  meta=Path(s['stdout']).with_suffix('.json')
  if not meta.is_file() or json.loads(meta.read_text())!=s:raise StaleReceipt(f'{row["path"]}: archived stage metadata changed')
  files[str(meta.resolve())]=sha(meta)
  for arg in s['argv']:
   p=Path(arg)
   if not p.is_absolute():continue
   resolved=p.resolve()
   if any(resolved.is_relative_to(root) for root in roots) and (p.is_file() or p.suffix in ['.c','.js','.ts','.bend'] or p.name=='native'):
    files[str(resolved)]=sha(p) if p.is_file() else None
 return files

def row_digest(row):return digest({k:v for k,v in row.items() if k!='completed_binding'})

def bind_completed(row,source_root,project_root,context):
 if not terminal(row):return
 source=Path(source_root)/row['path']
 if not source.is_file() or sha(source)!=row['sha256']:raise StaleReceipt(f'{row["path"]}: source changed')
 files=snapshot_files(row,source_root,project_root)
 verify_legacy_files(row,files,Path(source_root).resolve(),Path(project_root).resolve())
 row['completed_binding']={'schema':'bend-completed-row-v1','source_sha256':row['sha256'],'context_sha256':digest(context),'files':files,'row_sha256':row_digest(row)}

def validate_completed(row,source_root,context):
 if not terminal(row):return
 b=row.get('completed_binding')
 if not b:raise StaleReceipt(f'{row["path"]}: missing completed-row binding; use fresh ledger')
 if b['context_sha256']!=digest(context):raise StaleReceipt(f'{row["path"]}: compiler/effect context changed')
 source=Path(source_root)/row['path']
 if not source.is_file() or sha(source)!=b['source_sha256'] or row['sha256']!=b['source_sha256']:raise StaleReceipt(f'{row["path"]}: source changed')
 if b['row_sha256']!=row_digest(row):raise StaleReceipt(f'{row["path"]}: completed row metadata changed')
 for name,expected in b['files'].items():
  p=Path(name)
  if (expected is None and p.exists()) or (expected is not None and (not p.is_file() or sha(p)!=expected)):raise StaleReceipt(f'{row["path"]}: completed evidence changed: {p.name}')

def validate_resume(ledger,source_root,context):
 """All terminal rows, not just selected rows; runs before pause or skip."""
 for row in ledger['files']:validate_completed(row,source_root,context)
