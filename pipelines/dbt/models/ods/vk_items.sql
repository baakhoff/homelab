-- Everything else in the VK data archive, one row per entry: wall posts,
-- comments, likes, bookmarks, profile details, sign-in sessions, apps, ad
-- interests, the video and photo lists. `section` is the archive's folder
-- (wall, comments, likes, ...); `text` the entry as shown, `links` its
-- links, `happened_at_local` the first date in it, in the account's time
-- zone. Photos and videos are their links only - the files were never in
-- the archive.
select
  id as item_key,
  JSONExtractString(record, 'section') as section,
  JSONExtractString(record, 'page') as page,
  JSONExtractInt(record, 'position') as position,
  JSONExtractString(record, 'text') as text,
  parseDateTimeBestEffortOrNull(JSONExtractString(record, 'time')) as happened_at_local,
  JSONExtract(record, 'links', 'Array(String)') as links,
  arrayMap(a -> JSONExtractString(a, 'description'), JSONExtractArrayRaw(record, 'attachments')) as attachments,
  extracted_at
from ({{ accumulated_records('vk', ['vk/items']) }})
