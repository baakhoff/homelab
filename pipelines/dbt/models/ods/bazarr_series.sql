-- One row per series Bazarr knows from Sonarr: how many of its episodes
-- are in the library, and how many of those still lack a subtitle the
-- profile wants.
select
  toUInt64OrZero(id) as series_id,
  JSONExtractString(record, 'title') as title,
  JSONExtractUInt(record, 'episodeFileCount') as episodes_in_library,
  JSONExtractUInt(record, 'episodeMissingCount') as episodes_missing_subtitles,
  JSONExtractBool(record, 'monitored') as monitored,
  extracted_at
from ({{ snapshot_records('bazarr', 'series') }})
