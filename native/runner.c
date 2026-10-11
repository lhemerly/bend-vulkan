// PRIVATE finite-fixture worker: only run through reviewed tools/run_examples.py; NOT a generic shader sandbox.
#define _GNU_SOURCE
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <ctype.h>
#include <errno.h>
#include <linux/nsfs.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <dirent.h>
#include <limits.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/prctl.h>

#define CHECK(x) do{VkResult r_=(x);if(r_!=VK_SUCCESS){fprintf(stderr,"%s: VkResult=%d\n",#x,r_);exit(2);}}while(0)
#define WG 64u
#define MAXW 16384u
#define MAXG 256u
#define CANARY 0x5a17cafeu
#define BUSY 77

static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (double)t.tv_sec+(double)t.tv_nsec/1e9;}

static uint32_t number(const char*s){char*e;unsigned long n=strtoul(s,&e,10);if(!*s||*e||n>UINT32_MAX){fprintf(stderr,"invalid number\n");exit(2);}return (uint32_t)n;}

/* bounded small read; max includes NUL, so 256 => at most 255 bytes of comm */
static int small_read(const char*path,char*buf,int max){int fd=open(path,O_RDONLY);if(fd<0)return -1;ssize_t n=read(fd,buf,(size_t)max-1);close(fd);if(n<0)n=0;buf[n]=0;int l=(int)n;while(l>0&&(buf[l-1]=='\n'||buf[l-1]==' '||buf[l-1]=='\t'||buf[l-1]=='\r'))buf[--l]=0;return l;}

static int read_u64(const char*p,uint64_t*v){char b[64];if(small_read(p,b,64)<=0)return 0;char *end;errno=0;*v=strtoull(b,&end,10);return !errno&&*end==0&&b[0]!='-';}

static uint64_t first_u64(const char*base,const char*const*names,size_t n,int*ok){
 char p[PATH_MAX];uint64_t v=0;*ok=0;
 for(size_t i=0;i<n;i++){snprintf(p,sizeof p,"%s/%s",base,names[i]);if(read_u64(p,&v)){*ok=1;return v;}}
 return 0;}

static VkPhysicalDeviceDrmPropertiesEXT drm_properties(VkPhysicalDevice physical){
 uint32_t count=0;CHECK(vkEnumerateDeviceExtensionProperties(physical,NULL,&count,NULL));
 VkExtensionProperties*ex=calloc(count,sizeof(*ex));if(!ex&&count){fprintf(stderr,"Allocation failed\n");exit(2);}
 CHECK(vkEnumerateDeviceExtensionProperties(physical,NULL,&count,ex));
 int supported=0;for(uint32_t i=0;i<count;i++)if(!strcmp(ex[i].extensionName,VK_EXT_PHYSICAL_DEVICE_DRM_EXTENSION_NAME))supported=1;
 free(ex);
 VkPhysicalDeviceDrmPropertiesEXT drm={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT};
 if(supported){VkPhysicalDeviceProperties2 p={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,.pNext=&drm};vkGetPhysicalDeviceProperties2(physical,&p);}
 return drm;}

static int hardware(VkPhysicalDeviceType t){return t==VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU||t==VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;}

static VkInstance instance_create(void){
 VkApplicationInfo app={.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO,.pApplicationName="Bend2VulkanFiniteRunner",.apiVersion=VK_API_VERSION_1_2};
 VkInstanceCreateInfo ici={.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,.pApplicationInfo=&app};
 VkInstance instance;CHECK(vkCreateInstance(&ici,NULL,&instance));return instance;}

