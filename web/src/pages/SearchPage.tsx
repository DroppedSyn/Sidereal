// Search results (M26): newest first, each with a highlighted snippet above its story card.
import { useSearchParams } from 'react-router-dom';
import { useSearch } from '../api/hooks';
import Highlighted from '../components/Highlighted';
import { ErrorNote, Loading } from '../components/Status';
import StoryCard from '../components/StoryCard';

export default function SearchPage({ now }: { now?: Date }) {
  const [params] = useSearchParams();
  const q = (params.get('q') ?? '').trim();
  const { data, isPending, isError, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useSearch(q);
  const results = data?.pages.flatMap((p) => p.results) ?? [];
  return (
    <div className="page search">
      <header className="page-header">
        <h2 className="page-title">Search</h2>
        {q ? <p className="page-sub">Results for “{q}”, newest first</p> : null}
      </header>
      {!q ? (
        <p className="status-note">Type a word or two in the search box above.</p>
      ) : isPending ? (
        <Loading what="Searching" />
      ) : isError ? (
        <ErrorNote error={error} onRetry={() => void refetch()} />
      ) : results.length === 0 ? (
        <p className="status-note">No stories match.</p>
      ) : (
        <>
          <ol className="search-results">
            {results.map((r) => (
              <li key={r.story.id} className="search-result">
                <Highlighted snippet={r.snippet} />
                <StoryCard story={r.story} now={now} />
              </li>
            ))}
          </ol>
          {hasNextPage ? (
            <button type="button" className="button" disabled={isFetchingNextPage}
              onClick={() => void fetchNextPage()}>
              {isFetchingNextPage ? 'Loading…' : 'Load more results'}
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
