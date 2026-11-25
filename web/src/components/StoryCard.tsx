// One story (plan §10.2). Every string from the API renders as React text, never as markup.
import { useId, useState } from 'react';
import type { Story } from '../api/types';
import { flagBadges } from '../lib/flags';
import { formatDateTime, relativeTime } from '../lib/format';
import { safeHref } from '../lib/safeHref';
import SourceBadges from './SourceBadges';

export type CardVariant = 'lead' | 'normal' | 'compact';

interface Props {
  story: Story;
  variant?: CardVariant;
  now?: Date;
}

function StoryTitle({ story, variant }: { story: Story; variant: CardVariant }) {
  const href = safeHref(story.lead_url);
  const Tag = variant === 'lead' ? 'h3' : 'h4';
  return (
    <Tag className="story-title">
      {href ? (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {story.title}
        </a>
      ) : (
        <span>{story.title}</span>
      )}
    </Tag>
  );
}

function Labels({ story }: { story: Story }) {
  const flags = flagBadges(story.flags);
  const focus = story.focus && story.focus !== 'none' ? story.focus : null;
  if (flags.length === 0 && !focus && story.tags.length === 0) return null;
  return (
    <ul className="story-labels" aria-label="Labels">
      {flags.map((f) => (
        <li key={f.key} className={f.severe ? 'badge badge-flag badge-severe' : 'badge badge-flag'}>
          {f.label}
        </li>
      ))}
      {focus ? <li className="badge badge-focus">{focus}</li> : null}
      {story.tags.map((t) => (
        <li key={t} className="tag">
          {t}
        </li>
      ))}
    </ul>
  );
}

function Score({ score }: { score: number | null }) {
  if (score === null) return <span className="story-score story-score-failed">not assessed</span>;
  return (
    <span className="story-score" title="Score (0 to 100)">
      score {Math.round(score)}
    </span>
  );
}

export default function StoryCard({ story, variant = 'normal', now }: Props) {
  const [showExcerpt, setShowExcerpt] = useState(false);
  const excerptId = useId();
  const seen = story.first_seen_at;
  return (
    <article className={`story story-${variant}`} data-bucket={story.bucket}>
      <StoryTitle story={story} variant={variant} />
      <div className="story-meta">
        <SourceBadges sources={story.sources} />
        <time dateTime={seen} title={formatDateTime(seen)} className="story-time">
          {relativeTime(seen, now)}
        </time>
        <Score score={story.score} />
      </div>
      <Labels story={story} />
      {story.summary ? (
        <p className="story-summary">
          <span className="label">AI summary</span> {story.summary}
        </p>
      ) : null}
      {story.why && variant !== 'compact' ? (
        <p className="story-why">
          <span className="label">Why it matters:</span> {story.why}
        </p>
      ) : null}
      {story.excerpt && variant !== 'compact' ? (
        <div className="story-excerpt">
          <button
            type="button"
            className="link-button"
            aria-expanded={showExcerpt}
            aria-controls={excerptId}
            onClick={() => setShowExcerpt((v) => !v)}
          >
            {showExcerpt ? 'Hide original excerpt' : 'Show original excerpt'}
          </button>
          {showExcerpt ? (
            <blockquote id={excerptId} className="excerpt-text">
              {story.excerpt}
            </blockquote>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
