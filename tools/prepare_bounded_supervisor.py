"""Source-only rebind after fresh runner preparation; never execute/authorize."""
import argparse,hashlib,os,types
from pathlib import Path

def prepare(template,manifest,dest,template_sha256):
 template=Path(template);manifest=Path(manifest);dest=Path(dest)
 raw=template.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=template_sha256:raise ValueError('reviewed template changed')
 module=types.ModuleType('_reviewed_supervisor_template');module.__file__=str(template)
 exec(compile(raw,str(template),'exec'),module.__dict__)
 if module.DELTA_SHA!='UNPREPARED':raise ValueError('requires unprepared reviewed template')
 if manifest!=module.E/module.OUTPUT_NAME/'DELTA.json':raise ValueError('wrong fresh output')
 runner=module.ROOT/'tools/cpu_raw_baseline.py';selection=module.E/'cpu-v5-remaining87-preparation-v1/SELECTION.json'
 module.verify_inputs(((runner,module.RUNNER_SHA),(selection,module.SELECTION_SHA)))
 module.read_prepared_delta(manifest,runner)
 # Input is source selected locally for review, not an authorization file.
 source=raw.decode();source=source.replace("DELTA_SHA = 'UNPREPARED'", "DELTA_SHA = '"+module.sha(manifest)+"'")
 if dest.parent.resolve()!=template.parent.resolve():raise ValueError('supervisor must retain project root')
 fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:f.write(source);f.flush();os.fsync(f.fileno())
 return {'supervisor_sha256':module.sha(dest),'delta_sha256':module.sha(manifest),'execution_authorized':False}
def main():
 import json
 a=argparse.ArgumentParser();a.add_argument('--template',required=True);a.add_argument('--template-sha256',required=True);a.add_argument('--manifest',required=True);a.add_argument('--output',required=True);args=a.parse_args()
 print(json.dumps(prepare(args.template,args.manifest,args.output,args.template_sha256),indent=2))
if __name__=='__main__':main()
