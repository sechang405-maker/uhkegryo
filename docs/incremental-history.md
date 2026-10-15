# Incremental conversation history

`GET /api/sessions/{session_id}/jobs` retains ascending `limit`/`offset` behavior by default.
Opt in with `latest=true&limit=20`; request earlier pages using `before_job_id` from
`next_before_job_id`. Each page returns ascending `items`, `has_more`, and the next cursor
anchored to the oldest page item. The same owned session must contain the cursor; a missing
or foreign cursor follows the session-not-found policy. UUID and timestamp together order ties.

`pending_items` includes nonterminal records outside the page so restoration resumes every
active job. `reference_item` and `previous_reference_item` carry the latest two nonempty
reference results separately from pagination and conversation turns. The frontend hydrates
only the latest rendered result and reference context through the existing detail endpoint;
previous reference detail is needed only for legacy preserved-role boards. Modern merged
term-ID plans already contain their complete board. Sources remain attached to each result.

The UI reads 20 sessions per request with explicit load more, deduplicates by session ID,
and restarts the offset chain after local create/reorder/delete. The selected session stays
available even outside the first page. Offset paging is not a snapshot: concurrent changes
from another tab may shift records between pages; refreshing restarts the list.

Older history loads only on explicit request, preserves current turn objects and thumbnail
hydration, and captures the scroll anchor before prepending. Switching/new/deleting the
active conversation aborts page requests and invalidates their generation. Demo mode remains
local and never calls these APIs. Markdown output has React's default memo boundary;
interactive retry and clarification actions remain outside it.
