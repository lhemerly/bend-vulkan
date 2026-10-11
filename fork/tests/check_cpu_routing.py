"""Actual generated native CPU routing and independent upstream/default matrix."""
from pathlib import Path
import subprocess,json,hashlib,os,sys
r=Path(__file__).resolve().parents[2];up=r.parent/'bend-vulkan-feasibility/source/tests/run'
d=r/'evidence'/(sys.argv[1] if len(sys.argv)>1 else 'fork-cpu-routing-first');d.mkdir(exist_ok=False)
source=(up/'gpu_mark.bend').read_text();prefix=source.split('law main.out:')[0]
def body(text,extra=''):
 return prefix+extra+'\nlaw main.out:\n  U32\n\ndef main.out():\n'+text+'\nlaw main:\n  IO(Unit)\n\ndef main():\n  IO.print(U32.show(main.out()))\n'
cases={
 'gpu_mark':(source,True,1,b'1212\n'),
 'renamed_reordered':('import Base\n\ndef irrelevant(v: U32) -> U32:\n  v\n'+source.replace('import Base\n','').replace('gmark','renamed_rec'),True,1,b'1212\n'),
 'ordinary_depth6':(source.replace('y = gmark(2n)','y = gmark(6n)'),True,1,b'1392\n'),
 'explicit_depth6':(source.replace('x = gmark!(2n)','x = gmark!(6n)'),False,0,b'19212\n'),
 'before_same_interval':(source.replace('x = gmark!(2n)','x = gmark(2n)').replace('y = gmark(2n)','y = gmark!(2n)'),False,0,b'1212\n'),
 'between_bangs':(body('  x = gmark!(2n)\n  y = gmark(2n)\n  z = gmark!(1n)\n  U32.add(U32.add(x, y), z)\n'),False,1,b'30\n'),
 'marked_parallel':(body('  x y = gmark!(2n) gmark(2n)\n  U32.add(U32.mul(x, 100), y)\n'),False,0,b'1212\n'),
 'hidden_later_gateway':(body('  x = gmark(2n)\n  y = later(2n)\n  U32.add(x, y)\n','def later(d: Nat) -> U32:\n  gmark!(d)\n'),False,0,b'24\n'),
 'recursive_effect':(body('  x y = gmark(2n) effect_rec(2n)\n  U32.add(x, y)\n','def effect_rec(d: Nat) -> U32:\n  match d:\n    case 0n:\n      gmark!(0n)\n    case 1n+p:\n      effect_rec(p)\n'),False,0,b'15\n'),
 'across_io':(prefix+'def main() -> IO(Unit):\n  do IO<Unit>:\n    first: U32 = gmark(2n)\n    Unit <- IO.print(U32.show(first))\n    second: U32 = gmark!(2n)\n    IO.print(U32.show(second))\n',True,1,b'12\n12\n'),
 'unknown_closure':(body('  initial = gmark!(0n)\n  a b = gmark(2n) apply_clo(build_clo(2n), 2n)\n  U32.add(initial, U32.add(a, b))\n','def apply_clo(f: Nat -> U32, d: Nat) -> U32:\n  f(d)\n\ndef build_clo(d: Nat) -> Nat -> U32:\n  match d:\n    case 0n:\n      z => gmark(z)\n    case 1n+p:\n      z => U32.add(gmark(z), U32.from_nat(p))\n'),False,1,b'28\n'),
 'two_io_handoffs':(prefix+'def main() -> IO(Unit):\n  do IO<Unit>:\n    first: U32 = gmark!(2n)\n    Unit <- IO.print(U32.show(first))\n    second: U32 = gmark!(1n)\n    IO.print(U32.show(second))\n',True,2,b'12\n6\n'),
 'captured_join':(body('  x = gmark!(2n)\n  wrap(2n, x)\n','def wrap(+d: Nat, z: U32) -> U32:\n  a b = gmark(d) gmark(d)\n  U32.add(z, U32.add(a, b))\n'),True,1,b'36\n'),
}
second=prefix.replace('gmark','other_rec').replace('      3\n','      5\n').replace('import Base\n','')
io_body='def main() -> IO(Unit):\n  do IO<Unit>:\n    first: U32 = other_rec!(1n)\n    Unit <- IO.print(U32.show(first))\n    second: U32 = gmark!(2n)\n    IO.print(U32.show(second))\n'
cases['root_order_a']=(prefix+second+io_body,True,2,b'10\n12\n')
reverse_body=io_body.replace('other_rec!(1n)','TEMP_CALL').replace('gmark!(2n)','other_rec!(1n)').replace('TEMP_CALL','gmark!(2n)')
cases['root_order_b']=(('import Base\n'+second+prefix.replace('import Base\n','')+reverse_body).replace('gmark','renamed_root'),True,2,b'12\n10\n')
helpers=''.join(prefix.replace('gmark',f'ordinary_{i}').replace('import Base\n','') for i in range(65))
sparse_body='  x = gmark!(2n)\n  acc0 = x\n'+''.join(f'  acc{i+1} = U32.add(acc{i}, ordinary_{i}(0n))\n' for i in range(65))+'  acc65\n'
cases['sparse_root_FID']=(body(sparse_body,helpers),True,1,b'207\n')
if len(sys.argv)>2:cases={k:v for k,v in cases.items() if k.startswith(sys.argv[2])}
env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')};rows=[]
def run(cmd,folder,tag,extra=None):
 p=subprocess.run(list(map(str,cmd)),capture_output=True,env={**env,**(extra or {})},timeout=30)
 (folder/(tag+'.stdout')).write_bytes(p.stdout);(folder/(tag+'.stderr')).write_bytes(p.stderr)
 (folder/(tag+'.json')).write_text(json.dumps({'argv':list(map(str,cmd)),'exit':p.returncode,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()},indent=2)+'\n')
 return p
