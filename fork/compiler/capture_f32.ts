// Compatibility entry point. Checked capture now has a single implementation.
export * from './capture.ts';
import * as Capture from './capture.ts';
import type * as Bend from '../../evidence/upstream/bend.ts';
export function routing_book(book: Bend.Book, natCapture = false) {
  return Capture.routing_book(book, natCapture, true);
}
export function compile_book(book: Bend.Book, vulkan = false, routing = false, natCapture = false) {
  return Capture.compile_book(book, vulkan, routing, natCapture, routing);
}
