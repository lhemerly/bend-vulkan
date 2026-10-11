"""Fail-closed adapter for exactly two generated scalar tasks and their emitted join."""
from pathlib import Path
import re,json,hashlib,sys
from emit_u32_segment import Unsupported,expression,emit

def segment(source,fid):
 hits=list(re.finditer(r'WL_CASE\('+re.escape(fid)+r'\)\s*\{',source))
 if len(hits)!=1:raise Unsupported('unique segment required: '+fid)
 start=hits[0].end();depth=1
 for i in range(start,len(source)):
  if source[i]=='{':depth+=1
  elif source[i]=='}':
   depth-=1
   if depth==0:return source[start:i]
 raise Unsupported('unterminated segment')

# Paths this adapter does not emit. They are still pinned exactly, so drift in
# an unimplemented path is rejected instead of silently changing reviewed scope.
TAIL=r'''\s*WL_ROOM\(2\);\s*STK\(0\)\s*=\s*(?P<pv>\w+);\s*STK\(1\)\s*=\s*FID_PAIR_K2;\s*WL_PUSHN\(2\);
\s*if\s*\(!DEVICE\s*&&\s*!seq\s*&&\s*fid_nofk\(FID_AFFINE\)\)\s*\{
\s*u64\s+(?P<t3>\w+)\s*=\s*task_node\(e,\s*FID_AFFINE,\s*WL_CONT,\s*WL_IDX,\s*0\);
\s*e\.mem\[(?P=t3)\s*\+\s*0\]\s*=\s*(?P=pv);
\s*return\s*term_tsk\(FID_AFFINE,\s*(?P=t3)\);\s*\}\s*r0\s*=\s*(?P=pv);\s*WL_JMP\(FID_AFFINE\);\s*'''
K2=r'''\s*u32\s+(?P<x1>\w+)\s*=\s*STK\(-1\);\s*u32\s+(?P<a0>\w+)\s*=\s*r0;\s*WL_OPEN\s*WL_ROOM\(2\);
\s*STK\(0\)\s*=\s*(?P=a0);\s*STK\(1\)\s*=\s*FID_PAIR_K3;\s*WL_PUSHN\(2\);
\s*if\s*\(!DEVICE\s*&&\s*!seq\s*&&\s*fid_nofk\(FID_AFFINE\)\)\s*\{
\s*u64\s+(?P<t4>\w+)\s*=\s*task_node\(e,\s*FID_AFFINE,\s*WL_CONT,\s*WL_IDX,\s*0\);
\s*e\.mem\[(?P=t4)\s*\+\s*0\]\s*=\s*U32_BIN\((?P=x1),\s*\+,\s*1ull\);
\s*return\s*term_tsk\(FID_AFFINE,\s*(?P=t4)\);\s*\}
\s*r0\s*=\s*U32_BIN\((?P=x1),\s*\+,\s*1ull\);\s*WL_JMP\(FID_AFFINE\);\s*'''
K3=r'''\s*WL_POPN\(2\);\s*u32\s+(?P<a1>\w+)\s*=\s*STK\(1\);\s*u32\s+(?P<b0>\w+)\s*=\s*r0;\s*WL_OPEN
\s*if\s*\(!DEVICE\s*&&\s*!seq\s*&&\s*fid_nofk\(FID_PAIR_J2\)\)\s*\{
\s*u64\s+(?P<t5>\w+)\s*=\s*task_node\(e,\s*FID_PAIR_J2,\s*WL_CONT,\s*WL_IDX,\s*0\);
\s*e\.mem\[(?P=t5)\s*\+\s*0\]\s*=\s*(?P=a1);\s*e\.mem\[(?P=t5)\s*\+\s*1\]\s*=\s*(?P=b0);
\s*return\s*term_tsk\(FID_PAIR_J2,\s*(?P=t5)\);\s*\}
\s*r0\s*=\s*(?P=a1);\s*r1\s*=\s*(?P=b0);\s*WL_JMP\(FID_PAIR_J2\);\s*'''

def pin_ignored(source,x,tail):
 """Pin the FID_PAIR inline continuation this adapter never emits."""
 m=re.fullmatch(TAIL,tail,re.X)
 if m is None or m['pv']!=x:raise Unsupported('FID_PAIR inline tail changed')
 if re.fullmatch(K2,segment(source,'FID_PAIR_K2'),re.X) is None:raise Unsupported('FID_PAIR_K2 inline shape changed')
 if re.fullmatch(K3,segment(source,'FID_PAIR_K3'),re.X) is None:raise Unsupported('FID_PAIR_K3 inline shape changed')

