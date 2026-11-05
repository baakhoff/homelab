-- One row per play from Plex's watch history: what was watched - a film, or
-- a series' episode with its season and number - by which Plex account, on
-- which device, and when. A play removed from Plex's history drops out.
select
  id as history_key,
  JSONExtractString(record, 'ratingKey') as item_key,
  JSONExtractString(record, 'type') as type,
  JSONExtractString(record, 'title') as title,
  nullIf(JSONExtractString(record, 'grandparentTitle'), '') as series,
  JSONExtract(record, 'parentIndex', 'Nullable(UInt32)') as season,
  JSONExtract(record, 'index', 'Nullable(UInt32)') as episode,
  JSONExtractString(record, 'librarySectionID') as library_key,
  JSONExtractUInt(record, 'accountID') as account_id,
  JSONExtractUInt(record, 'deviceID') as device_id,
  toDateTime(JSONExtractUInt(record, 'viewedAt'), 'UTC') as viewed_at,
  extracted_at
from ({{ snapshot_records('plex', 'status/sessions/history/all') }})
