-- Google Fit's recorded activities - walks, runs, rides, workouts - one row
-- each, from Takeout exports. `metrics` holds every total Fit kept for the
-- session by name; the common ones have columns. The GPS tracks
-- (Activities/*.tcx) are not loaded.
with sessions as (
  select
    id,
    record,
    extracted_at,
    arrayMap(a -> (
      JSONExtractString(a, 'metricName'),
      if(JSONHas(a, 'floatValue'), JSONExtractFloat(a, 'floatValue'), toFloat64(JSONExtractInt(a, 'intValue')))
    ), JSONExtractArrayRaw(record, 'aggregate')) as metric_list
  from ({{ accumulated_records('google', ['takeout/fit/sessions']) }})
)
select
  id as session_key,
  JSONExtractString(record, 'fitnessActivity') as activity,
  {{ ts("JSONExtractString(record, 'startTime')") }} as started_at,
  {{ ts("JSONExtractString(record, 'endTime')") }} as ended_at,
  toFloat64OrNull(replaceOne(JSONExtractString(record, 'duration'), 's', '')) as duration_s,
  nullIf(JSONExtractString(record, 'application', 'packageName'), '') as recorded_by,
  nullIf(arrayFirst(m -> m.1 like '%step_count%', metric_list).2, 0) as steps,
  nullIf(arrayFirst(m -> m.1 like '%distance%', metric_list).2, 0) as distance_m,
  nullIf(arrayFirst(m -> m.1 like '%calories%', metric_list).2, 0) as calories_kcal,
  nullIf(arrayFirst(m -> m.1 like '%heart_minutes%', metric_list).2, 0) as heart_points,
  CAST(metric_list, 'Map(String, Float64)') as metrics,
  extracted_at
from sessions
