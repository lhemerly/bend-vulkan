// The general backend starts from the same checked compiler as the CPU lane.
import * as fs from 'node:fs';
import * as Bend from '../evidence/upstream/bend.ts';
import {compile_book} from './compiler/capture.ts';

try {
  const [source, output] = process.argv.slice(2);
  if (!source || !output) throw Error('usage: bun general_cli.ts SOURCE OUTPUT.c');
  const book = Bend.book_nil();
  await Bend.book_load(book, source, '', new Map());
  Bend.book_valid(book);
  if (book.hols) throw Error('unchecked holes');
  fs.writeFileSync(output, compile_book(book));
} catch (error) {
  console.error((error as any)?.$ === 'Err' ? Bend.err_show(error as Bend.Err)
    : error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
