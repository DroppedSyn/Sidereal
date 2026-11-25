// TOP / Relevant / On the side (+ the optional dropped list), shared by Gazette and Daily.
import type { Counts, Sections } from '../api/types';
import BucketSection from './BucketSection';

export const CALM_MESSAGE = 'Nothing needs your attention right now.';
export const SIDE_COLLAPSE = 10;

interface Props {
  sections: Sections;
  counts: Counts;
  includeDrop: boolean;
  onToggleDrop: () => void;
  now?: Date;
}

export default function StorySections({ sections, counts, includeDrop, onToggleDrop, now }: Props) {
  return (
    <div className="sections">
      <BucketSection title="TOP" bucket="top" stories={sections.top} variant="lead"
        emptyMessage={CALM_MESSAGE} now={now} />
      <BucketSection title="Relevant" bucket="relevant" stories={sections.relevant}
        emptyMessage="Nothing relevant here." now={now} />
      <BucketSection title="On the side" bucket="side" stories={sections.side} variant="compact"
        emptyMessage="Nothing on the side." collapseAfter={SIDE_COLLAPSE} now={now} />
      {counts.drop > 0 ? (
        <div className="drop-toggle">
          <button type="button" className="link-button" aria-pressed={includeDrop} onClick={onToggleDrop}>
            {includeDrop ? `Hide ${counts.drop} dropped` : `Show ${counts.drop} dropped`}
          </button>
        </div>
      ) : null}
      {includeDrop && sections.drop.length > 0 ? (
        <BucketSection title="Dropped" bucket="drop" stories={sections.drop} variant="compact"
          emptyMessage="" now={now} />
      ) : null}
    </div>
  );
}
