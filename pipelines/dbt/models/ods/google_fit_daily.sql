-- Google Fit, one row per day: steps, distance, calories, move minutes,
-- heart points and heart rate, weight - from Takeout exports (Fit is being
-- shut down; this is its history). Health data from now on comes in
-- through SparkyFitness.
--
-- Takeout gives Fit's days two ways: one summary file with a row per day
-- ("Date"), and a file per day with a row per quarter hour, named after
-- the day. The summary wins; a day only the per-day files have is summed
-- from them. A day in two exports is taken from the newer one only.
with rows as (
  select
    record,
    extracted_at,
    JSONExtractString(record, 'Date') as summary_date,
    toDateOrNull(replaceOne(JSONExtractString(record, '_file'), '.csv', '')) as file_day
  from ({{ accumulated_records('google', ['takeout/fit/daily']) }})
),
summary as (
  select
    toDate(summary_date) as day,
    toFloat64OrNull(JSONExtractString(record, 'Step count')) as steps,
    toFloat64OrNull(JSONExtractString(record, 'Distance (m)')) as distance_m,
    toFloat64OrNull(JSONExtractString(record, 'Calories (kcal)')) as calories_kcal,
    toFloat64OrNull(JSONExtractString(record, 'Move Minutes count')) as move_minutes,
    toFloat64OrNull(JSONExtractString(record, 'Heart Points')) as heart_points,
    toFloat64OrNull(JSONExtractString(record, 'Heart Minutes')) as heart_minutes,
    toFloat64OrNull(JSONExtractString(record, 'Average heart rate (bpm)')) as avg_heart_rate,
    toFloat64OrNull(JSONExtractString(record, 'Max heart rate (bpm)')) as max_heart_rate,
    toFloat64OrNull(JSONExtractString(record, 'Min heart rate (bpm)')) as min_heart_rate,
    toFloat64OrNull(JSONExtractString(record, 'Average weight (kg)')) as avg_weight_kg
  from rows
  where toDateOrNull(summary_date) is not null
  order by extracted_at desc
  limit 1 by day
),
quarters as (
  select
    file_day as day,
    sum(toFloat64OrNull(JSONExtractString(record, 'Step count'))) as steps,
    sum(toFloat64OrNull(JSONExtractString(record, 'Distance (m)'))) as distance_m,
    sum(toFloat64OrNull(JSONExtractString(record, 'Calories (kcal)'))) as calories_kcal,
    sum(toFloat64OrNull(JSONExtractString(record, 'Move Minutes count'))) as move_minutes,
    sum(toFloat64OrNull(JSONExtractString(record, 'Heart Points'))) as heart_points,
    sum(toFloat64OrNull(JSONExtractString(record, 'Heart Minutes'))) as heart_minutes,
    avg(toFloat64OrNull(JSONExtractString(record, 'Average heart rate (bpm)'))) as avg_heart_rate,
    max(toFloat64OrNull(JSONExtractString(record, 'Max heart rate (bpm)'))) as max_heart_rate,
    min(toFloat64OrNull(JSONExtractString(record, 'Min heart rate (bpm)'))) as min_heart_rate,
    avg(toFloat64OrNull(JSONExtractString(record, 'Average weight (kg)'))) as avg_weight_kg
  from rows
  where summary_date = '' and file_day is not null
    and (file_day, extracted_at) in (
      select file_day, max(extracted_at) from rows where summary_date = '' group by file_day
    )
  group by day
)
select * from summary
union all
select * from quarters
where day not in (select day from summary)
