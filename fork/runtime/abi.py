"""Independent complete-buffer oracle for the finite 24-word fork ABI."""
import operator
def expression(e,args):
 if e[0]=='arg':return args[e[1]]
 if e[0]=='lit':return e[1]
 op={'+':operator.add,'-':operator.sub,'*':operator.mul,'&':operator.and_,'|':operator.or_,'^':operator.xor}[e[1]]
 return op(expression(e[2],args),expression(e[3],args))&0xffffffff
def expected_words(plan,fid,x,order):
 w=[0]*24;w[0]=fid;w[1]=x;w[11]=order
 by={s['fid']:s for s in plan['segments']};root=next((s for s in by.values() if s['id']==fid and fid in plan['roots']),None)
 if order not in (0,1):w[3]=6;return w
 if root is None:w[3]=2;return w
 if 'result' in root:w[2]=expression(root['result'],[x])
 else:
  f=root['fork'];join=by[f['join']];w[6]=3;w[7]=join['id'];w[10]=1
  for c in f['children']:
   i=c['index'];arg=expression(c['args'][0],[x]);child=by[c['fid']]
   w[12+4*i:16+4*i]=[child['id'],arg,i,join['id']];w[8+i]=expression(child['result'],[arg])
  w[2]=expression(join['result'],w[8:10])
 w[4]=2;w[20]=w[2];return w
