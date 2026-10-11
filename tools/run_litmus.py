"""Private bounded publication gate; preparation is CPU-only unless --gpu is explicit."""
from pathlib import Path
import argparse,json,hashlib
import run_examples as r
ROOT=r.ROOT
def main():
 p=argparse.ArgumentParser();p.add_argument('--gpu',action='store_true');p.add_argument('--render-node',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.gpu and a.render_node is None:p.error('--gpu requires --render-node')
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 r.run(['python3',ROOT/'tools/build_litmus.py'],out/'build.txt')
 r.run(['python3',ROOT/'tools/check_litmus_static.py'],out/'static-check.txt')
 shader=ROOT/'shaders/publication_litmus.comp';manifest=json.loads((ROOT/'evidence/litmus-fixtures/manifest.json').read_text())
 if hashlib.sha256(shader.read_bytes()).hexdigest()!=manifest['shader_sha256']:raise RuntimeError('fixture/source mismatch')
 spv=out/'publication.spv';host=out/'runner'
 r.run(['glslangValidator','-V','--target-env','vulkan1.2',shader,'-o',spv],out/'shader-compile.txt')
 r.run(['spirv-val','--target-env','vulkan1.2',spv],out/'shader-validate.txt')
 r.run(['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',ROOT/'native/runner.c','-lvulkan','-o',host],out/'host-compile.txt')
 r.run([host,'--guard-selftest'],out/'guard-selftest.txt')
 result={'gpu_dispatches':0,'scope':'strictly alternating single-workgroup SPSC occupancy<=1; publication/reuse/wrap only; distinct subgroup leaders; no queue-full, simultaneous producers, fork/join or cross-workgroup scheduler coverage','shader_sha256':hashlib.sha256(shader.read_bytes()).hexdigest(),'spirv_sha256':hashlib.sha256(spv.read_bytes()).hexdigest(),'cases':[]}
 if a.gpu:
  dev=r.identity(a.render_node,r.run([host,'--probe-inventory'],out/'inventory.txt'));result['device']=dev
  for start in manifest['starts']:
   name=f'{start:08x}';inp=ROOT/f'evidence/litmus-fixtures/{name}-input.bin';expected=r.readwords(ROOT/f'evidence/litmus-fixtures/{name}-expected.bin')
   guard=r.guard(dev);output=out/(name+'-output.bin')
   r.run([host,spv,inp,output,44,1,dev['index'],dev['major'],dev['minor'],dev['vendor'],dev['product'],dev['sysfs']],out/(name+'-gpu.txt'),3)
   actual=r.readwords(output)
   if len(actual)!=44 or actual[:40]!=expected:raise RuntimeError('exact buffer mismatch: '+name)
   size,count,producer,consumer=actual[40:]
   if size not in (4,8,16,32,64) or count<2 or (producer,consumer)!=(0,1):raise RuntimeError('distinct subgroup evidence failed')
   result['gpu_dispatches']+=1;result['cases'].append({'start':start,'pairs':4096,'subgroup_size':size,'subgroups':count,'producer_subgroup':producer,'consumer_subgroup':consumer,'guard':guard,'exact_words':40})
 (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
