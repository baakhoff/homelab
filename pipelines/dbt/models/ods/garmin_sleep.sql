-- Garmin Connect's nights, one row per day the night ended on: when it
-- began and ended, deep, light, REM and awake time, the score, breathing,
-- overnight HRV and stress. From ingest_garmin's daily/sleep; each night's
-- newest copy. `record` is the whole answer, the sleep movement and stages
-- minute by minute included.
with nights as (
  select id as day_text, record, extracted_at
  from ({{ accumulated_records('garmin', ['daily/sleep']) }})
  where JSONExtract(record, 'dailySleepDTO', 'sleepTimeSeconds', 'Nullable(Int64)') > 0
)
select
  toDate(day_text) as day,
  fromUnixTimestamp64Milli(JSONExtract(record, 'dailySleepDTO', 'sleepStartTimestampGMT', 'Int64'), 'UTC') as started_at,
  fromUnixTimestamp64Milli(JSONExtract(record, 'dailySleepDTO', 'sleepEndTimestampGMT', 'Int64'), 'UTC') as ended_at,
  JSONExtract(record, 'dailySleepDTO', 'sleepTimeSeconds', 'Nullable(Int64)') as sleep_seconds,
  JSONExtract(record, 'dailySleepDTO', 'deepSleepSeconds', 'Nullable(Int64)') as deep_seconds,
  JSONExtract(record, 'dailySleepDTO', 'lightSleepSeconds', 'Nullable(Int64)') as light_seconds,
  JSONExtract(record, 'dailySleepDTO', 'remSleepSeconds', 'Nullable(Int64)') as rem_seconds,
  JSONExtract(record, 'dailySleepDTO', 'awakeSleepSeconds', 'Nullable(Int64)') as awake_seconds,
  JSONExtract(record, 'dailySleepDTO', 'sleepScores', 'overall', 'value', 'Nullable(Int64)') as score,
  nullIf(JSONExtractString(record, 'dailySleepDTO', 'sleepScores', 'overall', 'qualifierKey'), '') as quality,
  JSONExtract(record, 'dailySleepDTO', 'averageRespirationValue', 'Nullable(Float64)') as respiration_avg,
  JSONExtract(record, 'dailySleepDTO', 'avgSleepStress', 'Nullable(Float64)') as stress_avg,
  JSONExtract(record, 'avgOvernightHrv', 'Nullable(Float64)') as hrv_avg,
  JSONExtract(record, 'restingHeartRate', 'Nullable(Int64)') as resting_heart_rate,
  record,
  extracted_at
from nights
where toDateOrNull(day_text) is not null
