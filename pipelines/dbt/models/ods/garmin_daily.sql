-- Garmin Connect, one row per day: steps, distance, calories, floors,
-- intensity minutes, heart rate, stress, Body Battery, SpO2, breathing,
-- the night's sleep and HRV, and the morning's training readiness - from
-- ingest_garmin (pipelines/dags/garmin.py), which reads each day again
-- for a few days, so a day synced late is filled in. Each day's newest
-- copy. Days the watch recorded nothing are not here.
with summary as (
  select id as day_text, record from ({{ accumulated_records('garmin', ['daily/summary']) }})
),
sleep as (
  select id as day_text, record from ({{ accumulated_records('garmin', ['daily/sleep']) }})
),
hrv as (
  select id as day_text, record from ({{ accumulated_records('garmin', ['daily/hrv']) }})
),
readiness as (
  select id as day_text, record from ({{ accumulated_records('garmin', ['daily/training_readiness']) }})
)
select
  toDate(s.day_text) as day,
  JSONExtract(s.record, 'totalSteps', 'Nullable(Int64)') as steps,
  JSONExtract(s.record, 'dailyStepGoal', 'Nullable(Int64)') as step_goal,
  JSONExtract(s.record, 'totalDistanceMeters', 'Nullable(Float64)') as distance_m,
  JSONExtract(s.record, 'totalKilocalories', 'Nullable(Float64)') as calories_kcal,
  JSONExtract(s.record, 'activeKilocalories', 'Nullable(Float64)') as active_kcal,
  JSONExtract(s.record, 'floorsAscended', 'Nullable(Float64)') as floors,
  JSONExtract(s.record, 'moderateIntensityMinutes', 'Nullable(Int64)') as moderate_minutes,
  JSONExtract(s.record, 'vigorousIntensityMinutes', 'Nullable(Int64)') as vigorous_minutes,
  JSONExtract(s.record, 'restingHeartRate', 'Nullable(Int64)') as resting_heart_rate,
  JSONExtract(s.record, 'minHeartRate', 'Nullable(Int64)') as min_heart_rate,
  JSONExtract(s.record, 'maxHeartRate', 'Nullable(Int64)') as max_heart_rate,
  -- Garmin writes -1 and -2 for "not enough data" and "activity".
  nullIf(greatest(JSONExtract(s.record, 'averageStressLevel', 'Nullable(Int64)'), -1), -1) as stress_avg,
  nullIf(greatest(JSONExtract(s.record, 'maxStressLevel', 'Nullable(Int64)'), -1), -1) as stress_max,
  JSONExtract(s.record, 'bodyBatteryHighestValue', 'Nullable(Int64)') as body_battery_high,
  JSONExtract(s.record, 'bodyBatteryLowestValue', 'Nullable(Int64)') as body_battery_low,
  JSONExtract(s.record, 'bodyBatteryChargedValue', 'Nullable(Int64)') as body_battery_charged,
  JSONExtract(s.record, 'bodyBatteryDrainedValue', 'Nullable(Int64)') as body_battery_drained,
  JSONExtract(s.record, 'averageSpo2', 'Nullable(Float64)') as spo2_avg,
  JSONExtract(s.record, 'lowestSpo2', 'Nullable(Float64)') as spo2_low,
  JSONExtract(s.record, 'avgWakingRespirationValue', 'Nullable(Float64)') as respiration_waking,
  JSONExtract(sl.record, 'dailySleepDTO', 'sleepTimeSeconds', 'Nullable(Int64)') as sleep_seconds,
  JSONExtract(sl.record, 'dailySleepDTO', 'sleepScores', 'overall', 'value', 'Nullable(Int64)') as sleep_score,
  JSONExtract(h.record, 'hrvSummary', 'lastNightAvg', 'Nullable(Float64)') as hrv_last_night,
  JSONExtract(h.record, 'hrvSummary', 'weeklyAvg', 'Nullable(Float64)') as hrv_weekly,
  nullIf(JSONExtractString(h.record, 'hrvSummary', 'status'), '') as hrv_status,
  -- One reading per morning, sometimes another later; the first is the morning's.
  JSONExtract(arrayElement(JSONExtractArrayRaw(r.record), 1), 'score', 'Nullable(Int64)') as training_readiness,
  s.record as summary
from summary s
left join sleep sl on sl.day_text = s.day_text
left join hrv h on h.day_text = s.day_text
left join readiness r on r.day_text = s.day_text
where toDateOrNull(s.day_text) is not null
