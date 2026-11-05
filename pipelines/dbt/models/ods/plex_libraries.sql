-- One row per Plex library - Films, Series - and when it was last scanned.
-- Plex writes its times as Unix seconds.
select
  id as library_uuid,
  JSONExtractString(record, 'key') as library_key,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'type') as type,
  JSONExtractString(record, 'language') as language,
  toDateTime(JSONExtractUInt(record, 'createdAt'), 'UTC') as created_at,
  toDateTime(JSONExtractUInt(record, 'scannedAt'), 'UTC') as scanned_at,
  extracted_at
from ({{ snapshot_records('plex', 'library/sections') }})
