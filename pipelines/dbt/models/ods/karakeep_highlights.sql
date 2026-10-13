-- One row per highlight: a passage marked in a saved page, its colour, and
-- the note written beside it. bookmark_id joins karakeep_bookmarks.
select
  id as highlight_id,
  JSONExtractString(record, 'bookmarkId') as bookmark_id,
  JSONExtractString(record, 'text') as text,
  nullIf(JSONExtractString(record, 'note'), '') as note,
  JSONExtractString(record, 'color') as color,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  extracted_at
from ({{ snapshot_records('karakeep', 'highlights') }})
