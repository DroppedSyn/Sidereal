// Search snippets mark matches with two control characters (db/search_repo.py): U+0002 opens a
// match, U+0003 closes it. They are split here into plain-text pieces; nothing is parsed as HTML.
export const HIT_START = '\u0002';
export const HIT_END = '\u0003';

export interface Piece {
  text: string;
  hit: boolean;
}

/** Split a snippet into text pieces, `hit` for the parts between the markers. Stray or
 * unbalanced markers are dropped; empty pieces are left out. */
export function splitHighlights(snippet: string): Piece[] {
  const pieces: Piece[] = [];
  let hit = false;
  let text = '';
  const flush = () => {
    if (text) pieces.push({ text, hit });
    text = '';
  };
  for (const ch of snippet) {
    if (ch === HIT_START) {
      flush();
      hit = true;
    } else if (ch === HIT_END) {
      flush();
      hit = false;
    } else {
      text += ch;
    }
  }
  flush();
  return pieces;
}
