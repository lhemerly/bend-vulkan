"""Private frozen generated pair/join gate. Preparation unless --gpu is explicit."""
from pathlib import Path
import argparse,json,hashlib,subprocess,struct
import run_examples as r
from emit_pair_segment import parse,shader_source,cpu_source
ROOT=r.ROOT
SOURCE_HASH='9c0b22169098b31eac42d10555772260446a18c07b21ba8b7ed03a3a5495f607'
SHADER_HASH='cac312770932f72594731256615c42d53a435a7a7b89dfefc2ffdd51a833e0c4'
SPIRV_HASH='747e26307cf717b42bcb47317af01b5ba7ac119e7486273ac8d3f945af53c983'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def prepare(out):
 r.run(['bun',ROOT/'tools/compile_example.ts',ROOT/'examples/pair_gpu.bend',out/'generated.c'],out/'bend-compile.txt')
 if digest(out/'generated.c')!=SOURCE_HASH:raise RuntimeError('checked source differs from frozen review')
 spec=parse((out/'generated.c').read_text());(out/'adapter.json').write_text(json.dumps(spec,indent=2)+'\n')
 (out/'pair.comp').write_text(shader_source(spec));(out/'oracle.c').write_text(cpu_source(spec))
 if digest(out/'pair.comp')!=SHADER_HASH:raise RuntimeError('generated shader differs from frozen review')
 r.run(['glslangValidator','-V','--target-env','vulkan1.2',out/'pair.comp','-o',out/'pair.spv'],out/'shader-compile.txt')
 r.run(['spirv-val','--target-env','vulkan1.2',out/'pair.spv'],out/'shader-validate.txt')
 if digest(out/'pair.spv')!=SPIRV_HASH:raise RuntimeError('SPIR-V differs from frozen review')
 r.run(['clang','-std=c11','-O2',out/'generated.c','-lpthread','-lm','-o',out/'upstream-cpu'],out/'upstream-compile.txt')
 if r.run([out/'upstream-cpu','--gpu','off'],out/'upstream-main.txt').strip()!='419757':raise RuntimeError('full upstream CPU main mismatch')
 r.run(['python3',ROOT/'tools/check_pair_cpu.py'],out/'shader-cpu-tests.txt')
 r.run(['python3',ROOT/'tools/check_pair_static.py'],out/'static-check.txt')
 r.run(['python3','-m','unittest','discover','-s',ROOT/'tools','-p','test_emit*py'],out/'adapter-tests.txt')
 r.run(['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',ROOT/'native/runner.c','-lvulkan','-o',out/'runner'],out/'host-compile.txt')
 r.run([out/'runner','--guard-selftest'],out/'guard-selftest.txt')
 # Literal translation of reviewed GLSL complete_task/initialization. Atomics sequential.
 translated=(ROOT/'evidence/pair-preparation/shader-cpu.cpp').read_text()
 prefix=translated[:translated.index('uint inputs[]={')]
 driver='''int main(int argc,char**argv){
 if(argc!=6){return 2;}
 uint v[5];
 for(uint i=0;i<5;i++){char *end=nullptr;unsigned long long n=std::strtoull(argv[i+1],&end,10);if(!end||*end||n>UINT32_MAX)return 2;v[i]=(uint)n;}
 start(v[0],v[1],v[2],v[3],v[4]);
 bool valid=w[4]==0u;
 if(valid)complete_task(v[1]);
 if(valid)complete_task(v[1]^1u);
 if(valid&&v[4]==1u)complete_task(v[1]);
 if(acquireWord(9u)==2u)w[23]=w[10];
 canaries();return std::fwrite(w,sizeof(uint),48,stdout)==48?0:2;}
'''
 (out/'fixture-cpu.cpp').write_text(prefix+driver)
 r.run(['c++','-std=c++17','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all',out/'fixture-cpu.cpp','-o',out/'fixture-cpu'],out/'fixture-compile.txt')
 data=json.loads((ROOT/'evidence/pair-preparation/cpu-inputs.json').read_text())
 cases=[]
 for i,x in enumerate(data['inputs']):
  for order in (0,1):cases.append({'name':f'valid-{i:03d}-order{order}','args':[x,order,10,2,0],'kind':'valid','root_oracle':data['expected'][i]})
 for order in (0,1):cases.append({'name':f'duplicate-after-root-order{order}','args':[12345,order,10,2,1],'kind':'duplicate-after-root','root_oracle':419757})
 for arena in range(10):cases.append({'name':f'arena-capacity-{arena}','args':[12345,0,arena,2,0],'kind':'capacity'})
 for queue in range(2):cases.append({'name':f'queue-capacity-{queue}','args':[12345,0,10,queue,0],'kind':'capacity'})
 for name,args in [('order',[12345,2,10,2,0]),('arena-upper',[12345,0,11,2,0]),('queue-upper',[12345,0,10,3,0]),('repeat',[12345,0,10,2,2])]:cases.append({'name':'invalid-'+name,'args':args,'kind':'invalid-input'})
 for case in cases:
  initial=[0xdeadbeef]*48;initial[:4]=case['args'][:4];initial[22]=case['args'][4]
  r.words(out/(case['name']+'-input.bin'),initial)
  cpu=subprocess.run([out/'fixture-cpu',*map(str,case['args'])],capture_output=True,timeout=3,check=True)
  if len(cpu.stdout)!=192:raise RuntimeError('CPU fixture byte count')
  (out/(case['name']+'-expected.bin')).write_bytes(cpu.stdout)
  w=list(struct.unpack('<48I',cpu.stdout))
  if case['kind']=='valid' and not (w[4]==0 and w[9]==2 and w[10]==case['root_oracle'] and w[12:14]==[1,1]):raise RuntimeError('independent emitted CPU oracle mismatch')
  if case['kind']=='duplicate-after-root' and not(w[4]==3 and w[9]==2 and w[10]==419757 and w[12:14]==[1,1]):raise RuntimeError('duplicate CPU fixture mismatch')
  if case['kind'] in ('capacity','invalid-input') and not(w[4]==(1 if case['kind']=='capacity' else 6) and w[9]==0 and w[12:16]==[0,0,0,0]):raise RuntimeError('failure CPU fixture mismatch')
 (out/'fixture-matrix.json').write_text(json.dumps(cases,indent=2)+'\n')
 return cases

