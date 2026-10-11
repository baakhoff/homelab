-- One row per note: its path in the space, its text, and when it was
-- created and last changed. SilverBullet reports both times as Unix
-- milliseconds. A page deleted in SilverBullet is gone from the next
-- snapshot, and so from here.
select
  id as page,
  replaceRegexpOne(id, '\\.md$', '') as title,
  JSONExtractString(record, 'content') as content,
  JSONExtractUInt(record, 'size') as size_bytes,
  fromUnixTimestamp64Milli(JSONExtractInt(record, 'created'), 'UTC') as created_at,
  fromUnixTimestamp64Milli(JSONExtractInt(record, 'lastModified'), 'UTC') as updated_at,
  extracted_at
from ({{ snapshot_records('silverbullet', 'pages') }})
