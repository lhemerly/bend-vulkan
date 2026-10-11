// Uses pinned library APIs, never CLI telemetry/update/publish or hub credentials.
import * as fs from 'node:fs';import * as path from 'node:path';
import * as B from '../../bend-vulkan-feasibility/source/bend2/bend.ts';
import * as C from '../../bend-vulkan-feasibility/source/bend2/comp.ts';
import * as F from '../fork/compiler/capture.ts';
const [mode,input,dest]=process.argv.slice(2);const file=path.resolve(input);let book:B.Book;
try{
 const text=fs.readFileSync(file,'utf8');
 if(text.split('\n').some(l=>/^\s*import\b/.test(l)&&l.trim()!=='import Base'))throw Error('ledger probe permits Base-only imports; other modules need explicit import closure review');
 book=B.book_nil();await B.book_load(book,file,'',new Map());B.book_valid(book);
 if(book.hols)throw 'Error: '+book.hols+' TODO'+(book.hols===1?'':'s')+' found.\nThe code is incomplete, and not a valid proof yet.';
}catch(e){console.error('SOME PROOFS FAIL\n'+((e as any)?.$==='Err'?B.err_show(e as any):e instanceof RangeError?'Error: the machine stack overflowed (a deep recursion, or a literal too large to expand)':String(e)));process.exit(1);}
try{
 if(mode==='check')console.log('CHECK_OK');
 else if(mode==='interp'){
  const main=book.tlds.main;
  if(!main||main.$!=='Def'||!main.v)throw Error('module without runnable main: check only');
  if(C.io_type(book)!==null)process.exitCode=C.io_run(book,[file]);
  else console.log(B.term_show(B.term_lower(B.term_snf(book,main.v))));
 }else if(mode==='upstream-c')fs.writeFileSync(dest,C.compile_book(book));
 else if(mode==='fork-c')fs.writeFileSync(dest,F.compile_book(book));
 else if(mode==='upstream-js')fs.writeFileSync(dest,C.js_book(book));
 else throw Error('unknown probe mode');
}catch(e){console.error((e as any)?.$==='Err'?B.err_show(e as any):String(e));process.exitCode=1;}
