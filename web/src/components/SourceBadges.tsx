import type { StorySource } from '../api/types';
import { safeHref } from '../lib/safeHref';

export default function SourceBadges({ sources }: { sources: StorySource[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className="source-badges" aria-label="Sources">
      {sources.map((s, i) => {
        const href = safeHref(s.url);
        return (
          <li key={`${s.key}-${i}`} className="badge badge-source">
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {s.name}
              </a>
            ) : (
              <span>{s.name}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
