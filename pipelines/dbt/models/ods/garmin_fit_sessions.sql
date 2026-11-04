-- The activities as the watch recorded them, one row per session of each
-- FIT file in a Garmin export (pipelines/tools/garmin_pack.py): sport,
-- start, time, distance, calories, heart rate, ascent. A multisport
-- activity is a session per leg. `fit` is the file, and the key into
-- garmin_fit_records; `activity_id` the Garmin Connect activity that
-- started the same second, when there is one.
with sessions as (
  select
    id,
    JSONExtractString(record, 'fit') as fit,
    record,
    file,
    parseDateTime64BestEffortOrNull(JSONExtractString(record, 'start_time'), 3, 'UTC') as started_at,
    extracted_at
  from ({{ accumulated_records('garmin', ['fit/session']) }})
),
activities as (
  select toInt64(id) as activity_id,
         {{ ts("JSONExtractString(record, 'startTimeGMT')") }} as started_at
  from ({{ accumulated_records('garmin', ['activities']) }})
  where toInt64OrZero(id) != 0
)
select
  s.id as session_key,
  s.fit,
  s.file,
  JSONExtract(s.record, 'index', 'Int64') as session_index,
  nullIf(a.activity_id, 0) as activity_id,
  JSONExtractString(s.record, 'sport') as sport,
  nullIf(JSONExtractString(s.record, 'sub_sport'), '') as sub_sport,
  s.started_at,
  JSONExtract(s.record, 'total_elapsed_time', 'Nullable(Float64)') as elapsed_s,
  JSONExtract(s.record, 'total_timer_time', 'Nullable(Float64)') as timer_s,
  JSONExtract(s.record, 'total_distance', 'Nullable(Float64)') as distance_m,
  JSONExtract(s.record, 'total_calories', 'Nullable(Float64)') as calories_kcal,
  JSONExtract(s.record, 'avg_heart_rate', 'Nullable(Float64)') as avg_heart_rate,
  JSONExtract(s.record, 'max_heart_rate', 'Nullable(Float64)') as max_heart_rate,
  JSONExtract(s.record, 'total_ascent', 'Nullable(Float64)') as ascent_m,
  s.record,
  s.extracted_at
from sessions s
left join activities a on a.started_at = s.started_at
