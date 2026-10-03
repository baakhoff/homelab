-- Places: one row per named place - added by hand, or found for a visit.
select
  id as place_id,
  JSONExtractString(record, 'name') as name,
  JSONExtract(record, 'latitude', 'Nullable(Float64)') as lat,
  JSONExtract(record, 'longitude', 'Nullable(Float64)') as lon,
  JSONExtractString(record, 'source') as source,
  JSONExtract(record, 'visits_count', 'Nullable(Int64)') as visits_count,
  arrayMap(t -> JSONExtractString(t, 'name'), JSONExtractArrayRaw(record, 'tags')) as tags,
  {{ ts("JSONExtractString(record, 'created_at')") }} as created_at,
  extracted_at
from ({{ snapshot_records('dawarich', 'places') }})
