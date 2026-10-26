"""Lower the pinned compiler's device C AST to Vulkan GLSL.

Device pointers become byte offsets into the shared corpus. Private pointers are
GLSL inout parameters. Clang supplies types and implicit conversions; unsupported
AST nodes fail compilation instead of silently changing program semantics.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def device_source(source, cube_log):
    dialect = source[source.index('#if DEVICE\n#define LOCK'):source.index('// Types\n')]
    source = source[source.index('// Types\n'):]
    source = source.replace('#define CUBE      ((u64)CUBE_T * CUBE_T)',
                            '#define CUBE      ((u64)CUBE_T << CUBE_LOG)')
    source = source.replace('#define RING_LOG  (17 - CUBE_LOG)', '#define RING_LOG  10')
    source = source.replace('#define RING_WORDS ((1ull << 10) + 2)', '#define RING_WORDS (RING_LEN + 2)')
    start, end = source.index('// A32\n'), source.index('// Err\n')
    atomics = '#define a32_at(H,w) ((DEV u32*)&(H)[w])\n#define a32_acq(p) bend_fence()\n#define w64_load(p) (*(p))\n'
    for space in ('DEV', 'TG'):
        for op in ('load', 'load_acq'):
            atomics += f'u32 __attribute__((overloadable)) a32_{op}({space} u32* p);\n'
        for op in ('store', 'store_rel', 'add', 'sub', 'sub_rel', 'and', 'or', 'xor', 'min', 'max', 'exch', 'fadd'):
            atomics += f'u32 __attribute__((overloadable)) a32_{op}({space} u32* p, u32 v);\n'
        atomics += f'bool __attribute__((overloadable)) a32_cas({space} u32* p, u32* e, u32 v);\n'
        atomics += f'u32 __attribute__((overloadable)) a32_cmpx({space} u32* p, u32 x, u32 v);\n'
    source = source[:start] + atomics + source[end:]
    source = source.replace('A32_LOOP(fadd, f32_rewrap(f32_unbox(o) + f32_unbox(v)))', '')
    a = source.index('INLINE f32 f32_unbox(')
    b = source.index('INLINE u64 f32_to_u32(', a)
    source = source[:a] + 'f32 f32_unbox(u64 x);\nu64 f32_rewrap(f32 x);\n' + source[b:]
    a = source.index('#ifdef __METAL_VERSION__\nkernel void bend_dev(')
    b = source.index('  if (pass == 2)', a)
    source = source[:a] + '''static void bend_dev(DEV u64* H, u32 pass, u32 grids, u32 row, u32 lane) {
  TG u32* vote = (TG u32*)0;
''' + source[b:]
    header = f'''#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#define CUBE_LOG {cube_log}
#define DEVICE 1
#define DEV __attribute__((address_space(1)))
#define TG __attribute__((address_space(3)))
#define THR
#define INLINE static inline
#define OUTLINE static
#define FAR static
#define CONSTV static const
#define CLZ(x) ((uint32_t)__builtin_clz(x))
void bend_fence(void);
void bend_bar(void);
void bend_bard(void);
#define FENCE() bend_fence()
#define BAR() bend_bar()
#define BARD() bend_bard()
'''
    return header + dialect + source


def ctype(node):
    t = node.get('type', {})
    return t.get('qualType', '').replace('DEV ', '__attribute__((address_space(1))) ').replace('TG ', '__attribute__((address_space(3))) ').replace('THR ', '')


def pointer(t):
    return '*' in t


def global_pointer(t):
    return pointer(t) and 'address_space(' in t


def pointee(t):
    return re.sub(r'\s*\*\s*$', '', re.sub(r'__attribute__\(\(address_space\(\d\)\)\)', '', t)).strip()


def size(t):
    t = re.sub(r'__attribute__\(\(address_space\(\d\)\)\)', '', t).replace('const ', '').strip()
    return {'u64': 8, 'Term': 8, 'uint64_t': 8, 'unsigned long': 8, 'unsigned long long': 8,
            'u32': 4, 'u32a': 4, 'uint32_t': 4, 'unsigned int': 4, 'int': 4,
            'Bank': 24, 'u8': 1, 'uint8_t': 1, 'unsigned char': 1}.get(t) or unsupported_size(t)


def unsupported_size(t):
    raise ValueError('unsupported device C storage type: ' + t)


def gltype(t):
    if global_pointer(t):
        return 'uint64_t'
    t = re.sub(r'__attribute__\(\(address_space\(\d\)\)\)', '', t).replace('const ', '').strip()
    table = {'void': 'void', 'bool': 'bool', '_Bool': 'bool', 'float': 'float', 'f32': 'float',
             'double': 'float', 'u64': 'uint64_t', 'Term': 'uint64_t', 'uint64_t': 'uint64_t',
             'unsigned long': 'uint64_t', 'unsigned long long': 'uint64_t', 'long': 'int64_t',
             'long long': 'int64_t', 'int': 'int', 'unsigned int': 'uint', 'u32': 'uint',
             'u32a': 'uint', 'uint32_t': 'uint', 'u8': 'uint', 'uint8_t': 'uint',
             'unsigned char': 'uint', 'Env': 'Env', 'Bank': 'Bank'}
    if t not in table:
        raise ValueError('unsupported C type: ' + t)
    return table[t]


def name(s):
    # Prefix C identifiers so GLSL keywords and builtins cannot collide.
    return 'b_' + s if '__' not in 'b_' + s else 'bend_escaped_' + s.encode().hex()


class Lower:
    def __init__(self, ast):
        self.ast = ast
        self.local_words = 1
        def arrays(node):
            if node.get('kind') == 'VarDecl':
                dims = re.findall(r'\[(\d+)\]', ctype(node))
                if dims:
                    self.local_words = max(self.local_words, int(dims[0]))
            if node.get('kind') == 'ArraySubscriptExpr':
                base, index = node['inner']
                if pointer(ctype(base)) and not global_pointer(ctype(base)):
                    while index.get('kind') in ('ImplicitCastExpr', 'CStyleCastExpr', 'ParenExpr', 'ConstantExpr'):
                        index = index['inner'][0]
                    if index.get('kind') == 'IntegerLiteral':
                        self.local_words = max(self.local_words, int(index['value']) + 1)
            for child in node.get('inner', []):
                arrays(child)
        for declaration in ast['inner']:
            if declaration['kind'] == 'FunctionDecl':
                arrays(declaration)

    def address(self, node):
        k, inner = node['kind'], node.get('inner', [])
        if k in ('ParenExpr', 'ImplicitCastExpr'):
            return self.address(inner[0])
        if k == 'UnaryOperator' and node['opcode'] == '*':
            return self.expr(inner[0])
        if k == 'ArraySubscriptExpr':
            return f'({self.expr(inner[0])} + uint64_t({self.expr(inner[1])}) * {size(ctype(node))}ul)'
        if k == 'MemberExpr' and node.get('isArrow'):
            offset = {'off': 0, 'rd': 8, 'wr': 12, 'top': 16}[node['name']]
            return f'({self.expr(inner[0])} + {offset}ul)'
        raise ValueError('unsupported device address: ' + k)

    def deref(self, ptr, t, space):
        if 'address_space(3)' in space:
            return f'b_vote[uint({ptr}) / 4u]'
        if size(t) == 8:
            return f'b_heap64[uint(({ptr}) / 8ul)]'
        if size(t) == 4:
            return f'b_heap32[uint(({ptr}) / 4ul)]'
        raise ValueError('unsupported device dereference: ' + t)

    def convert(self, value, target, original):
        if pointer(target):
            return value if pointer(original) or '[' in original else f'uint64_t({value})'
        if gltype(target) == gltype(original):
            return value
        if gltype(target) == 'bool':
            return f'({value} != {gltype(original)}(0))'
        return f'{gltype(target)}({value})'

    def truth(self, n):
        value = self.expr(n)
        return value if gltype(ctype(n)) == 'bool' else f'({value} != {gltype(ctype(n))}(0))'

    def expr(self, n):
        k, ch, t = n['kind'], n.get('inner', []), ctype(n)
        if k == 'IntegerLiteral':
            return n['value'] + ('ul' if gltype(t) == 'uint64_t' else 'l' if gltype(t) == 'int64_t' else 'u' if gltype(t) == 'uint' else '')
        if k == 'FloatingLiteral':
            value = n['value']
            return value if any(x in value.lower() for x in ('.', 'e')) else value + '.0'
        if k == 'DeclRefExpr':
            return name(n['referencedDecl']['name'])
        if k in ('ParenExpr', 'ConstantExpr'):
            return '(' + self.expr(ch[0]) + ')'
        if k in ('ImplicitCastExpr', 'CStyleCastExpr'):
            if n.get('castKind') in ('LValueToRValue', 'FunctionToPointerDecay', 'ArrayToPointerDecay', 'NoOp'):
                return self.expr(ch[0])
            if t == 'void':
                return self.expr(ch[0])
            value = self.convert(self.expr(ch[0]), t, ctype(ch[0]))
            if gltype(t) == 'uint' and size(t) == 1:
                value = '(' + value + ' & 255u)'
            return value
        if k == 'ArraySubscriptExpr':
            if global_pointer(ctype(ch[0])):
                return self.deref(self.address(n), t, ctype(ch[0]))
            return f'{self.expr(ch[0])}[uint({self.expr(ch[1])})]'
        if k == 'MemberExpr':
            if n.get('isArrow'):
                return self.deref(self.address(n), t, ctype(ch[0]))
            return self.expr(ch[0]) + '.' + name(n['name'])
        if k == 'UnaryOperator':
            op = n['opcode']
            if op == '!':
                return f'int(!{self.truth(ch[0])})'
            if op == '&':
                return self.address(ch[0]) if global_pointer(t) else self.expr(ch[0])
            if op == '*':
                return self.deref(self.expr(ch[0]), t, ctype(ch[0])) if global_pointer(ctype(ch[0])) else self.expr(ch[0])
            if op in ('++', '--') and global_pointer(ctype(ch[0])):
                raise ValueError('device pointer increment needs explicit lowering')
            return '(' + (self.expr(ch[0]) + op if n.get('isPostfix') else op + self.expr(ch[0])) + ')'
        if k in ('BinaryOperator', 'CompoundAssignOperator'):
            op = n['opcode']; a, b = self.expr(ch[0]), self.expr(ch[1])
            if op in ('+', '-', '*', '/') and gltype(t) == 'float':
                fn = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'div'}[op]
                return f'b_float_{fn}({a}, {b})'
            if pointer(ctype(ch[0])) and op in ('+', '-', '+=', '-='):
                if pointer(ctype(ch[1])):
                    return f'int64_t(({a} - {b}) / {size(pointee(ctype(ch[0])))}ul)'
                b = f'(uint64_t({b}) * {size(pointee(ctype(ch[0])))}ul)'
            if op in ('&&', '||'):
                return f'int({self.truth(ch[0])} {op} {self.truth(ch[1])})'
            if op in ('==', '!=', '<', '>', '<=', '>='):
                return f'int({a} {op} {b})'
            return f'({a} {op} {b})'
        if k == 'ConditionalOperator':
            return f'({self.truth(ch[0])} ? {self.expr(ch[1])} : {self.expr(ch[2])})'
        if k == 'CallExpr':
            callee = ch[0]
            while callee['kind'] != 'DeclRefExpr':
                callee = callee['inner'][0]
            fn = callee['referencedDecl']['name']; args = [self.expr(a) for a in ch[1:]]
            if fn.startswith('a32_') and 'address_space(3)' in ctype(ch[1]):
                fn += '_shared'
            if fn == '__builtin_clz':
                return '(31 - findMSB(' + args[0] + '))'
            math_names = 'sqrt exp log log2 sin cos tan asin acos atan sinh cosh tanh floor ceil trunc'.split()
            mapped = fn if fn in math_names else 'abs' if fn == 'fabs' else 'b_atan2' if fn == 'atan2' else name(fn)
            return mapped + '(' + ', '.join(args) + ')'
        if k == 'InitListExpr':
            return self.initializer(n, t)
        if k == 'ImplicitValueInitExpr':
            return gltype(t) + '(0)'
        if k == 'UnaryExprOrTypeTraitExpr' and n['name'] == 'sizeof':
            return str(size(n['argType']['qualType'])) + 'ul'
        raise ValueError('unsupported expression: ' + k + ' ' + str(n)[:300])

    def initializer(self, n, t):
        dims = re.findall(r'\[(\d+)\]', t)
        if dims:
            base = t[:t.index('[')].strip()
            values = n.get('inner', n.get('array_filler', [])[1:])
            element_t = base + ''.join('[' + d + ']' for d in dims[1:])
            entries = [self.initializer(v, element_t) if v['kind'] == 'InitListExpr' else self.expr(v) for v in values]
            if not dims[1:]:
                entries += [gltype(base) + '(0)'] * (int(dims[0]) - len(entries))
            return gltype(base) + ''.join('[' + d + ']' for d in dims) + '(' + ','.join(entries) + ')'
        if t == 'Env':
            return 'Env(' + ', '.join(self.expr(v) for v in n.get('inner', [])) + ')'
        return self.expr(n)

    def decl(self, n, local=False):
        t, nm = ctype(n), name(n['name'])
        ch = n.get('inner', [])
        ch = [c for c in ch if not c['kind'].endswith('Attr')]
        if '[' in t:
            base = t[:t.index('[')].strip()
            dims = re.findall(r'\[(\d+)\]', t)
            if local:
                if len(dims) != 1:
                    raise ValueError('multidimensional local array')
                dims = [str(self.local_words)]
            decl = ('const ' if not local else '') + gltype(base) + ' ' + nm + ''.join('[' + d + ']' for d in dims)
            if ch:
                if local:
                    raise ValueError('initialized local array')
                decl += ' = ' + self.initializer(ch[-1], t)
            return decl
        return gltype(t) + ' ' + nm + (' = ' + self.expr(ch[-1]) if ch else '')

    def stmt(self, n):
        k, ch = n.get('kind'), n.get('inner', [])
        if k == 'CompoundStmt':
            return '{\n' + '\n'.join(self.stmt(x) for x in ch) + '\n}'
        if k == 'DeclStmt':
            return '\n'.join(self.decl(x, True) + ';' for x in ch)
        if k == 'ReturnStmt':
            return 'return' + (' ' + self.expr(ch[0]) if ch else '') + ';'
        if k == 'IfStmt':
            return 'if (' + self.truth(ch[0]) + ') ' + self.stmt(ch[1]) + (' else ' + self.stmt(ch[2]) if len(ch) == 3 else '')
        if k == 'ForStmt':
            init, _, test, step, body = ch
            initial = self.stmt(init).rstrip(';') if init.get('kind') else ''
            return 'for (' + initial + '; ' + (self.truth(test) if test.get('kind') else '') + '; ' + (self.expr(step) if step.get('kind') else '') + ') ' + self.stmt(body)
        if k == 'WhileStmt':
            return 'while (' + self.truth(ch[0]) + ') ' + self.stmt(ch[1])
        if k == 'DoStmt':
            return 'do ' + self.stmt(ch[0]) + ' while (' + self.truth(ch[1]) + ');'
        if k == 'SwitchStmt':
            return 'switch (' + self.expr(ch[0]) + ') ' + self.stmt(ch[1])
        if k == 'CaseStmt':
            return 'case ' + self.expr(ch[0]) + ': ' + self.stmt(ch[1])
        if k == 'DefaultStmt':
            return 'default: ' + self.stmt(ch[0])
        if k in ('BreakStmt', 'ContinueStmt'):
            return k[:-4].lower() + ';'
        if k == 'NullStmt':
            return ';'
        return self.expr(n) + ';'

    def function(self, node):
        params = []
        for p in node.get('inner', []):
            if p['kind'] != 'ParmVarDecl':
                continue
            t = ctype(p)
            if pointer(t) and not global_pointer(t):
                base = pointee(t)
                # The only private scalar pointer is the CAS/error-poll counter.
                suffix = '' if size(base) == 4 else f'[{self.local_words}]'
                params.append('inout ' + gltype(base) + ' ' + name(p['name']) + suffix)
            else:
                params.append(gltype(t) + ' ' + name(p['name']))
        result = ctype({'type': {'qualType': node['type']['qualType'].split('(')[0].strip()}})
        signature = gltype(result) + ' ' + name(node['name']) + '(' + ', '.join(params) + ')'
        return signature + ' ' + self.stmt(next(x for x in node['inner'] if x['kind'] == 'CompoundStmt'))

    def emit(self):
        parts = []
        for node in self.ast['inner']:
            if node.get('loc', {}).get('includedFrom'):
                continue
            if node['kind'] == 'FunctionDecl' and any(x.get('kind') == 'CompoundStmt' for x in node.get('inner', [])):
                parts.append(self.function(node))
            elif node['kind'] == 'VarDecl':
                parts.append(self.decl(node) + ';')
        return '\n\n'.join(parts)


def translate(source, output, cube_log=4):
    output = Path(output)
    c = output.with_suffix('.device.c')
    c.write_text(device_source(Path(source).read_text(), cube_log))
    p = subprocess.run([os.environ.get('CC', 'clang'), '-x', 'c', '-std=gnu11', '-fsyntax-only', '-Xclang', '-ast-dump=json', str(c)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise RuntimeError(p.stderr)
    ast = json.loads(p.stdout)
    body = Lower(ast).emit()
    preamble = Path(__file__).resolve().parents[1] / 'fork/runtime/general.comp'
    output.write_text(preamble.read_text() + '\n' + body + '''
void main() { b_bend_dev(0ul, b_push.pass, gl_NumWorkGroups.x, gl_WorkGroupID.x, gl_LocalInvocationIndex); }
''')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    parser.add_argument('--cube-log', type=int, default=4, choices=range(8))
    args = parser.parse_args()
    translate(args.source, args.output, args.cube_log)
