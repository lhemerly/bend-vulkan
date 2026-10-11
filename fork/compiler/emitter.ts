// Fork-owned emitter. Metadata comes from checked semantic capture, never emitted C.
export type Expr = ["arg", number] | ["lit", number] | ["bin", string, Expr, Expr];
type Segment = { fid: string; id: number; arity: number; result?: Expr;
  fork?: { join: string; children: { fid: string; args: Expr[]; index: number }[] } };
export type Plan = { schema: string; roots: number[]; segments: Segment[] };

export function expression(e: Expr, args: string[], glsl = false): string {
  if (e[0] === "arg") {
    if (!Number.isInteger(e[1]) || !args[e[1]]) throw Error("argument outside checked arity");
    return args[e[1]];
  }
  if (e[0] === "lit") {
    if (!Number.isInteger(e[1]) || e[1] < 0 || e[1] > 0xffffffff) throw Error("invalid U32 literal");
    return `${e[1]}u`;
  }
  if (e[0] !== "bin" || !["+", "-", "*", "&", "|", "^"].includes(e[1])) throw Error("unsupported expression");
  const body = `(${expression(e[2], args, glsl)} ${e[1]} ${expression(e[3], args, glsl)})`;
  return glsl ? body : `((uint32_t)${body})`;
}

export function validate(plan: Plan): Map<string, Segment> {
  if (plan.schema !== "bend-u32-fork-v1") throw Error("metadata version mismatch");
  const by = new Map(plan.segments.map(s => [s.fid, s]));
  if (by.size !== plan.segments.length || new Set(plan.segments.map(s => s.id)).size !== by.size)
    throw Error("duplicate compiler segment identity");
  for (const s of by.values()) {
    if (!Number.isInteger(s.id) || s.id < 0 || s.id > 65535) throw Error("invalid segment ID");
    if (s.result && !s.fork) expression(s.result, Array.from({length:s.arity}, (_,i) => `a${i}`));
    else if (s.fork && !s.result) {
      if (s.arity !== 1 || s.fork.children.length !== 2) throw Error("unsupported fork shape");
      const join = by.get(s.fork.join);
      if (!join?.result || join.fork || join.arity !== 2) throw Error("unsupported join");
      if (new Set(s.fork.children.map(c => c.index)).size !== 2) throw Error("duplicate result index");
      for (const c of s.fork.children) {
        const child = by.get(c.fid);
        if (!child?.result || child.fork || child.arity !== 1 || c.args.length !== 1 || ![0,1].includes(c.index))
          throw Error("unsupported child");
        expression(c.args[0], ["x"]);
      }
    } else throw Error("missing/ambiguous checked body");
  }
  for (const id of plan.roots) if (![...by.values()].some(s => s.id === id && s.arity === 1))
    throw Error("invalid root descriptor");
  return by;
}

export function referenceDispatch(plan: Plan): string {
  const by = validate(plan);
  const cases = plan.roots.map(id => {
    const root = [...by.values()].find(s => s.id === id)!;
    if (root.result) return `case ${id}: return ${expression(root.result, ["x"])};`;
    const values = root.fork!.children.map(c => {
      const arg = expression(c.args[0], ["x"]);
      return `uint32_t child${c.index} = ${expression(by.get(c.fid)!.result!, [arg])};`;
    }).join("\n");
    return `case ${id}: {\n${values}\nreturn ${expression(by.get(root.fork!.join)!.result!, ["child0","child1"])};\n}`;
  }).join("\n");
  return `static uint32_t fork_reference(uint32_t fid, uint32_t x) {\nswitch(fid) {\n${cases}\ndefault: err_fail("fork: unknown checked root"); return 0;\n}\n}\n`;
}

export function shader(plan: Plan): string {
  const by = validate(plan);
  const setup: string[] = [], childCases: string[] = [], joins: string[] = [];
  for (const id of plan.roots) {
    const root = [...by.values()].find(s => s.id === id)!;
    if (root.result) { setup.push(`case ${id}u: w[2]=${expression(root.result,["w[1]"],true)}; releaseWord(4u,2u); break;`); continue; }
    const f = root.fork!, join = by.get(f.join)!;
    setup.push(`case ${id}u: w[5]=2u; w[7]=${join.id}u; ${f.children.map(c => `w[${12+c.index*4}]=${by.get(c.fid)!.id}u; w[${13+c.index*4}]=${expression(c.args[0],["w[1]"],true)}; w[${14+c.index*4}]=${c.index}u; w[${15+c.index*4}]=${join.id}u;`).join(" ")} releaseWord(10u,1u); break;`);
    joins.push(`case ${join.id}u: result=${expression(join.result!,["w[8]","w[9]"],true)}; break;`);
    for (const c of f.children) {
      const s=by.get(c.fid)!;
      childCases.push(`case ${s.id}u: result=${expression(s.result!,["w[at+1u]"],true)}; break;`);
    }
  }
  return `#version 450
#extension GL_KHR_memory_scope_semantics : require
#pragma use_vulkan_memory_model
// Fork ABI v1: 24 logical uint words. Finite prescribed two-child order.
layout(local_size_x=128) in;
layout(std430,binding=0) devicecoherent buffer Words { uint w[]; };
uint acquireWord(uint i){return atomicLoad(w[i],gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsAcquire);}
void releaseWord(uint i,uint v){atomicStore(w[i],v,gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsRelease);}
void phase(){controlBarrier(gl_ScopeWorkgroup,gl_ScopeWorkgroup,gl_StorageSemanticsShared,gl_SemanticsAcquireRelease);}
void complete(uint slot){
 if(acquireWord(10u)!=1u || acquireWord(3u)!=0u)return;
 uint at=12u+4u*slot;
 if(w[at+2u]!=slot || w[at+3u]!=w[7]){releaseWord(3u,2u);return;}
 uint old=atomicOr(w[6],1u<<slot,gl_ScopeDevice,gl_StorageSemanticsNone,gl_SemanticsRelaxed);
 if((old&(1u<<slot))!=0u){releaseWord(3u,3u);return;}
 uint result; switch(w[at]) { ${[...new Set(childCases)].join("\n")} default:releaseWord(3u,2u);return; }
 w[8u+slot]=result;
 uint rem=atomicAdd(w[5],0xffffffffu,gl_ScopeDevice,gl_StorageSemanticsBuffer,gl_SemanticsRelease);
 if(rem==1u){
  if(acquireWord(5u)!=0u){releaseWord(3u,4u);return;}
  switch(w[7]) { ${[...new Set(joins)].join("\n")} default:releaseWord(3u,2u);return; }
  w[2]=result; releaseWord(4u,2u);
 } else if(rem!=2u)releaseWord(3u,4u);
}
void main(){
 if(any(notEqual(gl_WorkGroupID,uvec3(0u))) || w.length()<24)return;
 uint order=w[11];
 if(gl_LocalInvocationIndex==0u){
  for(uint i=2u;i<11u;i++)w[i]=0u;
  for(uint i=12u;i<24u;i++)w[i]=0u;
  if(order>1u)releaseWord(3u,6u);
  else switch(w[0]) { ${setup.join("\n")} default:releaseWord(3u,2u); }
 }
 phase();
 if(gl_LocalInvocationIndex==order)complete(order);
 phase();
 if(gl_LocalInvocationIndex==(order^1u))complete(order^1u);
 phase();
 if(gl_LocalInvocationIndex==0u && acquireWord(4u)==2u)w[20]=w[2];
}
`;
}
