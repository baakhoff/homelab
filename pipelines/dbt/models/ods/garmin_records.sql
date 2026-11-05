-- Every Garmin record, one row each, as it came - those with a model of
-- their own (the days' summaries and sleep, activities, weigh-ins) and the
-- rest: the days' stress, Body Battery, heart rate, breathing, SpO2, steps
-- and HRV minute by minute, training status, VO2 max, hydration, blood
-- pressure; the snapshots of devices, personal records, badges, goals and
-- workouts; every item of the export's JSON files; the FIT files' laps,
-- lengths, splits, sets and HRV. `endpoint` says which - daily/<what>,
-- snapshot/<what>, export/<area>/<kind>, fit/<message> - and `record_key`
-- is the day for a daily record. Each record's newest copy; a snapshot's
-- item gone from Garmin stays. Only the FIT files' second-by-second
-- records are left out: they are garmin_fit_records.
--
-- Here so the rest can be read from ods, which brand and CloudBeaver see,
-- until a model of its own is worth it.
select
  id as record_key,
  endpoint,
  file,
  record,
  extracted_at
from (
  select
    JSONExtractString(payload, 'id') as id,
    JSONExtractString(payload, 'endpoint') as endpoint,
    JSONExtractString(payload, 'file') as file,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'garmin') }}
  where JSONExtractString(payload, 'endpoint') != 'fit/record'
  order by kafka_ts desc
  limit 1 by endpoint, id
)