def main():
 p=argparse.ArgumentParser();p.add_argument('--gpu',action='store_true');p.add_argument('--render-node',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.gpu and a.render_node is None:p.error('--gpu requires --render-node')
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);cases=prepare(out)
 result={'gpu_dispatches':0,'fixture_cases':len(cases),'reviewed_source_sha256':SOURCE_HASH,'reviewed_shader_sha256':SHADER_HASH,'reviewed_spirv_sha256':SPIRV_HASH,'scope':'finite generated two-task/join, prescribed completion order; no simultaneous producers/general scheduler/compiler integration','cpu_only_cases':['duplicate-before-join','corrupted task FID/location'],'cases':[]}
 def save(): (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
 save()
 if a.gpu:
  dev=r.identity(a.render_node,r.run([out/'runner','--probe-inventory'],out/'inventory.txt'));result['device']=dev
  for case in cases:
   if digest(out/'pair.comp')!=SHADER_HASH or digest(out/'pair.spv')!=SPIRV_HASH:raise RuntimeError('frozen shader changed before dispatch')
   guard=r.guard(dev);name=case['name'];output=out/(name+'-output.bin')
   r.run([out/'runner',out/'pair.spv',out/(name+'-input.bin'),output,48,1,dev['index'],dev['major'],dev['minor'],dev['vendor'],dev['product'],dev['sysfs']],out/(name+'-gpu.txt'),3)
   expected=(out/(name+'-expected.bin')).read_bytes()
   if output.read_bytes()!=expected:raise RuntimeError('48-word GPU/CPU mismatch: '+name)
   result['gpu_dispatches']+=1;result['cases'].append({'name':name,'kind':case['kind'],'args':case['args'],'exact_words':48,'output_sha256':digest(output),'guard':guard});save()
  result['status']='passed'
 else:result['status']='prepared CPU/static; no GPU dispatch'
 save();print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
if __name__=='__main__':main()
