"""Fail-closed adapter from one real upstream emitted U32 segment to GLSL.
Supports one scalar argument and nested U32_BIN +,-,*,&,|,^; no Bend runtime/calls.
"""
import re, json, hashlib, sys
from pathlib import Path
class Unsupported(ValueError): pass

def expression(text, variable):
    tokens=re.findall(r'U32_BIN|[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:ull|u)?|[^\s]',text)
    pos=0
    def take(expected=None):
        nonlocal pos
        if pos>=len(tokens):raise Unsupported('truncated expression')
        t=tokens[pos];pos+=1
        if expected is not None and t!=expected:raise Unsupported('expected '+expected)
        return t
    def parse():
        t=take()
        if t=='U32_BIN':
            take('(');a=parse();take(',');op=take()
            if op not in ('+','-','*','&','|','^'):raise Unsupported('unsupported operator '+op)
            take(',');b=parse();take(')');return '('+a+' '+op+' '+b+')'
        if isinstance(variable,dict) and t in variable:return variable[t]
        if t==variable:return 'x'
        if re.fullmatch(r'[0-9]+(?:ull|u)?',t):
            n=int(re.sub(r'ull$|u$','',t))
            if n>0xffffffff:raise Unsupported('non-U32 constant')
            return str(n)+'u'
        raise Unsupported('unsupported token '+t)
    result=parse()
    if pos!=len(tokens):raise Unsupported('trailing expression')
    return result

def emit(source, fid):
    if not re.fullmatch(r'FID_[A-Z0-9_]+',fid):raise Unsupported('invalid FID')
    pattern=r'WL_CASE\('+fid+r'\)\s*\{\s*u32 (\w+) = r0;\s*WL_OPEN\s*r0 = ([^;]+);\s*WL_RETN\(1\);\s*\}\}'
    found=re.findall(pattern,source)
    if len(found)!=1:raise Unsupported('expected exactly one scalar straight-line upstream segment')
    variable,raw=found[0];expr=expression(raw,variable)
    shader='''#version 450
// Generated from pinned upstream Bend compiler segment; scalar U32 subset only.
layout(local_size_x=64) in;
layout(std430,binding=0) buffer Words { uint w[]; };
uint generated_segment(uint x) { return EXPR; }
void main() {
    if (w.length()<1) return;
    uint count=w[0];
    if (count==0u || count>4096u || uint(w.length())<1u+2u*count) return;
    uint i=gl_GlobalInvocationID.x;
    if(i<count) w[1u+count+i]=generated_segment(w[1u+i]);
}
'''.replace('EXPR',expr)
    # Keep actual upstream U32_BIN expression in the independent CPU helper.
    cpu='''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef uint32_t u32;typedef uint64_t u64;
#define U32_BIN(a,o,b) ((u64)((u32)(a) o (u32)(b)))
static u32 segment(u32 x) { u32 VAR=x;return (u32)(RAW); }
int main(void) { unsigned long long x;while(scanf("%llu",&x)==1){if(x>UINT32_MAX)return 2;printf("%u\\n",segment((u32)x));}return 0; }
'''.replace('VAR',variable).replace('RAW',raw)
    return shader,cpu,raw
if __name__=='__main__':
    source=Path(sys.argv[1]).read_text();shader,cpu,raw=emit(source,sys.argv[2]);Path(sys.argv[3]).write_text(shader);Path(sys.argv[4]).write_text(cpu)
    print(json.dumps({'adapter':'scalar-u32-v1','source_sha256':hashlib.sha256(source.encode()).hexdigest(),'fid':sys.argv[2],'raw_expression':raw,'unsupported':'calls/heap/fork/continuations/arrays/Nat/IO/floats/generalBend'}))
