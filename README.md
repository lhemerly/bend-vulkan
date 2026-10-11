# Bend Vulkan (experimental)

An independent experimental Vulkan backend for the pinned Bend2 compiler at
[`11d483271b46e445b922756d5fd4127a1ea99ae8`](https://github.com/bendlang/bend/tree/11d483271b46e445b922756d5fd4127a1ea99ae8).
This is the Bend language/runtime project, not an unrelated TypeScript application.
It is not an upstream-supported backend or a complete compatibility release.

## Source map

- `evidence/upstream/`: unchanged pinned checker, compiler, prelude and effects.
- `fork/compiler/`: checked capture, typed U32/Nat/F32 plans, routing and GLSL emission.
- `fork/runtime/`: CPU reference, host continuation bridges, bounded controllers and worker preparation.
- `fork/tests/`: source fixtures and focused protocol, lifetime and rejection checks.
- `src/`, `shaders/`, `native/`: original Rust primitive reference, finite shaders and native runner.
- `tools/`: development and historical CPU ledger helpers. These are research tooling, not a unified public CLI.

## CPU checks

Requires Linux, Python 3, Rust/Cargo, Bun and Clang. Shader preparation also needs
glslangValidator, spirv-val and Vulkan development headers/loader. No third-party
Rust dependencies are required. Tool versions are not locked across this research snapshot.

The canonical local and CI commands are the repository CLI and its regression
suite. CI (`.github/workflows/cpu.yml`) runs `check` and the CLI tests on
`ubuntu-latest` after checkout, with read-only `contents` permission:

```sh
python3 tools/bend_vulkan.py check        # local + CI: cargo test, warnings-denied clippy, emit-u32 tests
python3 tools/bend_vulkan.py check --f32  # local only: the above plus the F32 CPU parity end-to-end check
python3 tools/test_bend_vulkan_cli.py     # local + CI: CLI regression suite
```

`check` runs the following offline Rust checks and emitter test in the same order;
they can still be run individually without the CLI:

```sh
CARGO_BUILD_JOBS=1 cargo test --offline
CARGO_BUILD_JOBS=1 cargo clippy --offline --all-targets -- -D warnings
python3 tools/test_emit_u32_segment.py
python3 fork/tests/check_f32_e2e.py evidence/upstream/tests/run/gpu_trig.bend /tmp/bend-f32-new-output
```

The last output directory must not exist. It regenerates C, compares ordinary
compiler bytes, builds both executables, and checks upstream and CPU-reference
results at one and two threads. It does not dispatch Vulkan. Generated GPU
configuration must be regenerated after relocation and remains non-admitted by default.

These commands are CPU-only verification. A green local run or CI job proves only
that the CPU Rust checks, emitter test and (for `--f32`) the F32 CPU parity check
passed; it is not GPU/Vulkan execution, performance or full-language coverage
evidence, and it never claims backend completion.

### Portable CPU CLI

`tools/bend_vulkan.py` is a Python 3 standard-library entry point that runs the
existing CPU checks sequentially from the repository root, independent of the
caller's working directory. It is CPU-only: it never dispatches Vulkan and a
passing run never claims backend completion.

```sh
python3 tools/bend_vulkan.py check           # cargo test, warnings-denied clippy, emit-u32 tests
python3 tools/bend_vulkan.py check --f32     # the above, then the F32 CPU parity end-to-end check
python3 tools/bend_vulkan.py doctor          # human report: are cargo, bun and clang on PATH?
python3 tools/bend_vulkan.py doctor --json   # same, as valid JSON on stdout
```

`check` requires `cargo` on `PATH`; `check --f32` additionally requires `bun` and
`clang`. The F32 check runs `fork/tests/check_f32_e2e.py` against
`evidence/upstream/tests/run/gpu_trig.bend` with a fresh temporary output
directory that does not exist before the script creates it, and removes that
temporary output afterwards. Python checks run through `sys.executable`. A
missing prerequisite, nonzero command exit or timeout stops the run immediately
with a nonzero status; per-command timeouts default to 600s (`--timeout`).
`tools/test_bend_vulkan_cli.py` is a focused subprocess test suite for this CLI.

`doctor` only inspects `PATH` (via `shutil.which`): it never executes a compiler
and never performs GPU work, so it is safe to run from any working directory.
The human report lists each required tool with its resolved path or an
actionable install hint, plus the CPU-only scope. With `--json`, stdout is a
single valid JSON document containing `cpu_only: true`, `gpu_dispatches: 0`,
and a `tools` mapping of `cargo`, `bun` and `clang` to
`{"available": bool, "path": string|null}` (plus `ok` and `missing`). The exit
status is `0` only when all required tools are on `PATH`, and the JSON stays
valid even when prerequisites are missing; those failures are reported on
stderr only in human mode.

## Evidence and limitations

Historical RX 6600 XT `gpu_trig` runs passed four bounded calls, printed `78542`,
and validated all 772 device words per call. This is finite correctness evidence,
not performance, general scheduling or full-language GPU coverage.
Historical CPU reconciliation reports 1,490 accepted contracts, including 639
compiled CPU/default-C parity passes; 190 obligations remain (21 pending and
169 requiring safety review). Checker-only and expected-negative contracts are
included in the accepted total. These numbers are not 1,490 GPU tests.
See the sanitized summaries under `evidence/` and [architecture assessment](ARCHITECTURE.md).

This public source snapshot was explicitly requested despite incomplete corpus
validation. Older local documentation forbidding publication until all examples
passed is superseded for this experimental source publication only. Publication
does not approve new GPU experiments or claim completion of those gates.

## Publication scope

Original local work remains intact. Source was copied without implementation
rewrites. Private logs, authorization records, process identities, device grants,
generated binaries/configurations, Library metadata, model conversations and
unrelated projects are excluded. Four private CPU orchestration/package files
(`cpu_idle_host_guard.py`, `cpu_correctness_host_guard_v2.py`,
`cpu_pending22_selection.py`, `package_all_cpu_sources.py`) are omitted because they embed private host or Library details;
historical supervisor workflows referring to them are not portable entry points.
Summaries retain hashes of private historical source records for traceability;
they do not contain the complete raw evidence archive.

Apache-2.0; preserve [NOTICE](NOTICE) and [upstream license](LICENSE.upstream).
The local snapshot has no prior committed history. Vendored upstream attribution
and pin are preserved; this publication is an independent repository.
