-- Garmin Connect's weigh-ins - a scale, or typed in - one row each:
-- weight, BMI, body fat and water, bone and muscle mass. Garmin keeps
-- weights in grams; here they are kilograms.
with days as (
  select record from ({{ accumulated_records('garmin', ['daily/weigh_ins']) }})
),
weighs as (
  select arrayJoin(
    arrayConcat(
      JSONExtractArrayRaw(record, 'dateWeightList'),
      arrayFlatten(arrayMap(x -> JSONExtractArrayRaw(x, 'allWeightMetrics'),
                            JSONExtractArrayRaw(record, 'dailyWeightSummaries')))
    )
  ) as w
  from days
)
select
  JSONExtract(w, 'samplePk', 'Int64') as weigh_in_id,
  fromUnixTimestamp64Milli(if(JSONExtract(w, 'timestampGMT', 'Int64') > 0,
                              JSONExtract(w, 'timestampGMT', 'Int64'),
                              JSONExtract(w, 'date', 'Int64')), 'UTC') as weighed_at,
  toDateOrNull(JSONExtractString(w, 'calendarDate')) as day,
  JSONExtract(w, 'weight', 'Nullable(Float64)') / 1000 as weight_kg,
  JSONExtract(w, 'bmi', 'Nullable(Float64)') as bmi,
  JSONExtract(w, 'bodyFat', 'Nullable(Float64)') as body_fat_pct,
  JSONExtract(w, 'bodyWater', 'Nullable(Float64)') as body_water_pct,
  JSONExtract(w, 'boneMass', 'Nullable(Float64)') / 1000 as bone_mass_kg,
  JSONExtract(w, 'muscleMass', 'Nullable(Float64)') / 1000 as muscle_mass_kg,
  nullIf(JSONExtractString(w, 'sourceType'), '') as source
from weighs
where weigh_in_id != 0
order by weighed_at desc
limit 1 by weigh_in_id
