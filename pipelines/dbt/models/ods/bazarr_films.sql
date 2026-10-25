-- One row per film Bazarr knows from Radarr: the subtitle languages it
-- has for it and the ones its profile still wants, as two-letter codes.
select
  toUInt64OrZero(id) as film_id,
  JSONExtractString(record, 'title') as title,
  arrayMap(x -> JSONExtractString(x, 'code2'), JSONExtractArrayRaw(record, 'subtitles')) as subtitles,
  arrayMap(x -> JSONExtractString(x, 'code2'), JSONExtractArrayRaw(record, 'missing_subtitles')) as missing_subtitles,
  JSONExtractBool(record, 'monitored') as monitored,
  extracted_at
from ({{ snapshot_records('bazarr', 'movies') }})
