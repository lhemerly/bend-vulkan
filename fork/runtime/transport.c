/* Included after the pinned runtime defines its host types/errors.
 * Child lifetime and a five-second outer bound cover controller + worker failure.
 * argv is passed directly; no shell interpretation, fallback, or GPU auto-selection. */
#include <poll.h>
#include <sys/wait.h>
#include <signal.h>
#include <sys/prctl.h>
static int fork_bind_parent(pid_t expected_parent) {
  return expected_parent <= 0 || getppid() != expected_parent
    || prctl(PR_SET_PDEATHSIG, SIGKILL) != 0 || getppid() != expected_parent;
}
static uint32_t fork_vulkan(uint32_t fid, uint32_t x) {
  const char* config = getenv("BEND_FORK_VULKAN_CONFIG");
  if (!config || !*config) err_fail("fork: Vulkan transport awaits reviewed generated-shader gate/config");
  const pid_t expected_parent = getpid();
  char id[16], input[16], parent_id[16];
  snprintf(id,sizeof id,"%u",fid); snprintf(input,sizeof input,"%u",x);
  snprintf(parent_id,sizeof parent_id,"%ld",(long)expected_parent);
  int channel[2];
  if (pipe(channel)) err_fail("fork: controller pipe failed");
  pid_t child = fork();
  if (child < 0) { close(channel[0]); close(channel[1]); err_fail("fork: controller fork failed"); }
  if (child == 0) {
    if (fork_bind_parent(expected_parent)) _exit(2);
    close(channel[0]);
    if (dup2(channel[1], STDOUT_FILENO) < 0) _exit(2);
    close(channel[1]);
    execl("/usr/bin/python3", "python3", FORK_CONTROLLER, config, id, input,
      FORK_CALLER_SCHEMA, FORK_PLAN_SCHEMA, FORK_PLAN_SHA256,
      FORK_SHADER_SOURCE_SHA256, FORK_SHADER_SHA256, parent_id, (char*)NULL);
    _exit(2);
  }
  close(channel[1]);
  struct pollfd poller = { .fd=channel[0], .events=POLLIN };
  uint8_t bytes[5]; size_t count=0;
  /* Controller output is one little-endian U32. Drain through EOF, including extra-byte detection. */
  struct timespec began, current; clock_gettime(CLOCK_MONOTONIC,&began);
  int failed=0;
  for (;;) {
    clock_gettime(CLOCK_MONOTONIC,&current);
    long elapsed=(current.tv_sec-began.tv_sec)*1000+(current.tv_nsec-began.tv_nsec)/1000000;
    if (elapsed>=5000 || poll(&poller,1,(int)(5000-elapsed))<=0) { failed=1; break; }
    ssize_t n=read(channel[0],bytes+count,sizeof bytes-count);
    if (n==0) break;
    if (n<0 || (count+=(size_t)n)>=sizeof bytes) { failed=1; break; }
  }
  close(channel[0]); int status;
  if (failed) kill(child,SIGKILL);
  /* A child may close stdout before exiting; bounded reap avoids an unbounded wait. */
  for (;;) {
    pid_t got=waitpid(child,&status,WNOHANG);
    if (got==child) break;
    if (got<0) { failed=1; status=0; break; }
    clock_gettime(CLOCK_MONOTONIC,&current);
    if (current.tv_sec-began.tv_sec>=5) { kill(child,SIGKILL); waitpid(child,&status,0); failed=1; break; }
    struct timespec tick={0,1000000}; nanosleep(&tick,NULL);
  }
  if (failed || count!=4 || !WIFEXITED(status) || WEXITSTATUS(status)!=0)
    err_fail("fork: Vulkan controller failed; CPU fallback refused");
  return (uint32_t)bytes[0] | (uint32_t)bytes[1]<<8 | (uint32_t)bytes[2]<<16 | (uint32_t)bytes[3]<<24;
}
