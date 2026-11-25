// A search snippet with its matches in <mark>. Every piece is React text, never markup.
import { splitHighlights } from '../lib/highlight';

export default function Highlighted({ snippet }: { snippet: string }) {
  return (
    <p className="search-snippet">
      {splitHighlights(snippet).map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
    </p>
  );
}
