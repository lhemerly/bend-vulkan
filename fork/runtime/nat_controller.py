"""Exact Nat receipt controller. Production config/worker are non-admitted.

No environment-selected CPU fallback. The keyword-only test backend below is
an explicit in-process CPU test seam and is never supplied by the CLI.
"""
from pathlib import Path
import math,ctypes,fcntl,hashlib,json,os,signal,struct,subprocess,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
from nat_oracle import validate,evaluate,integer,LIMITS
from nat_arena import simulate,CANARIES

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def bind_parent(expected):
    if not integer(expected,1,(1<<31)-1) or os.getppid()!=expected:raise RuntimeError('original controller parent mismatch/adoption')
    if ctypes.CDLL(None,use_errno=True).prctl(1,signal.SIGKILL,0,0,0) or os.getppid()!=expected:raise RuntimeError('controller parent race')

def validate_budget(budget, now):
    if not isinstance(budget,dict) or set(budget)!={'deadline_monotonic','reserved_calls','max_calls'}:
        raise RuntimeError('invalid Nat budget fields')
    deadline=budget['deadline_monotonic']
    if type(deadline) not in (int,float) or not math.isfinite(deadline) or not 0<deadline<=2**53:
        raise RuntimeError('invalid finite Nat deadline')
    if not integer(budget['max_calls'],1,4096) or not integer(budget['reserved_calls'],0,budget['max_calls']):
        raise RuntimeError('invalid bounded Nat call budget')
    if deadline<=now or deadline-now>660 or budget['reserved_calls']>=budget['max_calls']:
        raise RuntimeError('finite Nat gate budget exhausted/out of bounds')
    return deadline

def check_launch_deadline(deadline):
    if time.monotonic()>=deadline:raise RuntimeError('Nat admission expired before worker launch')

def dispatch(config,fid,argument,order,caller,*,test_backend=None):
    if config.get('schema')!='bend-nat-vulkan-transport-v1' or caller.get('schema')!=config.get('schema') or config.get('caller')!=caller:
        raise RuntimeError('calling host/config binding mismatch')
    for key in ('plan','routing_plan','shader_source','shader','generation','worker_source','worker'):
        if digest(config[key])!=caller[key+'_sha256']:raise RuntimeError('calling host/artifact bytes mismatch: '+key)
    for binding in caller['runtime_bindings']:
        if digest(binding['path'])!=binding['sha256']:raise RuntimeError('runtime bytes mismatch')
    plan=json.loads(Path(config['plan']).read_text());validate(plan)
    generation=json.loads(Path(config['generation']).read_text())
    if generation.get('schema')!='bend-nat-approved-glsl-generation-v1' or generation.get('approved_GLSL_sha256')!=caller['shader_source_sha256'] or generation.get('SPIRV_sha256')!=caller['shader_sha256'] or generation.get('plan_sha256')!=caller['plan_sha256']:
        raise RuntimeError('approved GLSL/SPIR-V generation binding mismatch')
    if config.get('words')!=772 or config.get('groups')!=1 or config.get('local_size')!=[128,1,1] or config.get('roots')!=plan['roots']:
        raise RuntimeError('Nat exact dispatch contract mismatch')
    if not integer(argument,0,(1<<48)-1):raise RuntimeError('upstream full Nat immediate range')
    if argument>5 or not integer(fid,0,65535) or fid not in plan['roots'] or not integer(order,0,1):raise RuntimeError('Nat root/depth/order unsupported')
    # All identities/input checks precede admission and any worker/device work.
    if test_backend is None:
        if config.get('admitted') is not True:raise RuntimeError('Nat GPU admission disabled pending separate final gate')
        if not config.get('device') or not config.get('budget_file'):raise RuntimeError('Nat finite device/window absent')
        with open(config['budget_file'],'r+') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX);budget=json.load(stream)
            deadline=validate_budget(budget,time.monotonic())
            budget['reserved_calls']+=1;stream.seek(0);stream.truncate();json.dump(budget,stream);stream.flush()
        sys.path.insert(0,str(ROOT/'tools'))
        from run_examples import guard
        guard(config['device'])
    directory=Path(config['receipt_directory']);directory.mkdir(exist_ok=True)
    receipt_dir=Path(tempfile.mkdtemp(prefix='call-',dir=directory))
    initial=[0]*772;initial[:6]=[1,fid,argument,63,31,192];initial[13]=order;initial[-4:]=CANARIES
    inp=receipt_dir/'input.bin';output=receipt_dir/'output.bin';inp.write_bytes(struct.pack('<772I',*initial))
    receipt={'status':'prepared','GPU_execution':test_backend is None,'explicit_CPU_test_backend':test_backend is not None,'root':fid,'full_Nat_argument':argument,'order':order,'caller':caller}
    def save(): (receipt_dir/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    try:
        if test_backend is None:
            dev=config['device'];parent=os.getpid()
            args=[config['worker'],config['shader'],str(inp),str(output),'772','1',*[str(dev[k]) for k in ('index','major','minor','vendor','product','sysfs')],str(parent)]
            check_launch_deadline(deadline)
            p=subprocess.run(args,capture_output=True,timeout=3)
        else:p=test_backend(receipt_dir,initial,config)
        (receipt_dir/'native.stdout').write_bytes(p.stdout);(receipt_dir/'native.stderr').write_bytes(p.stderr)
        receipt['native_exit']=p.returncode
        if p.returncode:raise RuntimeError('Nat native worker unsuccessful exit')
        # subprocess.run has waited for exit and drained both streams through
        # clean EOF. No receipt is published based on bytes from a live child.
        raw=output.read_bytes()
        if len(raw)!=3088:raise RuntimeError('Nat native exact receipt framing')
        words=list(struct.unpack('<772I',raw))
        if words[10] or words[11]!=1 or words[12]!=words[9] or tuple(words[-4:])!=CANARIES:raise RuntimeError('Nat error/DONE/observer/canary receipt')
        expected=simulate(plan,fid,argument,order)
        if words!=expected or words[9]!=evaluate(plan,fid,argument):raise RuntimeError('Nat complete772-word receipt/oracle mismatch')
        if b'canaries_intact=1' not in p.stdout:raise RuntimeError('Nat native canary evidence absent')
        receipt.update(status='validated',output_sha256=hashlib.sha256(raw).hexdigest(),validated_words=772,clean_native_exit_and_EOF=True)
        save();return raw
    except Exception as error:
        receipt.update(status='failed',error=str(error));save();raise

def main():
    if len(sys.argv)!=7:raise RuntimeError('Nat controller CONFIG ROOT FULL_NAT ORDER CALLER_JSON EXPECTED_PARENT')
    bind_parent(int(sys.argv[6]))
    config=json.loads(Path(sys.argv[1]).read_text());caller=json.loads(sys.argv[5])
    raw=dispatch(config,int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4]),caller)
    # Only a completely validated receipt is forwarded, as an exact772-word
    # wire frame. Host also waits for clean EOF and controller successful exit.
    sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()
if __name__=='__main__':
    try:main()
    except Exception as error:print('Nat transport: '+str(error),file=sys.stderr);sys.exit(2)
