// CPU-only comparison of pinned upstream and current fork default emitters.
import * as fs from 'node:fs';
import * as Bend from '../../evidence/upstream/bend.ts';
import * as Upstream from '../../evidence/upstream/comp.ts';
import * as Fork from '../compiler/capture.ts';
const [file,out] = process.argv.slice(2);
const book = Bend.book_nil();
await Bend.book_load(book,file,'',new Map()); Bend.book_valid(book);
if(book.hols) throw Error('unchecked holes');
fs.writeFileSync(out+'/upstream.c',Upstream.compile_book(book));
fs.writeFileSync(out+'/default.c',Fork.compile_book(book));
