"""Reviewable call-site/order regression contracts; all mutants are STATIC ONLY."""
from pathlib import Path
import subprocess,json,tempfile,re
from check_litmus_static import check,function_body
ROOT=Path(__file__).resolve().parents[1]
def protocol(source):
 errors=[]
 try:body=function_body(source,'complete_task')
 except ValueError as e:return [str(e)]
 parts=[
  'w[ARENA+2u*slot]=result;',
  'w[ARENA+2u*slot+1u]=0u;',
  'uint oldRem=atomicAdd(w[REM],0xffffffffu,gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsRelease);',
  'if(oldRem==1u){',
  'if(acquireWord(REM)!=0u){firstError(4u);return;}',
  'uint a=w[ARENA],b=w[ARENA+2u];',
  'joined=generated_join(a,b);',
  'w[10]=joined;w[11]=0u;',
  'releaseWord(9u,2u);']
 cursor=0
 for part in parts:
  part=re.sub(r'\s+','',part)
  at=body.find(part,cursor)
  if at<0:errors.append('result stores -> Buffer release decrement -> winning acquire -> join reads -> generated join -> root stores -> root release');break
  cursor=at+len(part)
 if body.count('uinta=w[ARENA],b=w[ARENA+2u];')!=1:errors.append('unique join result read')
 if body.count('w[10]=joined;')!=1:errors.append('unique root result store')
 if 'if((was&bit)!=0u){firstError(3u);return;}' not in body:errors.append('duplicate completion guard')
 if 'if(claimed!=0u){firstError(5u);return;}' not in body:errors.append('exactly-once join guard')
 return errors

def main():
 source=(ROOT/'shaders/pair.generated.comp').read_text()
 stores='    w[ARENA+2u*slot]=result;\n    w[ARENA+2u*slot+1u]=0u;\n'
 decrement='    uint oldRem=atomicAdd(w[REM],0xffffffffu,gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsRelease);\n'
 variants={'baseline':source,
 'decrement-relaxed':source.replace(decrement,decrement.replace('gl_StorageSemanticsBuffer,gl_SemanticsRelease','gl_StorageSemanticsNone,gl_SemanticsRelaxed')),
 'winning-acquire-relaxed':source.replace('if(acquireWord(REM)!=0u)','if(relaxedWord(REM)!=0u)'),
 'join-read-before-acquire':source.replace('        uint a=w[ARENA],b=w[ARENA+2u];\n','').replace('    uint oldRem=', '    uint a=w[ARENA],b=w[ARENA+2u];\n    uint oldRem='),
 'result-store-after-decrement':source.replace(stores+decrement,decrement+stores),
 'root-publication-relaxed':source.replace('releaseWord(9u,2u);','atomicStore(w[9],2u,gl_ScopeDevice,gl_StorageSemanticsNone,gl_SemanticsRelaxed);'),
 'missing-duplicate-guard':source.replace('if((was&bit)!=0u){firstError(3u);return;}','if((was&bit)!=0u){firstError(3u);}'),
 'missing-join-claim-guard':source.replace('if(claimed!=0u){firstError(5u);return;}','if(claimed!=0u){firstError(5u);}'),
 'accidental-buffer-phase':source.replace('gl_StorageSemanticsShared,gl_SemanticsAcquireRelease','gl_StorageSemanticsShared|gl_StorageSemanticsBuffer,gl_SemanticsAcquireRelease')}
 results={}
 with tempfile.TemporaryDirectory(prefix='bend-pair-static-',dir='/tmp') as tmp:
  d=Path(tmp)
  for name,text in variants.items():
   shader=d/(name+'.comp');spv=d/(name+'.spv');shader.write_text(text)
   subprocess.run(['glslangValidator','-V','--target-env','vulkan1.2',shader,'-o',spv],check=True,capture_output=True)
   subprocess.run(['spirv-val','--target-env','vulkan1.2',spv],check=True,capture_output=True)
   asm=subprocess.run(['spirv-dis',spv],check=True,capture_output=True,text=True).stdout
   failures=check(asm)+protocol(text);results[name]=failures
   if name=='baseline' and failures:raise AssertionError(failures)
   if name!='baseline' and not failures:raise AssertionError('mutant escaped: '+name)
 result={'gpu_dispatches':0,'scope':'Call-site/order source regression contracts for reviewed helper plus SPIR-V semantics checks; not protocol proof','variants':results}
 (ROOT/'evidence/pair-preparation/static-check.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
