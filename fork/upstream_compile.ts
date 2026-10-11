import * as Bend from '../evidence/upstream/bend.ts';
import {compile_book} from '../evidence/upstream/comp.ts';
const book=Bend.book_nil();await Bend.book_load(book,process.argv[2],'',new Map());Bend.book_valid(book);if(book.hols)throw Error('unchecked holes');await Bun.write(process.argv[3],compile_book(book));
