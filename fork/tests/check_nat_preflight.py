"""Preflight-only worker safety and independent negative-source CPU provenance."""
from pathlib import Path
import json,os,struct,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'fork/runtime'))
from nat_arena import CANARIES
from nat_oracle import evaluate


def main(destination):
    out=ROOT/'evidence'/destination;out.mkdir(exist_ok=False)
    target=ROOT/'evidence/nat-corrected-cpu-v2/gpu_mark'
    prepared=target/'native-preflight';worker=prepared/'worker'
    config=json.loads((prepared/'preparation.json').read_text())
    assert config['admitted'] is False and config['host_gpu_bridge_implemented'] is False
    rows=[]
    def run(argv,d,tag,extra=None):
        env={k:v for k,v in os.environ.items() if not k.startswith('BEND_FORK_')}
        p=subprocess.run(list(map(str,argv)),capture_output=True,timeout=30,env={**env,**(extra or {})})
        (d/(tag+'.stdout')).write_bytes(p.stdout);(d/(tag+'.stderr')).write_bytes(p.stderr)
        (d/(tag+'.json')).write_text(json.dumps({'argv':list(map(str,argv)),'exit':p.returncode},indent=2)+'\n')
        return p
    for name,args,success in [('guard',['--guard-selftest'],True),('parent-bound',['--parent-selftest',os.getpid()],True),('wrong-parent',['--parent-selftest',os.getpid()+1],False),('inventory-veto',['--probe-inventory'],False)]:
        p=run([worker,*args],out,name);assert (p.returncode==0)==success
        rows.append({'case':name,'exit':p.returncode,'GPU_dispatches':0})
    roots=config['roots'];base=[0]*772;base[:6]=[1,roots[0],2,63,31,192];base[-4:]=CANARIES
    probes={'valid-but-blocked':({},'Nat GPU admission disabled'), 'input-depth6':({2:6},'Nat root/input/policy mismatch'),
      'unknown-root':({1:65535},'Nat root/input/policy mismatch'),'task-cap64':({3:64},'Nat root/input/policy mismatch'),
      'join-cap32':({4:32},'Nat root/input/policy mismatch'),'steps193':({5:193},'Nat root/input/policy mismatch'),
      'stale-DONE':({11:1},'Nat initial controls/canaries mismatch'),'reserved':({14:1},'Nat initial controls/canaries mismatch'),
      'stale-task':({16:1},'Nat initial controls/canaries mismatch'),'canary':({768:0},'Nat initial controls/canaries mismatch')}
    for name,(writes,reason) in probes.items():
        words=base.copy()
        for i,value in writes.items():words[i]=value
        inp=out/(name+'.bin');inp.write_bytes(struct.pack('<772I',*words));output=out/(name+'-output.bin')
        args=[worker,target/'nat.spv',inp,output,772,1,0,0,0,0,0,'/sys/devices/not-selected',os.getpid()]
        p=run(args,out,name,{'BEND_FORK_TRANSPORT':'vulkan','BEND_FORK_ADMITTED':'1'})
        assert p.returncode==2 and reason.encode() in p.stderr and not output.exists(),(name,p.stderr)
        rows.append({'case':name,'exit':p.returncode,'no_output':True,'reason':reason,'GPU_dispatches':0})
    inp=out/'valid-but-blocked.bin';swap=out/'swapped.spv';swap.write_bytes(b'not the bound module')
    p=run([worker,swap,inp,out/'swapped-output.bin',772,1,0,0,0,0,0,'/sys/devices/not-selected',os.getpid()],out,'module-swap')
    assert p.returncode==2 and b'immutable module mismatch' in p.stderr
    rows.append({'case':'module-swap','exit':2,'GPU_dispatches':0})
    for value in (6,2**32+2,(1<<48)-1,1<<48,True):
        plan=json.loads((target/'generated/nat-plan.json').read_text())
        try:
            evaluate(plan,roots[0],value);raise AssertionError('out-of-subset value accepted')
        except ValueError:pass
    native=[]
    for name in ('changed_argument','constant_argument'):
        d=out/name;d.mkdir();src=ROOT/'fork/tests/nat_origin'/(name+'.bend')
        p=run(['bun',ROOT/'fork/tests/plan_cpu_compile.ts',src,d],d,'emit');assert p.returncode==0,p.stderr
        assert (d/'upstream.c').read_bytes()==(d/'default.c').read_bytes()
        for compiler in ('upstream','default'):
            p=run(['clang','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',d/(compiler+'.c'),'-lpthread','-lm','-o',d/compiler],d,'build-'+compiler)
            assert p.returncode==0,p.stderr
        for threads in (1,2):
            base=run([d/'upstream','--gpu','off','--threads',threads],d,f'upstream-t{threads}')
            fork=run([d/'default','--gpu','off','--threads',threads],d,f'default-t{threads}')
            assert (base.returncode,base.stdout,base.stderr)==(fork.returncode,fork.stdout,fork.stderr)==(0,b'6\n',b'')
            native.append({'case':name,'threads':threads,'whole_program_stdout':'6\n','default_byte_and_raw_parity':True})
    report={'scope':'preflight wrapper has unconditional native dispatch rejection; independent CPU provenance for sources rejected by Nat capture','GPU_dispatches':0,'preflight':rows,'full_integer_rejections':5,'native_negative_source_provenance':native}
    (out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main(sys.argv[1])
