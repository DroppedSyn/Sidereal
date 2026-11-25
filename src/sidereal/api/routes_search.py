"""GET /api/search: full-text search over stories (M26, plan §16).

Results are newest first (story id descending) with an exclusive ``before`` id cursor, so
paging is stable while runs add stories; each result carries its bm25 rank and a snippet.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from sidereal.api.deps import get_settings, open_db
from sidereal.api.present import story_out
from sidereal.api.schemas import SearchResult, SearchResults
from sidereal.config import Settings
from sidereal.db.feedback_repo import story_feedback
from sidereal.db.search_repo import SearchQueryError, search
from sidereal.db.views_repo import views_for_ids

router = APIRouter()


@router.get("/api/search", response_model=SearchResults,
            responses={400: {"description": "the query could not be run"}})
def search_stories(
    settings: Annotated[Settings, Depends(get_settings)],
    q: Annotated[str, Query(max_length=1000)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> SearchResults:
    with open_db(settings) as conn:
        try:
            hits = search(conn, q, limit=limit + 1, before=before)
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        more = len(hits) > limit
        hits = hits[:limit]
        views = {v.id: v for v in views_for_ids(conn, [h.story_id for h in hits])}
        feedback = story_feedback(conn, list(views))
    results = [SearchResult(story=story_out(views[h.story_id], fb=feedback[h.story_id]),
                            rank=h.rank, snippet=h.snippet)
               for h in hits if h.story_id in views]
    next_before = hits[-1].story_id if more and hits else None
    return SearchResults(query=q, results=results, next_before=next_before)
