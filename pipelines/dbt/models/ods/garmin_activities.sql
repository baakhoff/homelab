-- Garmin Connect's activities - runs, rides, walks, swims, workouts - one
-- row each, as Garmin Connect lists them now: from ingest_garmin, which
-- lists the last week's every run and the history once. Each activity's
-- newest copy; one deleted in Garmin Connect stays. `record` holds every
-- total Garmin keeps; the common ones have columns. The second-by-second
-- recording is in garmin_fit_records, from the export.
select
  toInt64(id) as activity_id,
  JSONExtractString(record, 'activityName') as name,
  JSONExtractString(record, 'activityType', 'typeKey') as activity_type,
  {{ ts("JSONExtractString(record, 'startTimeGMT')") }} as started_at,
  -- The wall clock where it was, kept as if it were UTC.
  parseDateTime64BestEffortOrNull(JSONExtractString(record, 'startTimeLocal'), 3, 'UTC') as started_at_local,
  JSONExtract(record, 'duration', 'Nullable(Float64)') as duration_s,
  JSONExtract(record, 'movingDuration', 'Nullable(Float64)') as moving_s,
  JSONExtract(record, 'distance', 'Nullable(Float64)') as distance_m,
  JSONExtract(record, 'calories', 'Nullable(Float64)') as calories_kcal,
  JSONExtract(record, 'averageHR', 'Nullable(Float64)') as avg_heart_rate,
  JSONExtract(record, 'maxHR', 'Nullable(Float64)') as max_heart_rate,
  JSONExtract(record, 'averageSpeed', 'Nullable(Float64)') as avg_speed_mps,
  JSONExtract(record, 'elevationGain', 'Nullable(Float64)') as ascent_m,
  JSONExtract(record, 'elevationLoss', 'Nullable(Float64)') as descent_m,
  JSONExtract(record, 'steps', 'Nullable(Int64)') as steps,
  JSONExtract(record, 'aerobicTrainingEffect', 'Nullable(Float64)') as aerobic_effect,
  JSONExtract(record, 'anaerobicTrainingEffect', 'Nullable(Float64)') as anaerobic_effect,
  JSONExtract(record, 'vO2MaxValue', 'Nullable(Float64)') as vo2max,
  nullIf(JSONExtractString(record, 'locationName'), '') as location,
  JSONExtract(record, 'startLatitude', 'Nullable(Float64)') as start_lat,
  JSONExtract(record, 'startLongitude', 'Nullable(Float64)') as start_lon,
  record,
  extracted_at
from ({{ accumulated_records('garmin', ['activities']) }})
where toInt64OrZero(id) != 0
