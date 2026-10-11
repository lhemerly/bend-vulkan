"""Regenerate evidence, require saved vectors unchanged, then run source/CPU gates."""
from pathlib import Path
import subprocess,sys,os
root=Path(__file__).resolve().parents[1]
paths=[root/'evidence/shader-cpu-vectors.txt',root/'evidence/upstream-helper-vectors.txt']
saved={p:p.read_bytes() for p in paths}
subprocess.run([sys.executable,root/'tools/check_shader_cpu.py'],check=True)
subprocess.run(['cc','-std=c11','-O1','-fsanitize=undefined','-fno-sanitize-recover=all',root/'evidence/upstream-helpers.c','-o',root/'evidence/upstream-helpers'],check=True)
r=subprocess.run([root/'evidence/upstream-helpers'],capture_output=True,check=True);paths[1].write_bytes(r.stdout)
for p,old in saved.items():
 if p.read_bytes()!=old:
  p.with_suffix('.unexpected.txt').write_bytes(p.read_bytes());p.write_bytes(old);raise RuntimeError('regenerated vector mismatch: '+str(p))
subprocess.run(['cargo','test','--offline','--manifest-path',root/'Cargo.toml'],env=dict(os.environ,CARGO_BUILD_JOBS='1'),check=True)
subprocess.run(['cargo','clippy','--offline','--manifest-path',root/'Cargo.toml','--all-targets','--','-D','warnings'],env=dict(os.environ,CARGO_BUILD_JOBS='1'),check=True)
subprocess.run([sys.executable,root/'tools/test_emit_u32_segment.py'],check=True)
print('Saved vectors freshly regenerated and matched; Rust/Clippy/adapter gates passed. No GPU dispatch.')
