-- Google's "Saved" lists - links, places and things kept from Search and
-- Maps - one row per item, from Takeout exports. `list` is the list's name.
select
  id as item_key,
  replaceOne(JSONExtractString(record, '_file'), '.csv', '') as list,
  JSONExtractString(record, 'Title') as title,
  nullIf(JSONExtractString(record, 'URL'), '') as url,
  nullIf(JSONExtractString(record, 'Note'), '') as note,
  nullIf(JSONExtractString(record, 'Comment'), '') as comment,
  nullIf(JSONExtractString(record, 'Tags'), '') as tags,
  extracted_at
from ({{ accumulated_records('google', ['takeout/saved']) }})
