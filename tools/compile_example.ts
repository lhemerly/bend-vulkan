// Local-only upstream API adapter: no main.ts CLI, telemetry, credentials or publication.
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as Bend from '../evidence/upstream/bend.ts';
import * as Comp from '../evidence/upstream/comp.ts';
const file = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const text = fs.readFileSync(file, 'utf8');
if (text.split('\n').filter(x => /^\s*import\b/.test(x)).some(x => x.trim() !== 'import Base')) throw new Error('Only local Base import supported');
const book = Bend.book_nil();
await Bend.book_load(book, file, '', new Map());
Bend.book_valid(book);
if (book.hols) throw new Error('Incomplete checked book');
fs.writeFileSync(output, Comp.compile_book(book));
console.log('Checked local Bend source and emitted upstream C:', file);
