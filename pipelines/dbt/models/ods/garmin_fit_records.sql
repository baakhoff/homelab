{{ config(materialized='incremental', incremental_strategy='append', order_by='(fit, ts)', partition_by='toYear(ts)') }}

-- Every second, or every few, of every activity a watch recorded: one row
-- per FIT record message of the FIT files in a Garmin export
-- (pipelines/tools/garmin_pack.py) - time, position, heart rate, speed,
-- cadence, power, altitude, distance so far, temperature. `fit` is the
-- file, as in garmin_fit_sessions. Millions of rows, so incremental: each
-- run adds the records not here yet. The FIT SDK's names; speed and
-- altitude are the enhanced fields where the watch wrote them.
--
-- Partitioned by year, not month, as dawarich_points: the first load
-- inserts the whole history at once.
with rows as (
  select
    JSONExtractString(payload, 'id') as record_key,
    JSONExtractRaw(payload, 'record') as record,
    ingested_at
  from {{ source('raw', 'garmin') }}
  where JSONExtractString(payload, 'endpoint') = 'fit/record'
  {% if is_incremental() -%}
    and ingested_at > (select max(ingested_at) from {{ this }})
  {%- endif %}
)
select
  record_key,
  JSONExtractString(record, 'fit') as fit,
  parseDateTime64BestEffort(JSONExtractString(record, 'timestamp'), 0, 'UTC') as ts,
  JSONExtract(record, 'position_lat', 'Nullable(Float64)') as lat,
  JSONExtract(record, 'position_long', 'Nullable(Float64)') as lon,
  JSONExtract(record, 'heart_rate', 'Nullable(Int64)') as heart_rate,
  coalesce(JSONExtract(record, 'enhanced_speed', 'Nullable(Float64)'),
           JSONExtract(record, 'speed', 'Nullable(Float64)')) as speed_mps,
  JSONExtract(record, 'cadence', 'Nullable(Int64)') as cadence,
  JSONExtract(record, 'power', 'Nullable(Int64)') as power_w,
  coalesce(JSONExtract(record, 'enhanced_altitude', 'Nullable(Float64)'),
           JSONExtract(record, 'altitude', 'Nullable(Float64)')) as altitude_m,
  JSONExtract(record, 'distance', 'Nullable(Float64)') as distance_m,
  JSONExtract(record, 'temperature', 'Nullable(Int64)') as temperature_c,
  ingested_at
from rows
where parseDateTime64BestEffortOrNull(JSONExtractString(record, 'timestamp'), 0, 'UTC') is not null
{% if is_incremental() -%}
  and record_key not in (select record_key from {{ this }})
{%- endif %}
order by ingested_at desc
limit 1 by record_key
