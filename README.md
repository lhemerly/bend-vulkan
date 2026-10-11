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