static void features12(VkPhysicalDevice p,int*mm,int*ds){
 VkPhysicalDeviceVulkan12Features v12={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
 VkPhysicalDeviceFeatures2 f2={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2,.pNext=&v12};
 vkGetPhysicalDeviceFeatures2(p,&f2);*mm=v12.vulkanMemoryModel;if(!*mm)*ds=0;else *ds=v12.vulkanMemoryModelDeviceScope;}

/* ---- guards ---- */
static int forbidden(const char *name) {
 char lower[256];size_t n=strlen(name);if(n>=sizeof lower)n=sizeof lower-1;
 for(size_t i=0;i<n;i++){lower[i]=(char)tolower((unsigned char)name[i]);}lower[n]=0;
 const char *patterns[]={"gamescope","wine","play main","battlenet","leira","warframe","minecraft","dota2","eldenring","lutris","heroic"};
 for(size_t i=0;i<sizeof patterns/sizeof *patterns;i++)if(strstr(lower,patterns[i]))return 1;
 return 0;
}
static int game_scan(void){
 DIR*d=opendir("/proc");if(!d)return 1;int hit=0;struct dirent*e;char p[PATH_MAX],b[256];
 while(!hit&&(e=readdir(d))){if(e->d_name[0]<'0'||e->d_name[0]>'9')continue;
  snprintf(p,sizeof p,"/proc/%s/comm",e->d_name);errno=0;
  if(small_read(p,b,sizeof b)<=0){if(errno!=ENOENT&&errno!=ESRCH)hit=1;continue;}
  if(forbidden(b))hit=1;
 }
 closedir(d);return hit;
}

static void host_init_guard(void){
 struct stat ns;char self[64];ssize_t n=readlink("/proc/self",self,sizeof self-1);
 if(stat("/proc/self/ns/pid",&ns)||ns.st_ino!=PID_NS_INIT_INO||n<=0){fprintf(stderr,"initial host PID namespace unavailable; skip\n");exit(BUSY);}
 self[n]=0;char expected[64];snprintf(expected,sizeof expected,"%ld",(long)getpid());
 FILE *mount=fopen("/proc/self/mountinfo","r");if(!mount){fprintf(stderr,"procfs mount visibility unavailable\n");exit(BUSY);}char line[8192];int proc_seen=0;
 while(fgets(line,sizeof line,mount)){char root[256],at[256],opts[512];
  if(sscanf(line,"%*u %*u %*s %255s %255s %511s",root,at,opts)!=3)continue;
  if(!strcmp(at,"/proc")){proc_seen=1;
   char *hide=strstr(line,"hidepid=");
   if(strcmp(root,"/")||!strstr(line," - proc ")||strstr(line,"subset=")||(hide&&(hide[8]!='0'||(hide[9]!=','&&hide[9]!=' '&&hide[9]!='\n'&&hide[9]!=0)))){fclose(mount);fprintf(stderr,"restricted/unknown procfs view; skip\n");exit(BUSY);}
  }
 }fclose(mount);if(!proc_seen){fprintf(stderr,"unobscured procfs mount unavailable\n");exit(BUSY);}
 if(strcmp(self,expected)){fprintf(stderr,"procfs PID view mismatch; skip\n");exit(BUSY);}
}
/* Readable clients require observed canonical executable paths and live file identity.
 * This local finite-test policy is not an adversarial host attestation. */
static int os_graphics(const char *pid,const char *name){
 const struct {const char *name,*exe;} allowed[]={
  {"cosmic-comp","/usr/bin/cosmic-comp"},{"Xwayland","/usr/bin/Xwayland"},
  {"cosmic-panel","/usr/bin/cosmic-panel"},{"cosmic-app-libr","/usr/bin/cosmic-app-library"},
  {"xdg-desktop-por","/usr/lib/xdg-desktop-portal"},
  {"xdg-desktop-por","/usr/lib/xdg-desktop-portal-gtk"},
  {"xdg-desktop-por","/usr/lib/xdg-desktop-portal-cosmic"},
  {"brave","/opt/brave-bin/brave"},{"ChatGPT","/usr/lib/chatgpt/ChatGPT"}};
 char link[PATH_MAX],resolved[PATH_MAX];struct stat live,expected;
 if(snprintf(link,sizeof link,"/proc/%s/exe",pid)>=(int)sizeof link||!realpath(link,resolved)||stat(link,&live))return 0;
 for(size_t i=0;i<sizeof allowed/sizeof *allowed;i++){
  if(strcmp(name,allowed[i].name)||strcmp(resolved,allowed[i].exe)||stat(allowed[i].exe,&expected))continue;
  if(S_ISREG(expected.st_mode)&&expected.st_uid==0&&!(expected.st_mode&(S_IWGRP|S_IWOTH))&&live.st_dev==expected.st_dev&&live.st_ino==expected.st_ino)return 1;
 }
 return 0;
}
static int os_service(const char *name){
 const char *names[]={"systemd","systemd-journal","systemd-userdbd","systemd-resolve","systemd-timesyn","systemd-udevd","systemd-logind","systemd-userwor","dbus-broker-lau","dbus-broker","ananicy-cpp","NetworkManager","avahi-daemon","cosmic-greeter-","dmemcg-booster","tailscaled","(sd-pam)","greetd","lact","power-profiles-","polkitd","upowerd","fusermount3","udisksd","rtkit-daemon"};
 for(size_t i=0;i<sizeof names/sizeof *names;i++){if(!strcmp(name,names[i]))return 1;}return 0;
}
static int selected_clients(uint32_t mj,uint32_t mn){
 DIR *proc=opendir("/proc");if(!proc)return 0;int safe=1;struct dirent *entry;
 while((entry=readdir(proc))){if(entry->d_name[0]<'0'||entry->d_name[0]>'9'||atoi(entry->d_name)==getpid())continue;
  char name[256],path[PATH_MAX];snprintf(path,sizeof path,"/proc/%s/comm",entry->d_name);
  if(small_read(path,name,sizeof name)<=0){if(errno!=ENOENT&&errno!=ESRCH)safe=0;continue;}
  snprintf(path,sizeof path,"/proc/%s/fd",entry->d_name);DIR *fds=opendir(path);
  if(!fds){if(errno==ENOENT||errno==ESRCH)continue;if(errno==EACCES&&os_service(name))continue;
   char statm[256];snprintf(path,sizeof path,"/proc/%s/statm",entry->d_name);
   if(small_read(path,statm,sizeof statm)>0&&strtoull(statm,NULL,10)==0)continue; // kernel thread: no userspace address space.
   fprintf(stderr,"unknown unreadable FD client: pid=%s comm=%s\n",entry->d_name,name);safe=0;continue;
  }
  struct dirent *fd;while((fd=readdir(fds))){if(fd->d_name[0]=='.')continue;struct stat st;
   if(snprintf(path,sizeof path,"/proc/%s/fd/%s",entry->d_name,fd->d_name)>=(int)sizeof path){safe=0;continue;}
   if(stat(path,&st)){if(errno!=ENOENT&&errno!=ESRCH&&!(errno==EACCES&&os_service(name)))safe=0;continue;}
   if(S_ISCHR(st.st_mode)&&major(st.st_rdev)==mj&&minor(st.st_rdev)==mn&&!os_graphics(entry->d_name,name)){
    fprintf(stderr,"unknown/non-OS selected GPU client: pid=%s comm=%s\n",entry->d_name,name);safe=0;break;
   }
  }closedir(fds);
 }closedir(proc);return safe;
}

static long long max_temp(const char*base){
 char d[PATH_MAX];if(snprintf(d,sizeof d,"%s/hwmon",base)>=(int)sizeof d)return -1;DIR*dir=opendir(d);if(!dir)return -1;
 long long m=-1;struct dirent*e;
 while((e=readdir(dir))){if(e->d_name[0]=='.')continue;
  char sub[PATH_MAX];if(snprintf(sub,sizeof sub,"%s/%s",d,e->d_name)>=(int)sizeof sub)continue;
  DIR *hw=opendir(sub);if(!hw)continue;struct dirent *t;
  while((t=readdir(hw))){const char*n=t->d_name;size_t l=strlen(n);
   if(strncmp(n,"temp",4)||l<11||strcmp(n+l-6,"_input"))continue;
   char path[PATH_MAX];if(snprintf(path,sizeof path,"%s/%s",sub,n)>=(int)sizeof path)continue;
   uint64_t v;if(!read_u64(path,&v)||v>200000){m=-1;closedir(hw);closedir(dir);return m;}if((long long)v>m)m=(long long)v;
  }closedir(hw);
 }closedir(dir);return m;
}

static char g_canon[PATH_MAX];

static void guard(uint32_t mj,uint32_t mn,uint32_t vendor,uint32_t product){
 char raw[PATH_MAX],can[PATH_MAX];
 snprintf(raw,sizeof raw,"/sys/dev/char/%u:%u/device",mj,mn);
 if(!realpath(raw,can)){fprintf(stderr,"device sysfs path unavailable\n");exit(2);}
 if(!g_canon[0]||strcmp(g_canon,can)){fprintf(stderr,"device sysfs identity changed\n");exit(2);}
 DIR *nodes=opendir("/dev/dri");if(!nodes){fprintf(stderr,"render nodes unavailable\n");exit(BUSY);}int found=0;struct dirent *node;
 while((node=readdir(nodes))){if(strncmp(node->d_name,"renderD",7))continue;char path[PATH_MAX];struct stat st;
  snprintf(path,sizeof path,"/dev/dri/%s",node->d_name);
  if(!stat(path,&st)&&S_ISCHR(st.st_mode)&&major(st.st_rdev)==mj&&minor(st.st_rdev)==mn)found++;
 }closedir(nodes);if(found!=1){fprintf(stderr,"render node identity ambiguous/unavailable\n");exit(BUSY);}
 const char *ids[]={"vendor","device"};uint32_t wanted[]={vendor,product};
 for(size_t i=0;i<2;i++){char path[PATH_MAX],text[64],*end;
  if(snprintf(path,sizeof path,"%s/%s",can,ids[i])>=(int)sizeof path||small_read(path,text,sizeof text)<=0){fprintf(stderr,"PCI identity unavailable\n");exit(BUSY);}
  errno=0;unsigned long value=strtoul(text,&end,16);if(errno||*end||value!=wanted[i]){fprintf(stderr,"PCI identity changed\n");exit(BUSY);}
 }
 if(!selected_clients(mj,mn)){fprintf(stderr,"unknown selected-device workload/visibility; skip\n");exit(BUSY);}
 if(game_scan()){fprintf(stderr,"guard: forbidden process present\n");exit(BUSY);}
 int ok;uint64_t busy=first_u64(g_canon,(const char*const[]){"gpu_busy_percent","gt_busy_percent","busy_percent"},3,&ok);
 if(!ok){fprintf(stderr,"guard: busy telemetry missing\n");exit(BUSY);}
 uint64_t used=first_u64(g_canon,(const char*const[]){"mem_info_vram_used","mem_info_vram_used_bytes"},2,&ok);
 if(!ok){fprintf(stderr,"guard: vram used telemetry missing\n");exit(BUSY);}
 uint64_t total=first_u64(g_canon,(const char*const[]){"mem_info_vram_total","mem_info_vram_total_bytes"},2,&ok);
 if(!ok||!total){fprintf(stderr,"guard: vram total telemetry missing\n");exit(BUSY);}
 long long t=max_temp(g_canon);
 if(t<=0){fprintf(stderr,"guard: temperature telemetry missing\n");exit(BUSY);}
 if(busy>20){fprintf(stderr,"guard: gpu busy %llu%%\n",(unsigned long long)busy);exit(BUSY);}
 if((double)used/(double)total>0.80){fprintf(stderr,"guard: vram %llu/%llu\n",(unsigned long long)used,(unsigned long long)total);exit(BUSY);}
 if(t>65000){fprintf(stderr,"guard: temperature %lld mC\n",t);exit(BUSY);}}

static int probe_inventory(void){
 VkInstance instance=instance_create();uint32_t count=0;
 CHECK(vkEnumeratePhysicalDevices(instance,&count,NULL));
 if(!count||count>32){fprintf(stderr,"no bounded device inventory\n");vkDestroyInstance(instance,NULL);return 2;}
 VkPhysicalDevice list[32];CHECK(vkEnumeratePhysicalDevices(instance,&count,list));
 for(uint32_t i=0;i<count;i++){
  VkPhysicalDeviceProperties p;vkGetPhysicalDeviceProperties(list[i],&p);
  VkPhysicalDeviceDrmPropertiesEXT d=drm_properties(list[i]);
  int mm,ds;features12(list[i],&mm,&ds);
  int ok=hardware(p.deviceType)&&d.hasRender&&p.apiVersion>=VK_API_VERSION_1_2&&p.limits.maxComputeWorkGroupInvocations>=WG;
  printf("%u\t%s\t%u\t%u\t%u\t%llu\t%llu\t%u\t%u\t%u\t%u\t%s\n",i,ok?"hardware":"rejected",
   p.deviceType,p.vendorID,p.deviceID,(unsigned long long)d.renderMajor,(unsigned long long)d.renderMinor,
   p.apiVersion,p.limits.maxComputeWorkGroupInvocations,mm?1u:0u,ds?1u:0u,p.deviceName);}
 printf("api_target=1.2 devices=%u\n",count);
 vkDestroyInstance(instance,NULL);return 0;}

#include "pair_spv.h"

int main(int argc,char**argv){
 if(argc==2&&!strcmp(argv[1],"--probe-inventory"))return probe_inventory();
 if(argc==4&&!strcmp(argv[1],"--guard-client-check")){host_init_guard();if(!selected_clients(number(argv[2]),number(argv[3])))return BUSY;puts("read-only executable/client guard passed; no GPU dispatch");return 0;}
 if(argc==2&&!strcmp(argv[1],"--guard-selftest")){
  const char *bad[]={"gamescope-wl","Play Main Threa","wineserver","BATTLenet.overl","leira","wine64","wine-preloader","Warframe.x64","minecraft"};
  for(size_t i=0;i<sizeof bad/sizeof *bad;i++)if(!forbidden(bad[i]))return 2;
  if(forbidden("bend-vulkan-runner")||forbidden("systemd"))return 2;
  char pid[32];snprintf(pid,sizeof pid,"%ld",(long)getpid());if(os_graphics(pid,"brave"))return 2;
  puts("guard process matcher and wrong-executable rejection tests passed");return 0;
 }
 if(argc!=12){fprintf(stderr,"runner SHADER INPUT OUTPUT WORDS GROUPS DEVICE RENDER_MAJOR RENDER_MINOR VENDOR PRODUCT CANONICAL_PCI_PATH\n");return 2;}

 uint32_t words=number(argv[4]),groups=number(argv[5]),index=number(argv[6]);
 uint32_t major_=number(argv[7]),minor_=number(argv[8]),vendor=number(argv[9]),product=number(argv[10]);
 if(strlen(argv[11])>=sizeof g_canon||strncmp(argv[11],"/sys/devices/",13)){fprintf(stderr,"canonical PCI path required\n");return 2;}strcpy(g_canon,argv[11]);
 if(!words||words>MAXW||!groups||groups>MAXG){fprintf(stderr,"Bounds rejected: words 1..%u groups 1..%u\n",MAXW,MAXG);return 2;}

 /* direct native worker: die with controller, guard the fork race */
 pid_t parent=getppid();
 if(prctl(PR_SET_PDEATHSIG,SIGKILL)!=0||getppid()!=parent||parent==1){fprintf(stderr,"controller lifetime binding failed\n");return 2;}

 /* sandbox pid namespace must not be trusted */
 host_init_guard();

 /* shader: bounded SPIR-V with magic/version sanity */
 FILE*f=fopen(argv[1],"rb");if(!f){perror("shader");return 2;}
 fseek(f,0,SEEK_END);long length=ftell(f);rewind(f);
 if(length<20||length%4||length>4*1024*1024){fprintf(stderr,"invalid SPIR-V file size\n");fclose(f);return 2;}
 uint32_t*code=malloc((size_t)length);
 if(!code||fread(code,1,(size_t)length,f)!=(size_t)length){fprintf(stderr,"shader read failed\n");fclose(f);return 2;}
 fclose(f);
 if(code[0]!=0x07230203u){fprintf(stderr,"not a SPIR-V module\n");return 2;}
 if((code[1]>>16)!=1u||((code[1]>>8)&255u)>5u||(code[1]&255u)!=0u){fprintf(stderr,"unsupported SPIR-V version\n");return 2;}

 uint32_t local_x=0,local_y=0,local_z=0;int needs_mm=0,needs_ds=0;
 for(size_t at=5;at<(size_t)length/4;){uint32_t n=code[at]>>16,op=code[at]&65535u;if(!n||at+n>(size_t)length/4){fprintf(stderr,"malformed SPIR-V\n");return 2;}
  if(op==16u&&n==6u&&code[at+2]==17u){if(local_x){fprintf(stderr,"multiple local sizes\n");return 2;}local_x=code[at+3];local_y=code[at+4];local_z=code[at+5];}
  if(op==17u&&n==2u){if(code[at+1]==5345u)needs_mm=1;if(code[at+1]==5346u)needs_ds=1;}
  at+=n;
 }
 if((local_x!=1u&&local_x!=64u&&local_x!=128u)||local_y!=1u||local_z!=1u||(local_x==1u&&(words!=30u||groups!=1u))||(local_x==128u&&((words!=44u&&words!=48u)||groups!=1u))){fprintf(stderr,"unsupported bounded shader shape/ABI\n");return 2;}
 if(words==48u){
  if(local_x!=128u||groups!=1u||(size_t)length!=sizeof reviewed_pair_spv||memcmp(code,reviewed_pair_spv,sizeof reviewed_pair_spv)){fprintf(stderr,"pair ABI requires exact frozen reviewed SPIR-V, one128-thread group\n");return 2;}
 }
 /* input: exactly WORDS*4 bytes, no short read, no extra data */
 struct stat ist;
 if(stat(argv[2],&ist)||!S_ISREG(ist.st_mode)||ist.st_size!=(off_t)words*4u){
  fprintf(stderr,"input must be exactly %llu bytes\n",(unsigned long long)words*4ull);return 2;}
 uint32_t*initial=malloc((size_t)words*4u);if(!initial){fprintf(stderr,"Allocation failed\n");return 2;}
 f=fopen(argv[2],"rb");if(!f){perror("input");return 2;}
 if(fread(initial,1,(size_t)words*4u,f)!=(size_t)words*4u){fprintf(stderr,"input short read\n");fclose(f);return 2;}
 fclose(f);

 VkInstance instance=instance_create();
 uint32_t devices=0;CHECK(vkEnumeratePhysicalDevices(instance,&devices,NULL));
 if(!devices||devices>32||index>=devices){fprintf(stderr,"device index unavailable\n");return 2;}
 VkPhysicalDevice physicals[32];CHECK(vkEnumeratePhysicalDevices(instance,&devices,physicals));
 VkPhysicalDevice physical=physicals[index];
 VkPhysicalDeviceProperties props;vkGetPhysicalDeviceProperties(physical,&props);
 VkPhysicalDeviceDrmPropertiesEXT drm=drm_properties(physical);
 if(!hardware(props.deviceType)||props.vendorID!=vendor||props.deviceID!=product||!drm.hasRender||
    drm.renderMajor!=major_||drm.renderMinor!=minor_){
  fprintf(stderr,"selected Vulkan hardware no longer matches guarded DRM render node\n");return 2;}
 if(props.apiVersion<VK_API_VERSION_1_2){fprintf(stderr,"Vulkan 1.2 required\n");return 2;}
 /* Private finite fixtures declare their local size; validate against device limits. */
 if(local_x>props.limits.maxComputeWorkGroupInvocations||local_x>props.limits.maxComputeWorkGroupSize[0]||groups>props.limits.maxComputeWorkGroupCount[0]){
  fprintf(stderr,"workgroup size or dispatch group bound unsupported\n");return 2;}

 if(local_x==128u){
  VkPhysicalDeviceSubgroupProperties sub={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_PROPERTIES};
  VkPhysicalDeviceProperties2 p2={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2,.pNext=&sub};
  vkGetPhysicalDeviceProperties2(physical,&p2);
  if(!(sub.supportedStages&VK_SHADER_STAGE_COMPUTE_BIT)||!(sub.supportedOperations&VK_SUBGROUP_FEATURE_BASIC_BIT)||!sub.subgroupSize||sub.subgroupSize>64u){fprintf(stderr,"two compute subgroups with BASIC support required\n");return 2;}
 }
 /* native guard pass one, before any dispatch work */
 guard(drm.renderMajor,drm.renderMinor,vendor,product);
 if(getppid()!=parent){fprintf(stderr,"parent race detected\n");return 2;}

 int mm,ds;features12(physical,&mm,&ds);

 uint32_t families=0;vkGetPhysicalDeviceQueueFamilyProperties(physical,&families,NULL);
 VkQueueFamilyProperties*qprops=calloc(families,sizeof(*qprops));if(!qprops&&families){fprintf(stderr,"Allocation failed\n");return 2;}
 vkGetPhysicalDeviceQueueFamilyProperties(physical,&families,qprops);
 uint32_t family=UINT32_MAX;
 for(uint32_t i=0;i<families;i++)if(qprops[i].queueFlags&VK_QUEUE_COMPUTE_BIT){family=i;break;}
 free(qprops);
 if(family==UINT32_MAX){fprintf(stderr,"compute queue family required\n");return 2;}

 float priority=0.2f;
 VkDeviceQueueCreateInfo qci={.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,.queueFamilyIndex=family,.queueCount=1,.pQueuePriorities=&priority};
 if((needs_mm&&!mm)||(needs_ds&&!ds)){fprintf(stderr,"required Vulkan memory-model feature unavailable\n");return 2;}
 VkPhysicalDeviceVulkan12Features enabled={.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES,.vulkanMemoryModel=needs_mm,.vulkanMemoryModelDeviceScope=needs_ds};
 VkDeviceCreateInfo dci={.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,.queueCreateInfoCount=1,.pQueueCreateInfos=&qci,.pNext=&enabled};
 VkDevice device;CHECK(vkCreateDevice(physical,&dci,NULL,&device));
 VkQueue queue;vkGetDeviceQueue(device,family,0,&queue);

 /* logical words plus 4 sentinel canary words; descriptor covers the whole allocation */
 VkDeviceSize size=(VkDeviceSize)(words+4u)*4u;
 VkBufferCreateInfo bci={.sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,.size=size,
  .usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,.sharingMode=VK_SHARING_MODE_EXCLUSIVE};
 VkBuffer buffer;CHECK(vkCreateBuffer(device,&bci,NULL,&buffer));
 VkMemoryRequirements req;vkGetBufferMemoryRequirements(device,buffer,&req);
 VkPhysicalDeviceMemoryProperties mp;vkGetPhysicalDeviceMemoryProperties(physical,&mp);
 uint32_t memtype=UINT32_MAX;
 for(uint32_t i=0;i<mp.memoryTypeCount;i++)if((req.memoryTypeBits&(1u<<i))&&
   (mp.memoryTypes[i].propertyFlags&(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))==
   (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)){memtype=i;break;}
 if(memtype==UINT32_MAX){fprintf(stderr,"host-visible coherent memory required\n");return 2;}
 VkMemoryAllocateInfo mai={.sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,.allocationSize=req.size,.memoryTypeIndex=memtype};
 VkDeviceMemory memory;CHECK(vkAllocateMemory(device,&mai,NULL,&memory));
 CHECK(vkBindBufferMemory(device,buffer,memory,0));
 void*mapped=NULL;CHECK(vkMapMemory(device,memory,0,size,0,&mapped));
 memset(mapped,0,(size_t)size);
 uint32_t*words_view=mapped;memcpy(words_view,initial,(size_t)words*4u);free(initial);
 for(uint32_t i=0;i<4u;i++)words_view[words+i]=CANARY;

 VkDescriptorSetLayoutBinding binding={.binding=0,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
  .descriptorCount=1,.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT};
 VkDescriptorSetLayoutCreateInfo slci={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
  .bindingCount=1,.pBindings=&binding};
 VkDescriptorSetLayout setlayout;CHECK(vkCreateDescriptorSetLayout(device,&slci,NULL,&setlayout));
 VkDescriptorPoolSize ps={.type=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.descriptorCount=1};
 VkDescriptorPoolCreateInfo dpci={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,.maxSets=1,.poolSizeCount=1,.pPoolSizes=&ps};
 VkDescriptorPool pool;CHECK(vkCreateDescriptorPool(device,&dpci,NULL,&pool));
 VkDescriptorSetAllocateInfo dsai={.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,.descriptorPool=pool,.descriptorSetCount=1,.pSetLayouts=&setlayout};
 VkDescriptorSet set;CHECK(vkAllocateDescriptorSets(device,&dsai,&set));
 VkDescriptorBufferInfo dbi={.buffer=buffer,.range=size}; /* whole allocation: canary writes are visible */
 VkWriteDescriptorSet w={.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,.dstSet=set,.dstBinding=0,
  .descriptorCount=1,.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,.pBufferInfo=&dbi};
 vkUpdateDescriptorSets(device,1,&w,0,NULL);

 VkPipelineLayoutCreateInfo plci={.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
  .setLayoutCount=1,.pSetLayouts=&setlayout}; /* no push constants */
 VkPipelineLayout layout;CHECK(vkCreatePipelineLayout(device,&plci,NULL,&layout));
 VkShaderModuleCreateInfo smci={.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,.codeSize=(size_t)length,.pCode=code};
 VkShaderModule shader;CHECK(vkCreateShaderModule(device,&smci,NULL,&shader));free(code);
 VkComputePipelineCreateInfo cpci={.sType=VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,
  .stage={.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,.stage=VK_SHADER_STAGE_COMPUTE_BIT,
   .module=shader,.pName="main"},.layout=layout};
 VkPipeline pipeline;CHECK(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&cpci,NULL,&pipeline));

 VkCommandPoolCreateInfo pci={.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
  .flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,.queueFamilyIndex=family};
 VkCommandPool commandpool;CHECK(vkCreateCommandPool(device,&pci,NULL,&commandpool));
 VkCommandBufferAllocateInfo cbai={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
  .commandPool=commandpool,.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY,.commandBufferCount=1};
 VkCommandBuffer cmd;CHECK(vkAllocateCommandBuffers(device,&cbai,&cmd));
 VkFenceCreateInfo fci={.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
 VkFence fence;CHECK(vkCreateFence(device,&fci,NULL,&fence));

 VkCommandBufferBeginInfo begin={.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
  .flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
 CHECK(vkBeginCommandBuffer(cmd,&begin));
 vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,pipeline);
 vkCmdBindDescriptorSets(cmd,VK_PIPELINE_BIND_POINT_COMPUTE,layout,0,1,&set,0,NULL);
 VkMemoryBarrier pre={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_HOST_WRITE_BIT,
  .dstAccessMask=VK_ACCESS_SHADER_READ_BIT|VK_ACCESS_SHADER_WRITE_BIT};
 vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_HOST_BIT,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,0,1,&pre,0,NULL,0,NULL);
 vkCmdDispatch(cmd,groups,1,1); /* single finite dispatch, no repeats */
 VkMemoryBarrier post={.sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER,.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT,
  .dstAccessMask=VK_ACCESS_HOST_READ_BIT};
 vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&post,0,NULL,0,NULL);
 CHECK(vkEndCommandBuffer(cmd));

 /* guard again immediately before submit; identity must be stable, no fallback */
 guard(drm.renderMajor,drm.renderMinor,vendor,product);
 if(getppid()!=parent){fprintf(stderr,"parent race detected\n");return 2;}

 VkSubmitInfo submit={.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,.commandBufferCount=1,.pCommandBuffers=&cmd};
 double t0=now();CHECK(vkQueueSubmit(queue,1,&submit,fence));
 VkResult waited=vkWaitForFences(device,1,&fence,VK_TRUE,1000000000ULL);
 double elapsed=now()-t0;
 if(waited!=VK_SUCCESS){fprintf(stderr,"fence wait: VkResult=%d\n",waited);return 2;}

 for(uint32_t i=0;i<4u;i++)if(words_view[words+i]!=CANARY){
  fprintf(stderr,"canary violation at sentinel %u\n",i);return 2;}

 f=fopen(argv[3],"wb");if(!f){perror("output");return 2;}
 if(fwrite(words_view,1,(size_t)words*4u,f)!=(size_t)words*4u){fprintf(stderr,"output write failed\n");fclose(f);return 2;}
 fclose(f);

 printf("device=%s\nvulkan_index=%u\nrender_major=%u\nrender_minor=%u\nvendor_id=%u\ndevice_id=%u\n"
  "driver_version=%u\napi_version=%u\nwords=%u\ngroups=%u\nworkgroup=%u\ncanaries=%u\n"
  "vulkan_memory_model=%s\nvulkan_memory_model_device_scope=%s\nsubmit_wait_ms=%.6f\ncanaries_intact=1\n",
  props.deviceName,index,major_,minor_,props.vendorID,props.deviceID,props.driverVersion,props.apiVersion,
  words,groups,local_x,4u,needs_mm?"enabled":"not-required",needs_ds?"enabled":"not-required",elapsed*1000.0);

 vkUnmapMemory(device,memory);vkDestroyFence(device,fence,NULL);vkDestroyCommandPool(device,commandpool,NULL);
 vkDestroyPipeline(device,pipeline,NULL);vkDestroyShaderModule(device,shader,NULL);
 vkDestroyPipelineLayout(device,layout,NULL);vkDestroyDescriptorPool(device,pool,NULL);
 vkDestroyDescriptorSetLayout(device,setlayout,NULL);vkDestroyBuffer(device,buffer,NULL);
 vkFreeMemory(device,memory,NULL);vkDestroyDevice(device,NULL);vkDestroyInstance(instance,NULL);
 return 0;}
