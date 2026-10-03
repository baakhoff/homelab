-- Stays: one row per visit Dawarich detected, or one entered by hand - a
-- stretch of time spent at one place or area. Suggested visits wait for a
-- confirm or decline in Dawarich; declined ones are kept here with their
-- status.
select
  id as visit_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'status') as status,
  {{ ts("JSONExtractString(record, 'started_at')") }} as started_at,
  {{ ts("JSONExtractString(record, 'ended_at')") }} as ended_at,
  JSONExtract(record, 'duration', 'Nullable(Int64)') as duration_minutes,
  JSONExtract(record, 'place', 'id', 'Nullable(Int64)') as place_id,
  JSONExtract(record, 'area_id', 'Nullable(Int64)') as area_id,
  JSONExtract(record, 'place', 'latitude', 'Nullable(Float64)') as lat,
  JSONExtract(record, 'place', 'longitude', 'Nullable(Float64)') as lon,
  extracted_at
from ({{ snapshot_records('dawarich', 'visits') }})
