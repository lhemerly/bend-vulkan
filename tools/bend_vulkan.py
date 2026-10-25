"""Build and run the general Bend Vulkan backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from c_to_glsl import translate

CC = os.environ.get('CC', 'clang')

ROOT = Path(__file__).resolve().parents[1]


def command(argv, timeout=120):
    result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout or f'{argv[0]} failed')
    return result


def once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError('pinned runtime anchor mismatch: ' + old[:60])
    return source.replace(old, new)


def host_source(source, cube_log):
    source = once(source, '#define CUBE      ((u64)CUBE_T * CUBE_T)',
                  '#define CUBE      ((u64)CUBE_T << CUBE_LOG)')
    source = once(source, '#define RING_LOG  (17 - CUBE_LOG)', '#define RING_LOG  10')
    source = once(source, '#define RING_WORDS ((1ull << 10) + 2)', '#define RING_WORDS (RING_LEN + 2)')
    source = once(source, 'static u32    CUBE_LOG = 7;', f'#define CUBE_LOG {cube_log}')
    source = once(source, '#if !BEND_CUDA\n#define gpu_map pool_mmap',
                  '#if !BEND_CUDA && !BEND_VULKAN\n#define gpu_map pool_mmap')
    source = once(source, '#if BEND_METAL || BEND_CUDA\n\nstatic void gpu_kernel',
                  '#if BEND_METAL || BEND_CUDA || BEND_VULKAN\n\nstatic void gpu_kernel')
    source = once(source, '#else\n\n#define gpu_probe() "this binary has no CUDA or Metal GPU support"',
                  '#elif BEND_VULKAN\n#include "vulkan_host.c"\n#else\n\n#define gpu_probe() "this binary has no CUDA or Metal GPU support"')
    return source


def build(source, directory, backend='vulkan', cube_log=4):
    source, directory = Path(source).resolve(strict=True), Path(directory).resolve()
    if directory.exists():
        raise ValueError('build output must be a new directory')
    for tool in ('bun', CC) + (('glslangValidator', 'spirv-val') if backend == 'vulkan' else ()):
        if not shutil.which(tool):
            raise ValueError('required tool missing: ' + tool)
    directory.mkdir(parents=True)
    command(['bun', ROOT/'fork/general_cli.ts', source, directory/'default.c'])
    c = (directory/'default.c').read_text()
    if backend == 'vulkan':
        translate(directory/'default.c', directory/'program.comp', cube_log)
        command(['glslangValidator', '-V', '--target-env', 'vulkan1.2', directory/'program.comp', '-o', directory/'program.gpu'])
        command(['spirv-val', '--target-env', 'vulkan1.2', directory/'program.gpu'])
        shutil.copyfile(ROOT/'fork/runtime/vulkan_host.c', directory/'vulkan_host.c')
        c = host_source(c, cube_log)
    (directory/'program.c').write_text(c)
    flags = ['-DBEND_VULKAN=1', '-lvulkan'] if backend == 'vulkan' else []
    flags += ['-l' + library for header, library in [('X11', 'X11'), ('alsa', 'asound')]
              if '#include <' + header + '/' in c]
    command([CC, '-std=gnu11', '-O1', '-ffp-contract=off', directory/'program.c',
             '-lpthread', '-lm', *flags, '-o', directory/'program'])
    files = ['program', 'program.c', 'default.c']
    if backend == 'vulkan':
        files += ['program.gpu', 'program.comp', 'vulkan_host.c']
    manifest = {'schema': 'bend-vulkan-general-v1', 'backend': backend, 'cube_log': cube_log,
                'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'files': {f: hashlib.sha256((directory/f).read_bytes()).hexdigest() for f in files}}
    (directory/'build.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return directory


def run(directory, args):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/'build.json').read_text())
    if manifest.get('schema') != 'bend-vulkan-general-v1':
        raise ValueError('unsupported build manifest')
    for filename, digest in manifest['files'].items():
        if hashlib.sha256((directory/filename).read_bytes()).hexdigest() != digest:
            raise ValueError('build artifact changed: ' + filename)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('BEND_FORK_', 'BEND_VULKAN_'))}
    env['BEND_VULKAN_DEVICE'] = str(args.device)
    if args.software:
        env['BEND_VULKAN_SOFTWARE'] = '1'
    if args.trace:
        env['BEND_VULKAN_TRACE'] = '1'
    backend = args.backend or manifest['backend']
    if backend == 'vulkan' and manifest['backend'] != 'vulkan':
        raise ValueError('this build has no Vulkan module; rebuild with --backend vulkan')
    gpu = (args.memory or 'on') if backend == 'vulkan' else 'off'
    argv = [str(directory/'program'), '--gpu', gpu, '--threads', str(args.threads)]
    argv += ['--', *args.program_args]
    process = subprocess.Popen(argv, env=env, start_new_session=True)
    try:
        return process.wait(timeout=args.timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise RuntimeError('program interrupted or execution deadline exceeded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('devices', help='list Vulkan devices and required capabilities')
    compile_parser = sub.add_parser('build', help='compile a checked source into a new directory')
    compile_parser.add_argument('source')
    compile_parser.add_argument('-o', '--output', required=True)
    execute = sub.add_parser('run', help='run a source file or a completed build directory')
    execute.add_argument('source')
    execute.add_argument('--device', type=int, default=0)
    execute.add_argument('--software', action='store_true', help='explicitly permit a software Vulkan device')
    execute.add_argument('--threads', type=int, default=1)
    execute.add_argument('--memory', help='GPU heap size, e.g. 256MB')
    execute.add_argument('--timeout', type=float, default=300)
    execute.add_argument('--trace', action='store_true')
    for p in (compile_parser, execute):
        p.add_argument('--backend', choices=('vulkan', 'cpu'), default='vulkan')
        p.add_argument('--cube-log', type=int, choices=range(8), default=4,
                       help='log2 of the number of 128-lane workgroups')
    execute.set_defaults(backend=None)
    # Keep program arguments separate from the build/run options.
    argv = sys.argv[1:]
    program_args = []
    if '--' in argv:
        split = argv.index('--'); program_args = argv[split+1:]; argv = argv[:split]
    args = parser.parse_args(argv)
    args.program_args = program_args
    if args.command == 'devices':
        with tempfile.TemporaryDirectory(prefix='bend-vulkan-devices-') as temporary:
            binary = Path(temporary)/'devices'
            command([CC, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', ROOT/'native/devices.c', '-lvulkan', '-o', binary])
            print(command([binary]).stdout, end='')
        return 0
    if args.command == 'build':
        print(build(args.source, args.output, args.backend, args.cube_log))
        return 0
    if args.device < 0 or not 1 <= args.threads <= 128 or not 0 < args.timeout <= 86400:
        parser.error('invalid device, threads, or timeout')
    if Path(args.source).is_dir():
        return run(args.source, args)
    with tempfile.TemporaryDirectory(prefix='bend-vulkan-') as temporary:
        directory = build(args.source, Path(temporary)/'build', args.backend or 'vulkan', args.cube_log)
        return run(directory, args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('bend-vulkan: ' + str(error), file=sys.stderr)
        sys.exit(1)
