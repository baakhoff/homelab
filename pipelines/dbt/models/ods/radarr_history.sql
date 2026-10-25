-- One row per event in Radarr's history: a release grabbed, a download
-- imported into the library, a download that failed, a file deleted - with
-- the release's name and quality.
select
  toUInt64OrZero(id) as event_id,
  JSONExtractUInt(record, 'movieId') as film_id,
  JSONExtractString(record, 'eventType') as event_type,
  JSONExtractString(record, 'sourceTitle') as release,
  nullIf(JSONExtractString(record, 'quality', 'quality', 'name'), '') as quality,
  {{ ts("JSONExtractString(record, 'date')") }} as happened_at,
  extracted_at
from ({{ snapshot_records('radarr', 'history') }})
