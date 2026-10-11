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
 else if(mode==='verdict'){
  const bad=book_promises(book);
  if(bad.length){console.error('SOME PROOFS FAIL\nError: '+bad.length+' def'+(bad.length===1?' relies':'s rely')+' on unsafe or foreign code:\n'+bad.map(k=>'- '+B.name_key(k)).join('\n'));process.exitCode=1;}
  else console.log('ALL PROOFS CHECK\nUse --verdict for mathematical validity.');
 }
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

// Exact copied upstream promise/reference traversal; CLI entry point not run.
function book_promises(book: B.Book): string[] {
  const own  = [...new Set(book.order)].filter((k) => book.tlds[k].b !== true);
  const bad  = new Set(Object.keys(book.tlds).filter((k) => {
    const t = book.tlds[k] as B.Def;
    return t.u === true || (t.i !== undefined && t.b !== true);
  }));
  if (bad.size === 0) {
    return [];
  }
  const uses: Record<string, string[]> = Object.create(null);
  const reach = new Set(own);
  for (const k of reach) {
    const t = book.tlds[k];
    if (t !== undefined) {
      const rs = new Set<string>();
      for (const c of t.$ === "ADT" ? [t, ...t.c] : [t]) {
        term_refs(B.term_lower(c.T), rs);
      }
      if (t.$ === "Def" && t.e !== undefined) {
        term_refs(t.e, rs);
      }
      for (const r of rs) {
        (uses[r] ??= []).push(k);
        reach.add(r);
      }
    }
  }
  for (const k of bad) {
    uses[k]?.forEach((j) => bad.add(j));
  }
  return own.filter((k) => bad.has(k));
}

// term_refs adds to out the names a term (a span skipped) refers to.
function term_refs(t: object, out: Set<string>): void {
  const seen = new Set([t]);
  for (const todo = [t]; todo.length > 0;) {
    const x = todo.pop() as Record<string, unknown>;
    if ((x.$ === "Ref" || x.$ === "ADT") && typeof x.k === "string") {
      out.add(x.k);
    }
    for (const f in x) {
      const v = x[f];
      if (f !== "s" && typeof v === "object" && v !== null && !seen.has(v)) {
        seen.add(v);
        todo.push(v);
      }
    }
  }
}

