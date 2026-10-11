"""Bounded immutable case snapshots; atomic small manifest. No legacy migration."""
import hashlib,json,os,re,stat,tempfile
from pathlib import Path
SCHEMA='bend-cpu-case-manifest-v1'
CHUNK=262144
CASE_LIMIT=2097152
MANIFEST_LIMIT=262144
MAX_CASES=100

def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()+b'\n'
def sha(data):return hashlib.sha256(data).hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)

def read(path,limit):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'invalid bounded regular file')
  with os.fdopen(fd,'rb',closefd=False) as f:data=f.read(limit+1)
  require(len(data)<=limit,'file exceeds bound');return data
 finally:os.close(fd)

class Store:
 def __init__(self,out):
  self.out=Path(out);self.manifest=self.out/'DELTA.json';self.refs=None
  require(self.out.is_dir() and not self.out.is_symlink(),'invalid output directory')
 def _blob(self,data):
  name='case-'+sha(data)+'.jsonpart';path=self.out/name
  fd,temporary=tempfile.mkstemp(prefix='.chunk-',dir=self.out)
  try:
   with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
   # Hard stop leaves only an unpublished temporary file. link() publishes
   # complete bytes atomically and never replaces an immutable destination.
   try:os.link(temporary,path,follow_symlinks=False)
   except FileExistsError:require(read(path,CHUNK)==data,'immutable chunk changed')
  finally:
   if os.path.exists(temporary):os.unlink(temporary)
  return name
 def _atomic(self,data):
  require(len(data)<=MANIFEST_LIMIT,'manifest exceeds bound')
  fd,name=tempfile.mkstemp(prefix='.manifest-',dir=self.out)
  try:
   with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
   os.replace(name,self.manifest)
   directory=os.open(self.out,os.O_RDONLY|os.O_DIRECTORY)
   try:os.fsync(directory)
   finally:os.close(directory)
  finally:
   if os.path.exists(name):os.unlink(name)
 def load(self):
  value=json.loads(read(self.manifest,MANIFEST_LIMIT))
  require(value.get('schema')==SCHEMA,'legacy delta requires fresh output; never overwrite')
  require(set(value)=={'schema','header','cases','sha256'},'unexpected manifest fields')
  checksum=value.pop('sha256');require(sha(encode(value))==checksum,'manifest checksum mismatch')
  refs=value['cases'];require(isinstance(refs,list) and len(refs)<=MAX_CASES,'invalid case count')
  require(isinstance(value['header'],dict) and 'records' not in value['header'],'invalid header')
  records=[]
  for ref in refs:
   require(set(ref)=={'path','bytes','sha256','chunks'},'invalid case descriptor')
   require(type(ref['bytes']) is int and 0<ref['bytes']<=CASE_LIMIT,'invalid case size')
   require(isinstance(ref['chunks'],list) and len(ref['chunks'])==(ref['bytes']+CHUNK-1)//CHUNK,'invalid chunk count')
   parts=[]
   for index,name in enumerate(ref['chunks']):
    require(isinstance(name,str) and re.fullmatch(r'case-[0-9a-f]{64}\.jsonpart',name),'invalid chunk name')
    data=read(self.out/name,CHUNK);require(sha(data)==name[5:-9],'chunk hash mismatch')
    require(len(data)==min(CHUNK,ref['bytes']-index*CHUNK),'chunk size mismatch');parts.append(data)
   data=b''.join(parts);require(sha(data)==ref['sha256'],'case hash mismatch')
   record=json.loads(data);require(record['path']==ref['path'],'case path mismatch');records.append(record)
  require(len({r['path'] for r in records})==len(records),'duplicate paths')
  self.refs=refs;return dict(value['header'],records=records)
 def save(self,delta):
  records=delta['records'];require(len(records)<=MAX_CASES,'too many cases')
  # Check existing committed state before any overwrite, including first save.
  if self.manifest.exists():self.load()
  refs=[]
  for record in records:
   data=encode(record);require(len(data)<=CASE_LIMIT,'case exceeds existing file cap')
   chunks=[self._blob(data[n:n+CHUNK]) for n in range(0,len(data),CHUNK)]
   refs.append({'path':record['path'],'bytes':len(data),'sha256':sha(data),'chunks':chunks})
  require(len({r['path'] for r in refs})==len(refs),'duplicate paths')
  value={'schema':SCHEMA,'header':{k:v for k,v in delta.items() if k!='records'},'cases':refs}
  value['sha256']=sha(encode(value));self._atomic(encode(value));self.refs=refs
