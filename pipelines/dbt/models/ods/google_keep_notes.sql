-- Google Keep, one row per note, from Takeout exports - as of the newest
-- export loaded. A checklist's items are in `items` and, ticked or not,
-- in `text` too, one per line, so a search finds them either way.
-- Attachments (images, recordings) go to the NAS archive when the export is
-- packed with --files (pipelines/google.md).
select
  id as note_key,
  JSONExtractString(record, 'title') as title,
  if(JSONHas(record, 'listContent'),
     arrayStringConcat(arrayMap(x -> concat(if(JSONExtractBool(x, 'isChecked'), '[x] ', '[ ] '), JSONExtractString(x, 'text')),
                                JSONExtractArrayRaw(record, 'listContent')), '\n'),
     JSONExtractString(record, 'textContent')) as text,
  arrayMap(x -> (JSONExtractString(x, 'text'), JSONExtractBool(x, 'isChecked')),
           JSONExtractArrayRaw(record, 'listContent')) as items,
  arrayMap(x -> JSONExtractString(x, 'name'), JSONExtractArrayRaw(record, 'labels')) as labels,
  -- Each attachment's row in ods.files, in the note's order, once the file
  -- is stored.
  arrayMap(i -> concat('google/keep:', id, '/', toString(i)),
           arrayEnumerate(JSONExtractArrayRaw(record, 'attachments'))) as attachment_file_keys,
  JSONExtractBool(record, 'isPinned') as is_pinned,
  JSONExtractBool(record, 'isArchived') as is_archived,
  JSONExtractBool(record, 'isTrashed') as is_trashed,
  if(JSONExtractInt(record, 'createdTimestampUsec') > 0,
     fromUnixTimestamp64Micro(JSONExtractInt(record, 'createdTimestampUsec'), 'UTC'), NULL) as created_at,
  if(JSONExtractInt(record, 'userEditedTimestampUsec') > 0,
     fromUnixTimestamp64Micro(JSONExtractInt(record, 'userEditedTimestampUsec'), 'UTC'), NULL) as edited_at,
  extracted_at
from ({{ accumulated_records('google', ['takeout/keep/notes']) }})
