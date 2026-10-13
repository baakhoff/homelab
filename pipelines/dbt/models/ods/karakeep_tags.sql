-- One row per tag, with how many bookmarks carry it, split by who attached
-- it: a person, or the AI when the bookmark was saved.
select
  id as tag_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractUInt(record, 'numBookmarks') as bookmarks,
  JSONExtractUInt(record, 'numBookmarksByAttachedType', 'human') as bookmarks_by_person,
  JSONExtractUInt(record, 'numBookmarksByAttachedType', 'ai') as bookmarks_by_ai,
  extracted_at
from ({{ snapshot_records('karakeep', 'tags') }})
