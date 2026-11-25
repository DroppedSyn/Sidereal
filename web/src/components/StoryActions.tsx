// Feedback controls on a story card (M24): vote, read/unread, hide, mute source or keyword.
import { useState } from 'react';
import { useStoryFeedback } from '../api/feedback';
import type { Story } from '../api/types';
import MuteMenu from './MuteMenu';

export default function StoryActions({ story }: { story: Story }) {
  const feedback = useStoryFeedback();
  const [muting, setMuting] = useState(false);
  const vote = story.vote ?? null;
  const send = (change: Parameters<typeof feedback.mutate>[0]['change']) =>
    feedback.mutate({ id: story.id, change });
  return (
    <div className="story-actions">
      <div className="story-action-row" role="group" aria-label="Feedback">
        <button type="button" className="action-button" aria-pressed={vote === 'up'}
          aria-label="More like this" title="More like this"
          onClick={() => send({ vote: vote === 'up' ? null : 'up' })}>
          ▲ Up
        </button>
        <button type="button" className="action-button" aria-pressed={vote === 'down'}
          aria-label="Less like this" title="Less like this"
          onClick={() => send({ vote: vote === 'down' ? null : 'down' })}>
          ▼ Down
        </button>
        <button type="button" className="action-button" onClick={() => send({ read: !story.read })}>
          {story.read ? 'Mark unread' : 'Mark read'}
        </button>
        <button type="button" className="action-button" onClick={() => send({ hidden: true })}>
          Hide
        </button>
        <button type="button" className="action-button" aria-expanded={muting}
          onClick={() => setMuting((v) => !v)}>
          Mute…
        </button>
      </div>
      {feedback.isError ? (
        <p role="alert" className="action-error">
          Could not save: {feedback.error.message}
        </p>
      ) : null}
      {muting ? <MuteMenu story={story} /> : null}
    </div>
  );
}
