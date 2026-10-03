-- Body check-ins: one row per day's check-in - weight, measurements, steps.
select
  id as checkin_id,
  toDateOrNull(JSONExtractString(record, 'entry_date')) as entry_date,
  JSONExtract(record, 'weight', 'Nullable(Float64)') as weight,
  JSONExtract(record, 'body_fat_percentage', 'Nullable(Float64)') as body_fat_percentage,
  JSONExtract(record, 'waist', 'Nullable(Float64)') as waist,
  JSONExtract(record, 'hips', 'Nullable(Float64)') as hips,
  JSONExtract(record, 'neck', 'Nullable(Float64)') as neck,
  JSONExtract(record, 'height', 'Nullable(Float64)') as height,
  JSONExtract(record, 'steps', 'Nullable(Int64)') as steps,
  {{ ts("JSONExtractString(record, 'updated_at')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('sparkyfitness', 'measurements/check-in-measurements-range') }})
