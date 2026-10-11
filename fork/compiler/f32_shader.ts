import {natShader} from './nat_emitter';
import {emitF32,validateF32} from './f32_expression';
export function validateF32Plan(p:any):void {
 if(p.schema!=='bend-nat-f32-fork-v1'||p.depth!==5||p.tasks!==63||!Array.isArray(p.segments)||p.segments.length!==1||p.roots.length!==1)throw Error('F32 finite single-task contract');
 const s=p.segments[0];if(p.roots[0]!==s.id||!Number.isInteger(s.id)||s.id<0||s.id>65535||!Number.isInteger(s.join)||s.join<0||s.join>65535||s.join===s.id)throw Error('F32 checked identities');
 if(s.leaf?.type!=='U32'||s.leaf.op!=='from-f32')throw Error('F32 leaf conversion');validateF32(s.leaf.value,1);
 if(s.children.length!==2||s.children.some((c:any,i:number)=>c.slot!==i||c.id!==s.id))throw Error('F32 guarded binary recursion');s.children.forEach((c:any)=>validateF32(c.payload,1));
}
function floatFunction(e:any,name:string):string {
 let body=emitF32({type:'U32',op:'from-f32',value:e},['x'],'GLSL');
 const lines=body.split('\n'),ret=lines.pop()!;const v=ret.match(/return \((\w+) >=/)![1];return `float ${name}(float x){${lines.join('\n')}return ${v};}`;
}
export function f32Shader(p:any):string {
 validateF32Plan(p);const s=p.segments[0];
 const fake:any={schema:'bend-nat-fork-v1',roots:p.roots,limits:{depth:5,tasks:63,joins:31,steps:192,segments:64,expr:64,words:772},segments:[{id:s.id,fid:s.fid,role:'task',argument:'Nat',result:'U32',match:{kind:'Nat',zero:{op:'result',value:['lit',0]},successor:{op:'fork',join:s.join,children:s.children.map((c:any)=>({id:c.id,slot:c.slot,argument:{kind:'Nat',op:'guarded-predecessor'}}))}}},{id:s.join,fid:'checked-join-'+s.join,role:'join',arguments:['U32','U32'],result:'U32',value:['bin','+',['arg',0],['arg',1]]}]};
 let shader=natShader(fake);
 const start=shader.indexOf('bool descriptor('),end=shader.indexOf('bool reduction(',start);
 const leaf=`uint leaf(float x){${emitF32(s.leaf,['x'],'GLSL')}}`;
 const desc=`${leaf}\n${floatFunction(s.children[0].payload,'payload0')}\n${floatFunction(s.children[1].payload,'payload1')}\nbool descriptor(uint f,uint n,uint xb,out bool spawn,out uint v,out uint j,out uint c0,out uint c1,out uint x0,out uint x1){spawn=false;v=0u;j=0u;c0=0u;c1=0u;x0=0u;x1=0u;if(f!=${s.id}u)return false;float x=uintBitsToFloat(xb);if(isnan(x)||isinf(x))return false;if(n==0u){v=leaf(x);return true;}float a=payload0(x),b=payload1(x);if(isnan(a)||isinf(a)||isnan(b)||isinf(b))return false;spawn=true;j=${s.join}u;c0=${s.id}u;c1=${s.id}u;x0=floatBitsToUint(a);x1=floatBitsToUint(b);return true;}\n`;
 shader=shader.slice(0,start)+desc+shader.slice(end);
 shader=shader.replace('for(uint i=14u;i<768u;i++)','for(uint i=15u;i<768u;i++)')
 .replace('if(error==0u){w[6]=1u;', 'if(isnan(uintBitsToFloat(w[14]))||isinf(uintBitsToFloat(w[14])))error=1u;\n if(error==0u){w[TB+7u]=w[14];w[6]=1u;')
 .replace('c0=0u,c1=0u;bool spawn=false;','c0=0u,c1=0u,x0=0u,x1=0u;bool spawn=false;')
 .replace('descriptor(w[at],n,spawn,v,j,c0,c1)','descriptor(w[at],n,w[at+7u],spawn,v,j,c0,c1,x0,x1)')
 .replace('w[child+5u]=1u;','w[child+5u]=1u;w[child+7u]=slot==0u?x0:x1;');
 return shader.replace('// Task states','// F32 ABI v1: header14=root payload bits; task word7=payload bits.\n// Task states');
}
