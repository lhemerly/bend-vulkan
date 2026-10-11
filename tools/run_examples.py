"""Bounded local example gate. CPU preparation by default; --gpu adds guarded hardware tests."""
from pathlib import Path
import argparse,subprocess,struct,json,os,stat,random,hashlib,re
ROOT=Path(__file__).resolve().parents[1]
def run(args,log,timeout=10):
 r=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,timeout=timeout)
 log.write_bytes(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError(f'command exit{r.returncode}: {log}: '+r.stderr.decode(errors='replace'))
 return r.stdout.decode()
def words(path,values):path.write_bytes(struct.pack('<'+'I'*len(values),*values))
def readwords(path):
 b=path.read_bytes()
 if len(b)%4:raise RuntimeError('unaligned output')
 return list(struct.unpack('<'+'I'*(len(b)//4),b))
def identity(node,probe):
 node=node.resolve(strict=True);m=node.stat()
 if not stat.S_ISCHR(m.st_mode) or node.parent!=Path('/dev/dri'):raise RuntimeError('explicit DRM render node required')
 major,minor=os.major(m.st_rdev),os.minor(m.st_rdev)
 selected=[]
 for line in probe.splitlines():
  p=line.split('\t')
  if len(p)==12 and p[1]=='hardware' and (int(p[5]),int(p[6]))==(major,minor):selected.append(p)
 if len(selected)!=1:raise RuntimeError('no unique hardware Vulkan identity for render node')
 p=selected[0];sys=Path(f'/sys/dev/char/{major}:{minor}/device').resolve(strict=True)
 vendor=int((sys/'vendor').read_text().strip(),16);product=int((sys/'device').read_text().strip(),16)
 if(vendor,product)!=(int(p[3]),int(p[4])):raise RuntimeError('Vulkan/DRM PCI mismatch')
 return {'node':str(node),'sysfs':str(sys),'index':int(p[0]),'major':major,'minor':minor,'vendor':vendor,'product':product,'name':p[11]}
def guard(dev):
 if os.stat('/proc/self/ns/pid').st_ino!=0xEFFFFFFC or os.readlink('/proc/self')!=str(os.getpid()):raise RuntimeError('initial host PID namespace and consistent procfs required')
 mounts=[line for line in Path('/proc/self/mountinfo').read_text().splitlines() if len(line.split())>5 and line.split()[4]=='/proc']
 if len(mounts)!=1 or mounts[0].split()[3]!='/' or ' - proc ' not in mounts[0] or 'subset=' in mounts[0] or any(v!='0' for v in re.findall(r'hidepid=([^,\s]+)',mounts[0])):raise RuntimeError('restricted/unknown procfs mount')
 node=Path(dev['node']);m=node.stat()
 if(os.major(m.st_rdev),os.minor(m.st_rdev))!=(dev['major'],dev['minor']):raise RuntimeError('render identity changed')
 sys=Path(dev['sysfs'])
 if Path(f"/sys/dev/char/{dev['major']}:{dev['minor']}/device").resolve()!=sys:raise RuntimeError('PCI association changed')
 if(int((sys/'vendor').read_text().strip(),16),int((sys/'device').read_text().strip(),16))!=(dev['vendor'],dev['product']):raise RuntimeError('PCI identity changed')
 for p in Path('/proc').iterdir():
  if not p.name.isdecimal():continue
  try:name=(p/'comm').read_text().strip().lower()
  except FileNotFoundError:continue
  except PermissionError:raise RuntimeError('cannot inspect competing host process')
  if any(s in name for s in ('gamescope','wine','play main','battlenet','leira','warframe','minecraft','dota2','eldenring','lutris','heroic')):raise RuntimeError('competing application: '+name)
 guard_clients(dev)
 busy=int((sys/'gpu_busy_percent').read_text());used=int((sys/'mem_info_vram_used').read_text());total=int((sys/'mem_info_vram_total').read_text())
 temps=[int(x.read_text()) for x in (sys/'hwmon').glob('*/temp*_input')]
 if busy>20 or not total or used/total>.8 or not temps or max(temps)>65000 or max(temps)<=0:raise RuntimeError('device busy/pressure/thermal guard')
 return {'busy_percent':busy,'vram_used':used,'vram_total':total,'temperatures_mC':temps}
def guard_clients(dev):
 os_clients={'cosmic-comp':('/usr/bin/cosmic-comp',),'Xwayland':('/usr/bin/Xwayland',),'cosmic-panel':('/usr/bin/cosmic-panel',),'cosmic-app-libr':('/usr/bin/cosmic-app-library',),'xdg-desktop-por':('/usr/lib/xdg-desktop-portal','/usr/lib/xdg-desktop-portal-gtk','/usr/lib/xdg-desktop-portal-cosmic'),'brave':('/opt/brave-bin/brave',),'ChatGPT':('/usr/lib/chatgpt/ChatGPT',)}
 def allowed_client(process,name):
  try:
   link=process/'exe';exe=link.resolve(strict=True);live=link.stat();expected=exe.stat()
   return str(exe) in os_clients.get(name,()) and stat.S_ISREG(expected.st_mode) and expected.st_uid==0 and not expected.st_mode&0o022 and (live.st_dev,live.st_ino)==(expected.st_dev,expected.st_ino)
  except (OSError,RuntimeError):return False
 services={'systemd','systemd-journal','systemd-userdbd','systemd-resolve','systemd-timesyn','systemd-udevd','systemd-logind','systemd-userwor','dbus-broker-lau','dbus-broker','ananicy-cpp','NetworkManager','avahi-daemon','cosmic-greeter-','dmemcg-booster','tailscaled','(sd-pam)','greetd','lact','power-profiles-','polkitd','upowerd','fusermount3','udisksd','rtkit-daemon'}
 unknown=[];unreadable=[];device_number=os.makedev(dev['major'],dev['minor'])
 for p in Path('/proc').iterdir():
  if not p.name.isdecimal() or int(p.name)==os.getpid():continue
  try:name=(p/'comm').read_text().strip();fds=list((p/'fd').iterdir())
  except FileNotFoundError:continue
  except PermissionError:
   try:
    if int((p/'statm').read_text().split()[0])==0:continue
    name=(p/'comm').read_text().strip()
    if name in services:continue
   except (FileNotFoundError,PermissionError):name='unreadable'
   unreadable.append({'pid':p.name,'comm':name});continue
  for f in fds:
   try:m=f.stat()
   except FileNotFoundError:continue
   except PermissionError:
    if name in services:continue
    unreadable.append({'pid':p.name,'comm':name});break
   if stat.S_ISCHR(m.st_mode) and m.st_rdev==device_number and not allowed_client(p,name):
    unknown.append({'pid':p.name,'comm':name});break
 if unknown or unreadable:raise RuntimeError('selected GPU client/visibility unknowns: '+json.dumps({'non_OS_clients':unknown,'unreadable_userspace':unreadable}))
def main():
 a=argparse.ArgumentParser();a.add_argument('--gpu',action='store_true');a.add_argument('--render-node',type=Path);a.add_argument('--output',type=Path,required=True);args=a.parse_args()
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
 host=out/'runner'
 run(['cc','-O1','-std=c11','-Wall','-Wextra','-Werror',ROOT/'native/runner.c','-lvulkan','-o',host],out/'host-compile.txt')
 run([host,'--guard-selftest'],out/'guard-selftest.txt')
 run(['bun',ROOT/'tools/compile_example.ts',ROOT/'examples/affine_gpu.bend',out/'generated.c'],out/'bend-compile.txt')
 run(['python3',ROOT/'tools/emit_u32_segment.py',out/'generated.c','FID_AFFINE',out/'affine.comp',out/'segment.c'],out/'adapter.json')
 run(['clang','-std=c11','-O2',out/'generated.c','-lpthread','-lm','-o',out/'upstream-cpu'],out/'upstream-compile.txt')
 value=run([out/'upstream-cpu','--gpu','off'],out/'upstream-result.txt').strip()
 if value!='209870':raise RuntimeError('upstream Bend example result mismatch')
 run(['cc','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',out/'segment.c','-o',out/'segment-cpu'],out/'segment-compile.txt')
 inputs=[0,1,12345,0xffffffff,0x80000000,0xffff0000]+[random.Random(i+17).getrandbits(32) for i in range(124)]
 r=subprocess.run([out/'segment-cpu'],input='\n'.join(map(str,inputs))+'\n',capture_output=True,text=True,timeout=5)
 expected=list(map(int,r.stdout.split()))
 if r.returncode or len(expected)!=len(inputs):raise RuntimeError('CPU segment oracle failed')
 initial=[len(inputs)]+inputs+[0xdeadbeef]*len(inputs);final=[len(inputs)]+inputs+expected
 words(out/'segment-input.bin',initial);words(out/'segment-expected.bin',final)
 for name,source in [('segment',out/'affine.comp'),('ring',ROOT/'shaders/ring_fixture.comp')]:
  run(['glslangValidator','-V','--target-env','vulkan1.2',source,'-o',out/f'{name}.spv'],out/f'{name}-compile.txt')
  run(['spirv-val','--target-env','vulkan1.2',out/f'{name}.spv'],out/f'{name}-validate.txt')
 summary={'upstream':'11d483271b46e445b922756d5fd4127a1ea99ae8','supported':'one real straight-line scalar U32 segment; +,-,*,&,|,^; no runtime/fork/heap','upstream_main_result':value,'segment_vectors':len(inputs),'gpu_dispatches':0}
 if args.gpu:
  if args.render_node is None:raise RuntimeError('--gpu requires explicit --render-node')
  dev=identity(args.render_node,run([host,'--probe-inventory'],out/'inventory.txt'))
  summary['device']=dev;summary['guards']=[]
  def dispatch(name,shader,input,expected,groups):
   summary['guards'].append(guard(dev));result=out/(name+'-output.bin')
   run([host,shader,input,result,len(expected),groups,dev['index'],dev['major'],dev['minor'],dev['vendor'],dev['product'],dev['sysfs']],out/(name+'-gpu.txt'),3)
   if readwords(result)!=expected:raise RuntimeError(name+' exact GPU/CPU buffer mismatch')
   summary['gpu_dispatches']+=1
  # Ring ABI fixed4, exactly30logicalwords; expected from independently checked CPU fixture.
  vectors=(ROOT/'evidence/shader-cpu-vectors.txt').read_text().splitlines()
  for i in (0,126,127):
   expected_ring=[int(x,16) for x in vectors[i].split()];initial_ring=[0xdeadbeef]*30;initial_ring[11:19]=expected_ring[11:19]
   inp=out/f'ring-{i}-input.bin';words(inp,initial_ring)
   dispatch(f'ring-{i}',out/'ring.spv',inp,expected_ring,1)
  dispatch('segment',out/'segment.spv',out/'segment-input.bin',final,(len(inputs)+63)//64)
 summary['hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.spv')}
 (out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
