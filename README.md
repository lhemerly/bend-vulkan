# Bend Vulkan

A general Vulkan compute backend for the pinned Bend2 compiler
[`11d483271b46e445b922756d5fd4127a1ea99ae8`](https://github.com/bendlang/bend/tree/11d483271b46e445b922756d5fd4127a1ea99ae8).
The `bend-vulkan` command compiles checked Bend programs to a native host executable
and a SPIR-V device program. It uses Bend's general heap, closures, constructors,
arrays, reference counting, continuations, and parallel task scheduler.

This remains an independent experimental backend. The older depth-five U32/Nat/F32
experiments are retained for regression testing and historical evidence; the new
command does not use their bounded plan schemas or private admission tooling.

## Build and run

Linux dependencies: Python 3.10+, Bun 1.4.2, Clang, glslangValidator, spirv-val,
and the Vulkan development headers and loader. `CC` can select Clang explicitly.
The GPU needs Vulkan 1.2, `shaderInt64`, and the Vulkan memory model with device
scope. Host window/audio effects also need their upstream X11/ALSA development
libraries.

```sh
./bend-vulkan doctor                  # inspect required tools; no compiler or GPU work
./bend-vulkan devices
./bend-vulkan build evidence/upstream/tests/run/gpu_trig.bend -o build/trig
./bend-vulkan run build/trig --device 0 --trace
# Prints 78542; trace reports the device, memory path and actual dispatch count.

./bend-vulkan run fork/tests/general/deep_parallel.bend --device 0
# Prints 12288, from 4096 parallel leaves at depth 12.

./bend-vulkan run build/trig --backend cpu
./bend-vulkan build fork/tests/general/closure_input.bend -o build/cpu --backend cpu
./bend-vulkan run build/cpu
```

Build output must be a new directory. Builds are staged beside the destination and
published only after every compiler and validator succeeds, so a failed build
cannot leave a partial bundle behind. `run` also accepts a source file and builds
it in a temporary directory. Pass application arguments after `--`. Vulkan
execution is explicit; CPU-only builds reject a request to run on Vulkan. The
launcher verifies the recorded build artifacts before execution. Keep `program`
and `program.gpu` together when running the executable directly. `--version` and
`doctor --json` are available for automation.

Use `--software` to explicitly permit a software Vulkan device such as Mesa
lavapipe. Its driver may be selected with `VK_ICD_FILENAMES`. Software execution
is reported with its actual device name, and is not hardware performance evidence.

`--threads` controls host workers. `--cube-log` at build time selects 2^N device
workgroups of 128 lanes (default N=4). `--memory 256MB` selects the GPU heap within
`maxStorageBufferRange`; the default accounts for the selected scheduler geometry.
`--timeout` bounds execution in seconds (default 300). Large generated shaders can
be slow on software Vulkan.

The device heap uses device-local host-visible memory when the Vulkan memory type
offers it. Otherwise the host uses a mapped host-visible staging buffer and copies
the corpus around each command buffer, so the backend does not require resizable
BAR. The `--staging` diagnostic flag forces that path on a Vulkan build; the trace
reports `memory=staged` or `memory=host-visible`.

## Runtime boundaries

Bend's `!` calls enter the device through the pinned host scheduler. I/O and foreign
effects stay on the host. This preserves the upstream routing behavior, including
its treatment of marked calls inside CPU-owned parallel work. The checker and
prelude are unchanged. GPU text conversion of F32 values retains the upstream
host-only restriction; perform formatting/parsing outside a device call.

The general backend has no depth-five or 63-task plan restriction. Heap capacity,
stack depth, ring capacity, and the pinned 48-bit Nat representation still impose
runtime limits and produce explicit errors. Transcendental operations use device
math and are not promised to be bit-identical to every CPU libm. Arithmetic is
emitted with separate F32 rounding, and the suite checks special values, signed
zero, non-contraction, remainder, and power edge cases.

## Verification

```sh
cargo test --offline
cargo clippy --offline --all-targets -- -D warnings
python3 tools/test_emit_u32_segment.py
python3 tools/test_general_cli.py
python3 fork/tests/check_general.py /tmp/bend-cpu-new --cpu-only
python3 fork/tests/check_general.py /tmp/bend-vulkan-new --device 0
python3 fork/tests/check_general.py /tmp/bend-staging --device 0 \
  --staging --case array_fork --case deep_parallel
# For a software device, add --software.
```

The general gate regenerates each fixture, compares default C byte-for-byte with
the pinned compiler, validates SPIR-V, and compares upstream CPU, adapted CPU,
and actual Vulkan results at one and two host threads. Successful GPU cases must
show real dispatches. Expected runtime failures have explicit exit/output contracts.
Fixtures include shared arrays/atomics, closures, ADTs, strings, maps, numeric
edge cases, deep parallel recursion, result loops, a 3D stencil, and host/device
handoffs. Imported fixtures are attributed in `fork/tests/general/PROVENANCE.json`.

All 58 general cases passed on an AMD Radeon RX 6600 XT in both host thread modes.
The host-visible staging path also passed `array_fork`, `deep_parallel`,
`stencil3d`, `fork_leaf_result_loop`, and `nat_overflow` on that device. In the
earlier 56-case run, software Vulkan passed 55 cases; `map_set_ops` exceeded its
300-second software deadline and passed on hardware. All 12 CLI regression tests
pass. The machine-readable record is
[GENERAL-VALIDATION.json](evidence/GENERAL-VALIDATION.json). CI runs all new
CPU/source contracts and a representative lavapipe device suite, including the
staging path. See [architecture and validation limits](ARCHITECTURE.md).
Historical summaries in `evidence/CPU-SUMMARY.json` and
`evidence/GPU-DEVICE-SUMMARY.json` describe the old research snapshot; their
counts are not results of this general backend.

## Source map

- `evidence/upstream/`: unchanged pinned checker, compiler, prelude, and effects.
- `fork/compiler/capture.ts`: shared checked compiler; F32 compatibility wrapper in `capture_f32.ts`.
- `tools/c_to_glsl.py`: typed Clang AST lowering of the compiler's device C.
- `fork/runtime/general.comp`: Vulkan memory operations and numeric support.
- `fork/runtime/vulkan_host.c`: device selection, memory path, pipelines, dispatch, and synchronization.
- `tools/bend_vulkan.py`, `bend-vulkan`: public build/run CLI.
- `fork/tests/general/`, `fork/tests/check_general.py`: portable compatibility gate.
- Other `fork/`, `src/`, `shaders/`, and `tools/` files: earlier bounded backend and research tools.

Apache-2.0; preserve [NOTICE](NOTICE) and [upstream license](LICENSE.upstream).
Private historical logs, machine grants, and orchestration records are not part
of this repository and are not dependencies of the general backend.
