"""Read-only bounded manifest inspection; JSONL output, never aggregate export."""
import argparse,hashlib,json,types
from pathlib import Path

def load(path,reader_sha256):
 source=Path(__file__).with_name('cpu_delta_store.py');raw=source.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=reader_sha256:raise ValueError('reviewed reader hash mismatch')
 module=types.ModuleType('_reviewed_delta_reader');module.__file__=str(source)
 exec(compile(raw,str(source),'exec'),module.__dict__)
 return module.Store(Path(path).parent).load()
def main():
 a=argparse.ArgumentParser();a.add_argument('manifest');a.add_argument('--reader-sha256',required=True);args=a.parse_args()
 delta=load(args.manifest,args.reader_sha256)
 print(json.dumps({'type':'header','value':{k:v for k,v in delta.items() if k!='records'}},separators=(',',':')))
 for record in delta['records']:print(json.dumps({'type':'case','value':record},separators=(',',':')))
if __name__=='__main__':main()
