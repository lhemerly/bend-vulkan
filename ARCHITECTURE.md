# Architecture assessment

Verdict: a reasonably separated experimental backend, with substantial research
debt. It is not a clean production implementation yet. No comparative PMI review
was performed here, so this is an assessment of Bend's actual source boundaries.

The strongest boundary is `fork/compiler/nat_ir.ts`: explicit limits and validation
separate accepted task/join plans from generation. `fork/compiler/emitter.ts` and
`nat_emitter.ts` consume those plans. `fork/runtime/reference_bridge.c` keeps host
task delivery and continuation ownership separate from shader lowering. The pinned
checker in `evidence/upstream/bend.ts` remains distinct and unchanged.
`fork/runtime/f32_controller.py` validates manifest, generated shader and caller
identities before execution, while `fork/runtime/f32_worker_prepare.py` owns
preparation. CPU reference and actual device transports are explicit alternatives.
These are useful architecture boundaries, not conclusions inferred from test counts.

The largest maintenance problem is duplicated compiler code:
`fork/compiler/capture.ts` is 6,704 lines and `capture_f32.ts` is 6,753 lines.
Both derive from the pinned monolithic `evidence/upstream/comp.ts`, so future
upstream fixes and local changes need coordinated propagation. Likewise
`routing.ts`/`routing_f32.ts`, `cpu_routing.c`/`cpu_routing_f32.c`, and Nat/F32
controller/arena/bridge families duplicate structure. The separation makes narrow
experiments reviewable, but it has not converged to a shared backend interface.

`tools/cpu_remaining87_supervisor*.py`, `cpu_pending22_actual_supervisor*.py`
and versioned admission/audit scripts preserve experiments instead of offering
one canonical harness. Their source is retained without pretending every historic
workflow is independently runnable. Several require excluded private receipts,
source inventories, or host policies. The original README and CPU checkpoint
were stale relative to the later F32 hardware runs and v19 CPU reconciliation;
this public README is a fresh entry point.

Reproducibility is mixed: the Rust crate has no external dependencies and a lock
file; upstream source is vendored at a known commit; the focused F32 CPU smoke
regenerates output and verifies ordinary C byte parity. Bun, Clang, shader tools,
driver and Python versions are not uniformly pinned. Historical hash-bound worker
configs cannot simply be moved and reused. The public CI checks CPU primitives
and adapters; it does not validate Vulkan memory ordering or historical evidence.

Remaining work includes the 190 CPU obligations, consolidation of capture/routing
variants, a documented stable CLI and reproducible toolchain, and wider language
and concurrent runtime support. Bounded Nat/F32 examples and prescribed finite
task orders do not establish arbitrary heaps, ADTs, arrays, recursive parallel
programs, multi-workgroup progress or a general Bend Vulkan runtime.

Publication verification: focused Rust tests/Clippy, scalar adapter rejection
tests, and the unchanged gpu_trig CPU smoke were run from the relocated source.
No GPU experiments or benchmarks were performed. Historical CPU/GPU summaries
were extracted from current reconciliation and device receipts, with private
host/authorization metadata removed.
