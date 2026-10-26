# General Vulkan backend

The public build path uses the unchanged Bend2 2.0.39 checker, compiler, prelude,
and effects in `evidence/upstream/` at commit `295e996`. `fork/general_cli.ts`
calls that upstream `compile_book` directly, so ordinary compilation does not
depend on a fork-specific compiler copy. The gate compares the resulting C with an
independent `fork/upstream_compile.ts` invocation of the same upstream compiler.
The historical `fork/compiler/capture.ts` metadata compiler belongs to the old
bounded experiments and is not part of this path.

`tools/c_to_glsl.py` extracts the device half of the compiler's C runtime and asks
Clang for its typed AST. It lowers device pointers to byte offsets into the shared
corpus, private pointer parameters to GLSL `inout` parameters, C conversions to
explicit GLSL conversions, and the kernel entry to Vulkan builtins/push constants.
It understands the current compact `Fid`/`Cid` tables, enum error codes, and device
address spaces. Unknown AST forms fail compilation. This is a lowering of a pinned
compiler's output, not a general-purpose C-to-GLSL compiler.

The original work loop and segment switch remain the execution model. Heap banks,
reference counts, arrays, closures, task/continuation delivery, and the grow,
drain, and bank-compaction passes come from the same runtime as the CPU compiler.
The compiler's FID/CID tables and static image retain their identities. The 2.0.39
scheduler writes each turn's five dispatch group counts into `H_GROUPS`; the Vulkan
host reads those counts and submits only the nonzero dispatches. Host and device
scheduler geometry are generated together; their shared stack/ring offsets must
match. The default uses 16 workgroups and 1024 entries per ring. Runtime capacity
errors remain fail-stop errors, without a hidden CPU retry.

The runtime owns one `VkPhysicalDevice`, one `VkDevice`, one compute queue, and one
pipeline per process. `--device N` selects that one device from the inventory; it
does not schedule across multiple GPUs or use peer memory. Multi-GPU execution is
outside the current release scope.

`fork/runtime/general.comp` supplies 32-bit atomics, device/workgroup memory
semantics, and F32 support. Two storage-buffer views of one allocation expose
64-bit terms and 32-bit atomic cells. The views are not `restrict`-qualified.
Publication uses acquire/release operations and explicit memory barriers.
Subtraction atomics, compare/exchange, floating add, and shared-memory voting
preserve the runtime contracts. Arithmetic helpers use `precise` intermediates to
prevent contraction. F32 remainder uses significand division and power handles
IEEE special cases before calling device math.

`fork/runtime/vulkan_host.c` selects a Vulkan 1.2 compute device and checks its
integer, memory-model, workgroup, shared-memory, and storage-buffer capabilities.
When a host-visible device-local memory type exists, the host and device share one
mapped allocation. Otherwise the backend allocates the corpus in device-local
memory and a mapped host-visible staging buffer, then copies the corpus before and
after each command buffer. `BEND_VULKAN_FORCE_STAGING=1` (CLI `--staging`) forces
the staging path for diagnostics; the trace reports `memory=staged` or
`memory=host-visible`. Noncoherent host-visible memory is supported through
flush/invalidate calls. Host-to-compute, transfer, inter-dispatch, and
compute-to-host barriers plus a completed fence transfer ownership. Each corpus
turn records the upstream grow/drain/compaction passes in one command buffer.
CPU I/O resumes only after that turn completes. A fence deadline fails the process;
it does not claim that terminating a host process can cancel a stuck GPU kernel.

The CLI builds in a private sibling directory and publishes the bundle atomically
only after the compiler, translator, and SPIR-V validators succeed. It records the
artifact hashes, build version, and cube geometry, then rejects modified artifacts,
unsafe paths, and a conflicting `--cube-log` before running. `doctor` inspects
prerequisites without compiling or dispatching. CPU builds need no Vulkan headers
or shader tools. Vulkan builds can also run their CPU lane explicitly. Software
devices require explicit opt-in and retain their device identity in diagnostics.

## Validation and scope

The canonical gate is `fork/tests/check_general.py`. It compares independent
upstream CPU compilation, the upstream compiler's default C, adapted CPU execution,
and actual Vulkan execution. Both one- and two-thread host modes are checked,
including expected failures. Device execution evidence is required, so a CPU-only
run cannot satisfy a GPU case. The 59 general fixtures cover inputs and result types
outside the old U32/Nat/F32 plans, and include 4096-leaf recursion, shared atomic
arrays, result loops, and a 3D stencil. The gate also runs a representative subset
with `--staging` to exercise the host-visible copy path. The separate CLI regression
suite covers atomic publication after failed builds, artifact integrity, manifest
and cube-geometry rejection, version/doctor output, staging rejection for CPU
builds, and program-argument isolation from runtime flags.

The latest upstream `tests/run` snapshot at this pin has 104 fixtures. The 94 that
compile to native executables all match their expected output, including the
`F32.hypot` GPU case and the fixed-point F32 text fixture; the remaining 10 are
negative checker/compiler-diagnostic fixtures. Eight fixtures are GPU-marked, and
all eight pass on the validated Vulkan device.

This implementation targets the pinned compiler's general GPU runtime. It retains
upstream semantics and restrictions: effects and F32 text conversion are host-side,
marked work inside CPU-owned parallel evaluation follows upstream routing, and
heap/stack/ring limits remain finite. Device transcendental rounding may differ
from libm. It is not a claim that every upstream test is a device program, that all
GPU vendors/drivers have been validated, that multiple GPUs are supported, or that
performance is competitive.

The old bounded emitters/controllers and their negative/lifetime tests remain
available. Their source-bound admission experiments and historical CPU ledgers
are separate from the general backend. No old admission config is enabled or
reused. Historical evidence counts remain historical and must not be combined
with current general-runtime test counts.
