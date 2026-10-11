"""Independent finite F32 oracle; all inputs validated before word narrowing."""
import ctypes,math,struct
from nat_oracle import LIMITS,MASK,integer,expression as word_expression
libm=ctypes.CDLL('libm.so.6')
for op in ('sin','cos','tan'):
 f=getattr(libm,op+'f');f.argtypes=[ctypes.c_float];f.restype=ctypes.c_float

def bits(v):return struct.unpack('<I',struct.pack('<f',v))[0]
def number(v):
 if not integer(v,0,MASK):raise ValueError('full F32 word')
 return struct.unpack('<f',struct.pack('<I',v))[0]
def rounded(v):
 try:return number(bits(v))
 except OverflowError:return math.copysign(math.inf,v)
def expression(x,args,budget=None):
 if isinstance(x,list):return word_expression(x,args)
 if budget is None:budget=[64]
 budget[0]-=1
 if budget[0]<0 or type(x)is not dict:raise ValueError('typed expression bound')
 op=x.get('op')
 if x.get('type')=='U32' and op=='from-f32':
  v=expression(x['value'],args,budget);return int(v) if 1<=v<4294967296 else 0
 if x.get('type')!='F32':raise ValueError('F32 expression type')
 if op=='arg':
  if not integer(x.get('index'),0,len(args)-1):raise ValueError('F32 argument index')
  return args[x['index']]
 if op=='bits':
  v=number(x['bits'])
  if not math.isfinite(v):raise ValueError('nonfinite literal')
  return v
 if op in ('sin','cos','tan'):return float(getattr(libm,op+'f')(expression(x['value'],args,budget)))
 if op in ('add','mul'):
  a=expression(x['left'],args,budget);b=expression(x['right'],args,budget);return rounded(a+b if op=='add' else a*b)
 raise ValueError('unsupported F32 expression')
def validate(plan):
 if plan.get('schema')!='bend-nat-f32-fork-v1' or plan.get('depth')!=5 or plan.get('tasks')!=63 or len(plan.get('segments',[]))!=1:raise ValueError('F32 ABI')
 s=plan['segments'][0];fid=s.get('id');join=s.get('join')
 if not integer(fid,0,65535) or not integer(join,0,65535) or fid==join or plan.get('roots')!=[fid]:raise ValueError('F32 root/join identities')
 if s.get('leaf',{}).get('type')!='U32':raise ValueError('F32 result type')
 expression(s['leaf'],[0.0]);children=s.get('children',[])
 if len(children)!=2 or any(c.get('id')!=fid or c.get('slot')!=i for i,c in enumerate(children)):raise ValueError('F32 guarded children')
 for c in children:
  if c.get('payload',{}).get('type')!='F32':raise ValueError('F32 child type')
  expression(c['payload'],[0.0])
 return {fid:{'role':'task','match':{'zero':{'op':'result','value':s['leaf']},'successor':{'op':'fork','join':join,'children':children}}},join:{'role':'join','value':['bin','+',['arg',0],['arg',1]]}}
def evaluate(plan,root,argument,payload):
 by=validate(plan);v=number(payload)
 if not math.isfinite(v) or not integer(argument,0,5) or root not in plan['roots']:raise ValueError('F32 root input')
 def go(n,x):
  if not n:return expression(plan['segments'][0]['leaf'],[x])
  values=[expression(c['payload'],[x]) for c in plan['segments'][0]['children']]
  if any(not math.isfinite(a) for a in values):raise ValueError('nonfinite child')
  return (go(n-1,values[0])+go(n-1,values[1]))&MASK
 return go(argument,v)