for name,(text,accept,count,expected) in cases.items():
 folder=d/name;folder.mkdir();src=folder/(name+'.bend');src.write_text(text)
 p=run(['bun',r/'fork/routing_cli.ts',src,folder/'generated'],folder,'emit');assert p.returncode==0,(name,p.stderr)
 p=run(['bun',r/'tools/compile_example.ts',src,folder/'upstream.c'],folder,'upstream-emit');assert p.returncode==0,(name,p.stderr)
 assert (folder/'generated/default.c').read_bytes()==(folder/'upstream.c').read_bytes(),name
 for typ,c in [('upstream',folder/'upstream.c'),('program',folder/'generated/program.c')]:
  p=run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',c,'-lpthread','-lm','-o',folder/typ],folder,'build-'+typ);assert p.returncode==0,(name,p.stderr)
 results=[]
 for threads in [1,2]:
  args=['--gpu','off','--threads',str(threads)]
  base=run([folder/'upstream',*args],folder,f'baseline-t{threads}');assert (base.returncode,base.stdout,base.stderr)==(0,expected,b''),(name,base.stdout,base.stderr)
  plain=run([folder/'program',*args],folder,f'absent-t{threads}')
  assert (base.returncode,base.stdout,base.stderr)==(plain.returncode,plain.stdout,plain.stderr),(name,plain.stderr)
  selected=run([folder/'program',*args],folder,f'selected-t{threads}',{'BEND_FORK_TRANSPORT':'cpu-reference','BEND_FORK_TRACE':'1'})
  handoffs=selected.stderr.count(b'routing CPU-reference handoff')
  assert handoffs==count,(name,selected.stderr)
  if accept:
   assert selected.returncode==0 and selected.stdout==base.stdout,(name,selected.stderr)
   quiet=run([folder/'program',*args],folder,f'selected-quiet-t{threads}',{'BEND_FORK_TRANSPORT':'cpu-reference'})
   assert (quiet.returncode,quiet.stdout,quiet.stderr)==(base.returncode,base.stdout,base.stderr),(name,quiet.stderr)
   if name in ['gpu_mark','ordinary_depth6','renamed_reordered']:assert b'routing CPU pending' in selected.stderr
  else:
   assert selected.returncode!=0 and b'routing:' in selected.stderr,(name,selected.stdout,selected.stderr)
  results.append({'threads':threads,'selected_exit':selected.returncode,'handoffs':handoffs,'CPU_pending_trace':b'routing CPU pending' in selected.stderr})
 rows.append({'case':name,'default_C_byte_equal':True,'transport_absent_raw_parity':True,'selected_expected_accept':accept,'runs':results})
 if name=='sparse_root_FID':
  p=json.loads((folder/'generated/routing-plan.json').read_text());assert p['gateways'][0]['root_id']>63,p['gateways']
  rows[-1]['verified_root_FID_above63']=p['gateways'][0]['root_id']
 print(name,'PASS',flush=True)
(d/'RESULT.json').write_text(json.dumps({'scope':'CPU routing prototype with upstream semantic reference handoff, no Nat device lowering','gpu_dispatches':0,'cases':rows},indent=2)+'\n')
