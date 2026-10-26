"""Reproducible checked-source / CPU / SPIR-V / Vulkan compatibility gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from bend_vulkan import build, command, CC


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--cpu-only', action='store_true', help='validate shaders but do not execute Vulkan')
    parser.add_argument('--software', action='store_true')
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--case', action='append', help='fixture stem; repeat to select multiple cases')
    parser.add_argument('--cube-log', type=int, choices=range(8), default=4)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--staging', action='store_true', help='force the host-visible staging path')
    args = parser.parse_args()
    if args.cpu_only and args.staging:
        parser.error('--staging requires Vulkan execution')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('BEND_FORK_', 'BEND_VULKAN_'))}
    env['BEND_VULKAN_DEVICE'] = str(args.device)
    if args.software:
        env['BEND_VULKAN_SOFTWARE'] = '1'
    if args.staging:
        env['BEND_VULKAN_FORCE_STAGING'] = '1'
    cases = sorted((ROOT/'fork/tests/general').glob('*.bend'))
    if args.case:
        missing = set(args.case) - {p.stem for p in cases}
        if missing:
            parser.error('unknown cases: ' + ', '.join(sorted(missing)))
        cases = [p for p in cases if p.stem in args.case]
    report = {'passed': False, 'Vulkan_executed': not args.cpu_only,
              'software_permitted': args.software, 'staging_forced': args.staging,
              'device': None, 'memory_paths': [], 'cube_log': args.cube_log, 'cases': []}
    for source in cases:
        row = {'name': source.name, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'runs': []}
        directory = output/source.stem
        try:
            build(source, directory, cube_log=args.cube_log)
            command(['bun', ROOT/'fork/upstream_compile.ts', source, directory/'upstream.c'])
            assert (directory/'upstream.c').read_bytes() == (directory/'default.c').read_bytes(), 'default C differs from pinned compiler'
            command([CC, '-std=gnu11', '-O1', '-ffp-contract=off', directory/'upstream.c',
                     '-lpthread', '-lm', '-o', directory/'upstream'])
            expected = [line[2:] for line in source.read_text().splitlines() if line.startswith('#|')]
            exit_code = int(expected.pop().split()[1]) if expected and expected[-1].startswith('exit ') else 0
            want = '\n'.join(expected) + ('\n' if expected else '')
            for threads in (1, 2):
                lanes = [('upstream', 'off'), ('program', 'off')]
                if not args.cpu_only:
                    lanes += [('program', 'on')]
                for executable, gpu in lanes:
                    trace_env = dict(env, BEND_VULKAN_TRACE='1')
                    p = subprocess.run([str(directory/executable), '+RTS', '--gpu', gpu,
                                       '--threads', str(threads), '-RTS'],
                                       capture_output=True, text=True, env=trace_env, timeout=args.timeout)
                    label = f'{executable}-gpu-{gpu}-threads-{threads}'
                    (directory/(label+'.stdout')).write_text(p.stdout)
                    (directory/(label+'.stderr')).write_text(p.stderr)
                    errors = ''.join(line+'\n' for line in p.stderr.splitlines() if not line.startswith('Vulkan '))
                    actual = p.stdout + errors
                    assert p.returncode == exit_code and actual == want, (label, p.returncode, actual, want)
                    dispatches = re.search(r'dispatches=(\d+)', p.stderr)
                    device = re.search(r'Vulkan device=(.*?) memory=', p.stderr)
                    memory = re.search(r'memory=(\S+)', p.stderr)
                    if gpu == 'on':
                        assert (dispatches and int(dispatches[1]) > 0) or (exit_code and 'Vulkan submit ' in p.stderr), 'no device dispatch evidence'
                        if args.staging and memory:
                            assert memory[1] == 'staged', 'forced staging path was not used'
                        if args.staging and exit_code == 0:
                            assert memory and memory[1] == 'staged', 'no staging memory-path evidence'
                        if device:
                            report['device'] = device[1]
                        if memory and memory[1] not in report['memory_paths']:
                            report['memory_paths'].append(memory[1])
                    row['runs'].append({'lane': label, 'exit': p.returncode,
                                        'dispatches': int(dispatches[1]) if dispatches else None,
                                        'memory': memory[1] if memory else None})
            row.update(passed=True, default_C_byte_parity=True, SPIRV_valid=True)
        except Exception as error:
            row.update(passed=False, error=str(error))
        report['cases'].append(row)
        (output/'RESULT.json').write_text(json.dumps(report, indent=2)+'\n')
        print(source.stem + (' PASS' if row['passed'] else ' FAIL: ' + row['error'][:300]), flush=True)
    report['passed'] = all(c['passed'] for c in report['cases'])
    (output/'RESULT.json').write_text(json.dumps(report, indent=2)+'\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
