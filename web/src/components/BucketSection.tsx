import { useId, useState } from 'react';
import type { Story } from '../api/types';
import StoryCard, { type CardVariant } from './StoryCard';

interface Props {
  title: string;
  bucket: string;
  stories: Story[];
  variant?: CardVariant;
  emptyMessage: string;
  collapseAfter?: number;
  now?: Date;
}

export default function BucketSection({
  title,
  bucket,
  stories,
  variant = 'normal',
  emptyMessage,
  collapseAfter,
  now,
}: Props) {
  const headingId = useId();
  const [expanded, setExpanded] = useState(false);
  const limit = collapseAfter !== undefined && !expanded ? collapseAfter : stories.length;
  const shown = stories.slice(0, limit);
  const hidden = stories.length - shown.length;
  return (
    <section className={`bucket bucket-${bucket}`} aria-labelledby={headingId}>
      <h2 id={headingId} className="bucket-title">
        {title} <span className="bucket-count">{stories.length}</span>
      </h2>
      {stories.length === 0 ? (
        <p className="bucket-empty">{emptyMessage}</p>
      ) : (
        <ol className="story-list">
          {shown.map((s) => (
            <li key={s.id}>
              <StoryCard story={s} variant={variant} now={now} />
            </li>
          ))}
        </ol>
      )}
      {hidden > 0 ? (
        <button type="button" className="link-button" onClick={() => setExpanded(true)}>
          Show {hidden} more
        </button>
      ) : null}
    </section>
  );
}
