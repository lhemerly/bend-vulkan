"""Ordinary CPU-only one-example acceptance; no device or continuation grant."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
source=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve()
if out.exists():raise SystemExit('output must be new')
os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
def run(name,argv,env=None):
 r=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,timeout=15)
 (out/(name+'.stdout')).write_bytes(r.stdout);(out/(name+'.stderr')).write_bytes(r.stderr)
 row=dict(name=name,argv=argv,exit=r.returncode,stdout=r.stdout.decode(),stderr=r.stderr.decode());rows.append(row)
 if r.returncode:raise RuntimeError('failed '+name)
 return r
# Source generation owns creation of the fresh directory.
r=subprocess.run(['bun',str(ROOT/'fork/f32_routing_cli.ts'),str(source),str(out)],cwd=ROOT,capture_output=True,timeout=15)
if r.returncode:raise SystemExit(r.stderr.decode())
rows=[]
try:
 run('upstream-source',['bun',str(ROOT/'fork/upstream_compile.ts'),str(source),str(out/'upstream.c')])
 assert (out/'upstream.c').read_bytes()==(out/'default.c').read_bytes(),'ordinary compiler byte parity'
 for lane in ('upstream','program'):run('build-'+lane,['clang','-std=c11','-O1','-ffp-contract=off',str(out/(lane+'.c')),'-lpthread','-lm','-o',str(out/lane)])
 expected=''.join(line[2:]+'\n' for line in source.read_text().splitlines() if line.startswith('#|'))
 for threads in (1,2):
  for lane in ('upstream','program'):
   env=dict(os.environ);env.pop('BEND_FORK_TRANSPORT',None);env.pop('BEND_FORK_TRACE',None)
   if lane=='program':env['BEND_FORK_TRANSPORT']='cpu-reference';env['BEND_FORK_TRACE']='1'
   r=run(lane+'-t'+str(threads),[str(out/lane),'--gpu','off','--threads',str(threads)],env)
   assert r.stdout.decode()==expected,'unchanged example output mismatch'
   if lane=='program':assert b'CPU-reference handoff' in r.stderr,'missing real host bridge'
 result=dict(passed=True,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),default_C_byte_parity=True,expected=expected,GPU_dispatches=0,hardware_acceptance=False,rows=rows)
except Exception as e:
 result=dict(passed=False,error=str(e),rows=rows);raise
finally:
 (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed':True,'output':str(out),'expected':expected,'GPU':False}))
