// Separate typed F32 expression extension. No admission, transport, or checked-source claim.
export type F32Expr = {type:'F32',op:'arg',index:number}|{type:'F32',op:'bits',bits:number}
 |{type:'F32',op:'sin'|'cos'|'tan',value:F32Expr}
 |{type:'F32',op:'add'|'mul',left:F32Expr,right:F32Expr};
export type U32FromF32 = {type:'U32',op:'from-f32',value:F32Expr};
const bytes=new ArrayBuffer(4),words=new Uint32Array(bytes),floats=new Float32Array(bytes);
export function f32Bits(value:number):number {floats[0]=value;return words[0];}
export function fromBits(bits:number):number {
 if(!Number.isInteger(bits)||bits<0||bits>0xffffffff)throw Error('invalid F32 word');
 words[0]=bits;return floats[0];
}
export function validateF32(e:F32Expr,arity:number):void {
 let count=0;
 function visit(x:F32Expr):void {
  if(++count>64||!x||x.type!=='F32')throw Error('typed F32 expression limit/type');
  if(x.op==='arg'){if(!Number.isInteger(x.index)||x.index<0||x.index>=arity)throw Error('F32 argument index');return;}
  if(x.op==='bits'){if(!Number.isFinite(fromBits(x.bits)))throw Error('nonfinite literal outside finite contract');return;}
  if(['sin','cos','tan'].includes(x.op)){visit((x as any).value);return;}
  if(x.op==='add'||x.op==='mul'){visit(x.left);visit(x.right);return;}
  throw Error('unsupported F32 operation');
 }visit(e);
}
export function evaluateF32(e:F32Expr,args:number[]):number {
 validateF32(e,args.length);
 function go(x:F32Expr):number {
  if(x.op==='arg'){const v=Math.fround(args[x.index]);if(!Number.isFinite(v))throw Error('nonfinite F32 input');return v;}
  if(x.op==='bits')return fromBits(x.bits);
  if(x.op==='add')return Math.fround(go(x.left)+go(x.right));
  if(x.op==='mul')return Math.fround(go(x.left)*go(x.right));
  return Math.fround(Math[x.op](go(x.value)));
 }return go(e);
}
export function toU32(value:number):number {return value>=1&&value<4294967296?Math.floor(value):0;}
// Emit one rounded intermediate per source operation; avoid reassociation/FMA.
export function emitF32(e:U32FromF32,args:string[],backend:'C'|'GLSL'):string {
 if(e.type!=='U32'||e.op!=='from-f32')throw Error('F32 result conversion');validateF32(e.value,args.length);
 let id=0;const lines:string[]=[];
 function go(x:F32Expr):string {
  if(x.op==='arg')return args[x.index];
  let value:string;
  if(x.op==='bits')value=backend==='GLSL'?`uintBitsToFloat(${x.bits}u)`:`bend_f32_from_bits(${x.bits}u)`;
  else if(x.op==='add'||x.op==='mul'){const a=go(x.left),b=go(x.right);value=`${a} ${x.op==='add'?'+':'*'} ${b}`;}
  else value=`${x.op}${backend==='C'?'f':''}(${go(x.value)})`;
  const name=`f${id++}`;lines.push(`${backend==='GLSL'?'precise ':''}float ${name} = ${value};`);return name;
 }
 const result=go(e.value);lines.push(`return (${result} >= 1.0${backend==='C'?'f':''} && ${result} < 4294967296.0${backend==='C'?'f':''}) ? ${backend==='C'?'(uint32_t)':'uint'}(${result}) : 0u;`);
 return lines.join('\n');
}