def parse(source):
 affine=segment(source,'FID_AFFINE')
 _,_,affine_raw=emit(source,'FID_AFFINE')
 av=re.fullmatch(r'\s*u32 (\w+) = r0;\s*WL_OPEN\s*r0 = ([^;]+);\s*WL_RETN\(1\);\s*',affine)
 if av is None:raise Unsupported('affine shape')
 pair=segment(source,'FID_PAIR')
 branch=re.match(r'\s*u32 (?P<x>\w+) = r0;\s*WL_OPEN\s*if \(!seq\) \{(?P<body>[^{}]+)\}(?P<tail>.*)$',pair,re.S)
 if branch is None:raise Unsupported('parallel binding branch required')
 x=branch['x'];body=branch['body']
 pin_ignored(source,x,branch['tail'])
 pattern=r'''\s*u64 (?P<join>\w+) = task_node\(e, FID_PAIR_J2, WL_CONT, WL_IDX, 2\);
 \s*u64 (?P<left>\w+) = task_node\(e, FID_AFFINE, term_tsk\(FID_PAIR_J2, (?P=join)\), 0, 0\);
 \s*e.mem\[(?P=left) \+ 0\] = (?P<arg0>[^;]+);
 \s*e.mem\[(?P=join) \+ 0\] = term_tsk\(FID_AFFINE, (?P=left)\);
 \s*u64 (?P<right>\w+) = task_node\(e, FID_AFFINE, term_tsk\(FID_PAIR_J2, (?P=join)\), 1, 0\);
 \s*e.mem\[(?P=right) \+ 0\] = (?P<arg1>[^;]+);
 \s*e.mem\[(?P=join) \+ 1\] = term_tsk\(FID_AFFINE, (?P=right)\);
 \s*return term_tsk\(FID_PAIR_J2, (?P=join)\);\s*'''
 found=re.fullmatch(pattern.replace(' ','\\s*').replace('\n',''),body)
 if found is None:raise Unsupported('exact rem2/two-child task construction required')
 if len({found['join'],found['left'],found['right']})!=3:raise Unsupported('distinct task records required')
 join=segment(source,'FID_PAIR_J2')
 j=re.fullmatch(r'\s*u32 (?P<a>\w+) = r0;\s*u32 (?P<b>\w+) = r1;\s*WL_OPEN\s*r0 = (?P<raw>[^;]+);\s*WL_RETN\(1\);\s*',join)
 if j is None or j['a']==j['b']:raise Unsupported('two-U32 generated join required')
 fids={}
 for fid in ('FID_AFFINE','FID_PAIR','FID_PAIR_J2'):
  vals=re.findall(r'^#define '+fid+r' (\d+)$',source,re.M)
  if len(vals)!=1 or int(vals[0])>65535:raise Unsupported('FID encoding')
  fids[fid]=int(vals[0])
 if len(set(fids.values()))!=3:raise Unsupported('distinct FIDs required')
 table=re.search(r'CONSTV u8 FID_T\[\]\[3\] = \{(.+?)\};',source)
 if table is None:raise Unsupported('arity table required')
 arities=[int(a) for a in re.findall(r'\{\s*(\d+)\s*,\s*\d+\s*,\s*\d+\s*\}',table[1])]
 for name,want in [('FID_AFFINE',1),('FID_PAIR',1),('FID_PAIR_J2',2)]:
  if fids[name]>=len(arities) or arities[fids[name]]!=want:raise Unsupported('arity mismatch')
 return {'fids':fids,'arg_raw':[found['arg0'],found['arg1']],'arg_variable':x,'arg_glsl':[expression(found['arg0'],x),expression(found['arg1'],x)],'affine_raw':affine_raw,'affine_variable':av[1],'affine_glsl':expression(affine_raw,av[1]),'join_raw':j['raw'],'join_variables':[j['a'],j['b']],'join_glsl':expression(j['raw'],{j['a']:'a',j['b']:'b'}),'source_sha256':hashlib.sha256(source.encode()).hexdigest()}

def cpu_source(spec):
 return '''#include <stdint.h>
#include <stdio.h>
typedef uint32_t u32;typedef uint64_t u64;
#define U32_BIN(a,o,b) ((u64)((u32)(a) o (u32)(b)))
static u32 affine(u32 x){u32 AV=x;return (u32)(AFFINE);}
static u32 pair(u32 x){u32 XV=x;u32 A=affine((u32)(ARG0)),B=affine((u32)(ARG1));return (u32)(JOIN);}
int main(void){unsigned long long x;while(scanf("%llu",&x)==1){if(x>UINT32_MAX)return 2;printf("%u\\n",pair((u32)x));}return 0;}
'''.replace('AV',spec['affine_variable']).replace('AFFINE',spec['affine_raw']).replace('XV',spec['arg_variable']).replace('ARG0',spec['arg_raw'][0]).replace('ARG1',spec['arg_raw'][1]).replace('JOIN',spec['join_raw']).replace('A=',spec['join_variables'][0]+'=').replace(',B=',','+spec['join_variables'][1]+'=')
def shader_source(spec):
 template=(Path(__file__).resolve().parents[1]/'shaders/pair.template.comp').read_text()
 substitutions={'AFFINE_FID':str(spec['fids']['FID_AFFINE']),'JOIN_FID':str(spec['fids']['FID_PAIR_J2']),'ARG0':spec['arg_glsl'][0],'ARG1':spec['arg_glsl'][1],'AFFINE':spec['affine_glsl'],'JOIN':spec['join_glsl']}
 for key,value in substitutions.items():template=template.replace('@'+key+'@',value)
 if '@' in template:raise Unsupported('unresolved shader placeholder')
 return template

if __name__=='__main__':
 spec=parse(Path(sys.argv[1]).read_text());Path(sys.argv[2]).write_text(json.dumps(spec,indent=2)+'\n');Path(sys.argv[3]).write_text(cpu_source(spec));print(json.dumps(spec,indent=2))
