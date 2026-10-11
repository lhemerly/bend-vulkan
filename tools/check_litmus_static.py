"""Check narrow SPIR-V ordering invariants; mutants are compiled, NEVER dispatched."""
from pathlib import Path
import subprocess,json,tempfile,re
ROOT=Path(__file__).resolve().parents[1]
def check(asm):
 constants={}
 for line in asm.splitlines():
  p=line.split()
  if len(p)==5 and p[1]=='=' and p[2]=='OpConstant':
   try:constants[p[0]]=int(p[4])
   except ValueError:pass
 def value(x):return constants.get(x,-1)
 loads=[];stores=[];barriers=[]
 for line in asm.splitlines():
  p=line.split()
  if 'OpAtomicLoad' in p:
   i=p.index('OpAtomicLoad');loads.append((value(p[i+3]),value(p[i+4])))
  elif p and p[0]=='OpAtomicStore':stores.append((value(p[2]),value(p[3])))
  elif p and p[0]=='OpControlBarrier':barriers.append(tuple(map(value,p[1:])))
 problems=[]
 if 'OpMemoryModel Logical Vulkan' not in asm:problems.append('Vulkan memory model')
 if (1,66) not in loads:problems.append('Device Buffer acquire load')
 if (1,68) not in stores:problems.append('Device Buffer release store')
 if not barriers or any(b!=(2,2,264) for b in barriers):problems.append('Shared-only workgroup phase barrier')
 for builtin in ('SubgroupId','SubgroupLocalInvocationId','SubgroupSize','NumSubgroups'):
  if 'BuiltIn '+builtin not in asm:problems.append(builtin)
 return problems

def function_body(source,name):
 match=re.search(r'\b(?:bool|uint|void)\s+'+re.escape(name)+r'\s*\([^)]*\)\s*\{',source)
 if not match:raise ValueError('missing helper '+name)
 start=match.end();depth=1
 for i in range(start,len(source)):
  if source[i]=='{':depth+=1
  elif source[i]=='}':
   depth-=1
   if depth==0:return re.sub(r'\s+','',source[start:i])
 raise ValueError('unbalanced helper '+name)

def check_protocol_source(source):
 """Fail-closed contracts for THIS reviewed helper shape, not general GLSL verification."""
 problems=[]
 try:
  pop=function_body(source,'ringPop');push=function_body(source,'ringPush')
  def ordered(body,parts,label):
   cursor=0
   for part in parts:
    at=body.find(re.sub(r'\s+','',part),cursor)
    if at<0:problems.append(label);return
    cursor=at+len(re.sub(r'\s+','',part))
  ordered(pop,['uint mark = loadAcquire(W_SLOTS + 2u * slot + 1u);',
   'if ((mark >> 31) != lapOf(get)) return false;',
   'lo = w[W_SLOTS + 2u * slot];','hi = mark & HI_MASK;',
   'storeRelease(W_GET, get + 1u);'], 'ringPop marker acquire -> marker validation -> payload reads -> get release')
  ordered(push,['uint get = loadAcquire(W_GET);','if (pos - get >= SLOTS)',
   'w[W_SLOTS + 2u * slot] = lo;',
   'storeRelease(W_SLOTS + 2u * slot + 1u, hi | (lapOf(pos) << 31));'],
   'ringPush get acquire -> capacity check -> payload store -> marker release')
  # Reject duplicate payload accesses that could occur outside the ordered chain.
  if pop.count('lo=w[W_SLOTS+2u*slot];')!=1:problems.append('unique ringPop payload read')
  if push.count('w[W_SLOTS+2u*slot]=lo;')!=1:problems.append('unique ringPush payload write')
 except ValueError as error:problems.append(str(error))
 return problems

def main():
 source=(ROOT/'shaders/publication_litmus.comp').read_text()
 variants={'baseline':source,
  'missing-load-acquire':source.replace('gl_StorageSemanticsBuffer, gl_SemanticsAcquire);','gl_StorageSemanticsNone, gl_SemanticsRelaxed);'),
  'missing-store-release':source.replace('gl_StorageSemanticsBuffer, gl_SemanticsRelease);','gl_StorageSemanticsNone, gl_SemanticsRelaxed);'),
  'marker-callsite-relaxed':source.replace('uint mark = loadAcquire(', 'uint mark = loadRelaxed('),
  'payload-before-marker':source.replace('uint mark = loadAcquire(W_SLOTS + 2u * slot + 1u);','lo = w[W_SLOTS + 2u * slot];\n    uint mark = loadAcquire(W_SLOTS + 2u * slot + 1u);').replace('    lo = w[W_SLOTS + 2u * slot];\n    hi = mark','    hi = mark'),
  'reuse-get-callsite-relaxed':source.replace('uint get = loadAcquire(W_GET);','uint get = loadRelaxed(W_GET);'),
  'accidental-buffer-barrier':source.replace('gl_StorageSemanticsShared, gl_SemanticsAcquireRelease','gl_StorageSemanticsShared | gl_StorageSemanticsBuffer, gl_SemanticsAcquireRelease')}
 results={}
 with tempfile.TemporaryDirectory(prefix='bend-static-',dir='/tmp') as tmp:
  d=Path(tmp)
  for name,text in variants.items():
   shader=d/(name+'.comp');spv=d/(name+'.spv');shader.write_text(text)
   subprocess.run(['glslangValidator','-V','--target-env','vulkan1.2',shader,'-o',spv],check=True,capture_output=True)
   subprocess.run(['spirv-val','--target-env','vulkan1.2',spv],check=True,capture_output=True)
   asm=subprocess.run(['spirv-dis',spv],check=True,capture_output=True,text=True).stdout
   problems=check(asm)+check_protocol_source(text);results[name]=problems
   if name=='baseline' and problems:raise AssertionError(problems)
   if name!='baseline' and not problems:raise AssertionError('mutant escaped check: '+name)
 result={'gpu_dispatches':0,'scope':'SPIR-V instruction checks plus call-site/order-specific source contracts for the reviewed helper shape; not a memory-model proof or scheduler test','variants':results}
 (ROOT/'evidence/litmus-static-check.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
