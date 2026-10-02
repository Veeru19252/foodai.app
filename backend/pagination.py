"""Bounded list queries.

Several list endpoints here read a whole table: a customer's order history grows
with their lifetime activity, an admin table grows with the platform, and
``/restaurants`` and ``/reviews`` are reachable without authentication. None of
them had a ``LIMIT``, so their cost and payload grew without bound.

Rather than change the response shape -- each of these returns a bare JSON array
and the frontend reads them as such -- these add ``limit``/``offset`` query
parameters over a generous default. Every paged response also carries
``X-Total-Count``, so a caller that hits the cap can tell the list was truncated
and ask for the next page instead of silently assuming it saw everything.

The default sits far above any page a UI renders. It exists to stop a
pathological table from being dumped in a single response, not to redesign the
contract; a client that needs more walks the pages.

Handlers take ``limit``/``offset`` as plain ``int`` defaults rather than
``Query(...)`` markers or a ``Depends`` tuple. Two reasons, both learned the
hard way here: a marker object reaching a direct call is a confusing
``int(Query(200))`` TypeError, and a ``Depends`` tuple arrives as a marker rather
than a pair. Plain ints are still inferred as query parameters by FastAPI, so
``validate_page`` does the bounds checking and raises the same 422.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Response

# Cap on rows per response when the caller does not say. Large enough that no
# dashboard or list page reaches it in normal use.
DEFAULT_LIMIT = 200
# Ceiling on a caller-supplied limit, so ?limit=100000 cannot ask for the whole
# table back.
MAX_LIMIT = 1000


def validate_page(limit: int = DEFAULT_LIMIT, offset: int = 0) -> tuple:
    """Bounds-check paging arguments, returning ``(limit, offset)``.

    Raises 422 for a limit or offset outside its range, matching what a declared
    Query constraint would have produced.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be between 1 and {MAX_LIMIT}.",
        )
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be zero or greater.")
    return limit, offset


def count_of(db, query) -> int:
    """Rows ``query`` would return without a limit.

    Callers put this in ``X-Total-Count``. The ``order_by(None)`` matters: a
    COUNT over an ordered query is valid but pointless work for the database.
    Only worth calling where the extra query is cheaper than the rows it
    describes.
    """
    return query.order_by(None).count()


def set_total(response: Optional[Response], total: int) -> None:
    """Record the unpaged row count on the response being built.

    Injected as a parameter rather than returned to wrap the body, because a
    handler that returns a JSONResponse stops being callable as a plain function
    in a test -- the row list is no longer what comes back. Optional, so a direct
    call with no Response is still fine; FastAPI always supplies one over HTTP.

    ``Access-Control-Expose-Headers`` is required, or the browser hides the
    header from the frontend fetch that asked for it.
    """
    if response is None:
        return
    response.headers["X-Total-Count"] = str(total)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"