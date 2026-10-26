"""Build and run the general Bend Vulkan backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile

from c_to_glsl import translate

VERSION = '0.2.0'
CC = os.environ.get('CC', 'clang')

ROOT = Path(__file__).resolve().parents[1]

TOOL_HINTS = {
    'bun': 'install Bun from https://bun.sh and ensure it is on PATH',
    'clang': 'install Clang and ensure it is on PATH (or set CC=...)',
    'glslangValidator': 'install glslang-tools/vulkan-sdk and ensure it is on PATH',
    'spirv-val': 'install spirv-tools/vulkan-sdk and ensure it is on PATH',
}


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
    source = once(source, '#define RING_LEN  (1ull << (17 - CUBE_LOG))',
                  '#define RING_LEN  (1ull << 10)')
    source = once(source, 'static u32    CUBE_LOG = 7;', f'#define CUBE_LOG {cube_log}')
    source = once(source, '#if !BEND_CUDA\n#define gpu_map pool_mmap',
                  '#if !BEND_CUDA && !BEND_VULKAN\n#define gpu_map pool_mmap')
    source = once(source, '#if BEND_METAL || BEND_CUDA\n\nstatic void gpu_kernel',
                  '#if BEND_METAL || BEND_CUDA || BEND_VULKAN\n\nstatic void gpu_kernel')
    source = once(source, '#else\n\n#define gpu_probe() "this binary has no CUDA or Metal GPU support"',
                  '#elif BEND_VULKAN\n#include "vulkan_host.c"\n#else\n\n#define gpu_probe() "this binary has no CUDA or Metal GPU support"')
    return source


def required_tools(backend):
    return ('bun', CC) + (('glslangValidator', 'spirv-val') if backend == 'vulkan' else ())


def doctor_requirements(backend):
    requirements = {'bun': 'bun', 'clang': CC}
    if backend == 'vulkan':
        requirements['glslangValidator'] = 'glslangValidator'
        requirements['spirv-val'] = 'spirv-val'
    return requirements


def require_tools(backend):
    missing = [tool for tool in required_tools(backend) if not shutil.which(tool)]
    if missing:
        raise ValueError('required tool missing: ' + ', '.join(missing))


def build(source, directory, backend='vulkan', cube_log=4):
    """Build in a private sibling directory and publish it atomically.

    A failed build therefore never leaves a half-written output directory that
    blocks a retry or makes a partial artifact look runnable.
    """
    source = Path(source).resolve(strict=True)
    target = Path(directory).resolve()
    if target.exists():
        raise ValueError('build output must be a new directory')
    if not source.is_file():
        raise ValueError('source must be a checked .bend file')
    require_tools(backend)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.bend-vulkan-build-', dir=target.parent))
    try:
        os.chmod(staging, 0o755)
        command(['bun', ROOT/'fork/general_cli.ts', source, staging/'default.c'])
        c = (staging/'default.c').read_text()
        if backend == 'vulkan':
            translate(staging/'default.c', staging/'program.comp', cube_log)
            command(['glslangValidator', '-V', '--target-env', 'vulkan1.2', staging/'program.comp', '-o', staging/'program.gpu'])
            command(['spirv-val', '--target-env', 'vulkan1.2', staging/'program.gpu'])
            shutil.copyfile(ROOT/'fork/runtime/vulkan_host.c', staging/'vulkan_host.c')
            c = host_source(c, cube_log)
        (staging/'program.c').write_text(c)
        flags = ['-DBEND_VULKAN=1', '-lvulkan'] if backend == 'vulkan' else []
        flags += ['-l' + library for header, library in [('X11', 'X11'), ('alsa', 'asound')]
                  if '#include <' + header + '/' in c]
        command([CC, '-std=gnu11', '-O1', '-ffp-contract=off', staging/'program.c',
                 '-lpthread', '-lm', *flags, '-o', staging/'program'])
        files = ['program', 'program.c', 'default.c']
        if backend == 'vulkan':
            files += ['program.gpu', 'program.comp', 'vulkan_host.c']
        manifest = {'schema': 'bend-vulkan-general-v1', 'backend': backend, 'cube_log': cube_log,
                    'version': VERSION, 'source': str(source),
                    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'files': {f: hashlib.sha256((staging/f).read_bytes()).hexdigest() for f in files}}
        (staging/'build.json').write_text(json.dumps(manifest, indent=2) + '\n')
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def run(directory, args):
    directory = Path(directory).resolve()
    manifest = json.loads((directory/'build.json').read_text())
    if (manifest.get('schema') != 'bend-vulkan-general-v1'
            or manifest.get('backend') not in ('vulkan', 'cpu')
            or not isinstance(manifest.get('files'), dict)
            or not all(isinstance(name, str) and isinstance(digest, str)
                       for name, digest in manifest['files'].items())):
        raise ValueError('unsupported build manifest')
    if args.cube_log is not None and args.cube_log != manifest.get('cube_log'):
        raise ValueError('--cube-log does not match this build; rebuild with the requested geometry')
    for filename, digest in manifest['files'].items():
        if Path(filename).name != filename:
            raise ValueError('unsafe build artifact path: ' + filename)
        if hashlib.sha256((directory/filename).read_bytes()).hexdigest() != digest:
            raise ValueError('build artifact changed: ' + filename)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('BEND_FORK_', 'BEND_VULKAN_'))}
    env['BEND_VULKAN_DEVICE'] = str(args.device)
    if args.software:
        env['BEND_VULKAN_SOFTWARE'] = '1'
    if args.trace:
        env['BEND_VULKAN_TRACE'] = '1'
    if args.staging:
        env['BEND_VULKAN_FORCE_STAGING'] = '1'
    backend = args.backend or manifest['backend']
    if backend == 'vulkan' and manifest['backend'] != 'vulkan':
        raise ValueError('this build has no Vulkan module; rebuild with --backend vulkan')
    if args.staging and backend != 'vulkan':
        raise ValueError('--staging requires a Vulkan build')
    gpu = (args.memory or 'on') if backend == 'vulkan' else 'off'
    # Bend's C runtime accepts its own flags between +RTS and -RTS. Passing
    # them directly would expose them to IO.args as program arguments.
    argv = [str(directory/'program'), '+RTS', '--gpu', gpu, '--threads',
            str(args.threads), '-RTS']
    argv += args.program_args
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


def doctor_payload(backend):
    tools = {}
    for name, executable in doctor_requirements(backend).items():
        path = shutil.which(executable)
        tools[name] = {'available': path is not None, 'path': path, 'command': executable}
    missing = [tool for tool, info in tools.items() if not info['available']]
    return {
        'command': 'doctor',
        'ok': not missing,
        'missing': missing,
        'vulkan_requested': backend == 'vulkan',
        'gpu_dispatches': 0,
        'python': {'version': platform.python_version(), 'executable': sys.executable},
        'platform': platform.platform(),
        'tools': tools,
        'hints': {tool: TOOL_HINTS.get(tool, f'install {tool} and ensure it is on PATH')
                  for tool in missing},
    }


def doctor(backend, as_json):
    payload = doctor_payload(backend)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload['ok'] else 1
    print('bend-vulkan doctor: prerequisite inspection only; no compiler or GPU dispatch is performed')
    print('backend: ' + ('Vulkan' if backend == 'vulkan' else 'CPU'))
    for tool, info in payload['tools'].items():
        if info['available']:
            print(f'  {tool}: {info["path"]}')
        else:
            print(f'  {tool}: MISSING - {TOOL_HINTS.get(tool, f"install {tool} and ensure it is on PATH")}')
    if payload['ok']:
        print('SUCCESS: all required tools are on PATH')
        return 0
    print('FAILED: missing tools: ' + ', '.join(payload['missing']), file=sys.stderr)
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='bend-vulkan ' + VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('devices', help='list Vulkan devices and required capabilities')
    doctor_parser = sub.add_parser('doctor', help='inspect prerequisites without executing a compiler or GPU')
    doctor_parser.add_argument('--backend', choices=('vulkan', 'cpu'), default='vulkan',
                               help='which build dependency set to inspect')
    doctor_parser.add_argument('--cpu-only', action='store_true',
                               help='require only the CPU build tools (bun and clang)')
    doctor_parser.add_argument('--json', action='store_true', help='print a machine-readable report')
    compile_parser = sub.add_parser('build', help='compile a checked source into a new directory')
    compile_parser.add_argument('source')
    compile_parser.add_argument('-o', '--output', required=True)
    compile_parser.add_argument('--backend', choices=('vulkan', 'cpu'), default='vulkan')
    compile_parser.add_argument('--cube-log', type=int, choices=range(8), default=4,
                                help='log2 of the number of 128-lane workgroups')
    execute = sub.add_parser('run', help='run a source file or a completed build directory')
    execute.add_argument('source')
    execute.add_argument('--device', type=int, default=0)
    execute.add_argument('--software', action='store_true', help='explicitly permit a software Vulkan device')
    execute.add_argument('--threads', type=int, default=1)
    execute.add_argument('--memory', help='GPU heap size, e.g. 256MB')
    execute.add_argument('--timeout', type=float, default=300)
    execute.add_argument('--trace', action='store_true')
    execute.add_argument('--staging', action='store_true',
                         help='force the host-visible staging path (diagnostic)')
    execute.add_argument('--backend', choices=('vulkan', 'cpu'), default=None,
                         help='override the manifest backend (CPU builds cannot run on Vulkan)')
    execute.add_argument('--cube-log', type=int, choices=range(8), default=None,
                         help='log2 of the number of 128-lane workgroups when building a source')
    # Keep program arguments separate from the build/run options.
    argv = sys.argv[1:]
    program_args = []
    if '--' in argv:
        split = argv.index('--'); program_args = argv[split+1:]; argv = argv[:split]
    args = parser.parse_args(argv)
    args.program_args = program_args
    if args.command == 'doctor':
        backend = 'cpu' if args.cpu_only else args.backend
        return doctor(backend, args.json)
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
        cube_log = args.cube_log if args.cube_log is not None else 4
        directory = build(args.source, Path(temporary)/'build', args.backend or 'vulkan', cube_log)
        return run(directory, args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('bend-vulkan: ' + str(error), file=sys.stderr)
        sys.exit(1)
