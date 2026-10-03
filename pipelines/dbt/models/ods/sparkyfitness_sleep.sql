-- Nights: one row per sleep entry, from the phone or typed in.
select
  id as sleep_id,
  toDateOrNull(JSONExtractString(record, 'entry_date')) as entry_date,
  {{ ts("JSONExtractString(record, 'bedtime')") }} as bedtime,
  {{ ts("JSONExtractString(record, 'wake_time')") }} as wake_time,
  JSONExtract(record, 'duration_in_seconds', 'Nullable(Int64)') as duration_seconds,
  JSONExtract(record, 'time_asleep_in_seconds', 'Nullable(Int64)') as asleep_seconds,
  JSONExtract(record, 'deep_sleep_seconds', 'Nullable(Int64)') as deep_seconds,
  JSONExtract(record, 'rem_sleep_seconds', 'Nullable(Int64)') as rem_seconds,
  JSONExtract(record, 'sleep_score', 'Nullable(Float64)') as sleep_score,
  JSONExtract(record, 'resting_heart_rate', 'Nullable(Float64)') as resting_heart_rate,
  JSONExtractString(record, 'source') as source,
  extracted_at
from ({{ snapshot_records('sparkyfitness', 'sleep') }})
