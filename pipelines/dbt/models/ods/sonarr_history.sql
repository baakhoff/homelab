-- One row per event in Sonarr's history, as radarr_history is for films:
-- grabbed, imported, failed, deleted - per episode, with the release's name
-- and quality.
select
  toUInt64OrZero(id) as event_id,
  JSONExtractUInt(record, 'seriesId') as series_id,
  JSONExtractUInt(record, 'episodeId') as episode_id,
  JSONExtractString(record, 'eventType') as event_type,
  JSONExtractString(record, 'sourceTitle') as release,
  nullIf(JSONExtractString(record, 'quality', 'quality', 'name'), '') as quality,
  {{ ts("JSONExtractString(record, 'date')") }} as happened_at,
  extracted_at
from ({{ snapshot_records('sonarr', 'history') }})
