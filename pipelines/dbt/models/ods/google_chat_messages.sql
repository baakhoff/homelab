-- Google Chat (and old Hangouts) messages, one row each, from Takeout
-- exports. `conversation` is Takeout's folder name for the chat ("DM ...",
-- "Space ..."). Google writes the time as English prose - "Monday, March
-- 4, 2024 at 10:00:00 AM UTC" - kept as `created_text`, and read into
-- `created_at` as well as it parses.
select
  id as message_id,
  JSONExtractString(record, '_dir') as conversation,
  JSONExtractString(record, 'creator', 'name') as creator_name,
  lower(JSONExtractString(record, 'creator', 'email')) as creator_email,
  JSONExtractString(record, 'text') as text,
  nullIf(JSONExtractString(record, 'topic_id'), '') as topic_id,
  JSONExtractString(record, 'created_date') as created_text,
  parseDateTime64BestEffortOrNull(
    replaceRegexpAll(replaceAll(JSONExtractString(record, 'created_date'), unhex('E280AF'), ' '), '^[A-Za-z]+, | at', ''),
    3, 'UTC') as created_at,
  extracted_at
from ({{ accumulated_records('google', ['takeout/chat/messages']) }})
where JSONHas(record, 'message_id')
