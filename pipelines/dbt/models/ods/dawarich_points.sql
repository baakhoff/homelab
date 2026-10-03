{{ config(materialized='incremental', incremental_strategy='append', order_by='(point_id)', partition_by='toYear(ts)') }}

-- Where the phone was: one row per location point. Not a snapshot like the
-- other API sources - the ingest DAG sends the last week of points each day
-- (pipelines/dags/ingest.py), so most arrive several times. Each run adds
-- the points not here yet and skips the rest, so a point is kept as it was
-- first seen: one edited or deleted in Dawarich afterwards stays as it was.
--
-- Anomalies (points Dawarich flagged as GPS jumps) are not sent.
--
-- Partitioned by year, not month: the run after an import of old history
-- inserts every point at once, and ClickHouse refuses an insert that spans
-- more than 100 partitions - nine years of months.
with rows as (
  select
    toUInt64OrZero(JSONExtractString(payload, 'id')) as point_id,
    JSONExtractRaw(payload, 'record') as record,
    ingested_at
  from {{ source('raw', 'dawarich') }}
  where JSONExtractString(payload, 'endpoint') = 'points'
  {% if is_incremental() -%}
    and ingested_at > (select max(ingested_at) from {{ this }})
  {%- endif %}
)
select
  point_id,
  toDateTime(toUInt32(JSONExtractUInt(record, 'timestamp')), 'UTC') as ts,
  toFloat64OrNull(JSONExtractString(record, 'latitude')) as lat,
  toFloat64OrNull(JSONExtractString(record, 'longitude')) as lon,
  JSONExtract(record, 'altitude', 'Nullable(Float64)') as altitude_m,
  JSONExtract(record, 'accuracy', 'Nullable(Float64)') as accuracy_m,
  -- A string in the API: whatever the phone app sent, in m/s.
  toFloat64OrNull(JSONExtractString(record, 'velocity')) as velocity,
  JSONExtract(record, 'battery', 'Nullable(Int64)') as battery,
  JSONExtractString(record, 'country_name') as country,
  -- Empty until a reverse-geocoding provider is set in Dawarich.
  JSONExtractString(record, 'city') as city,
  JSONExtractString(record, 'tracker_id') as tracker_id,
  JSONExtract(record, 'track_id', 'Nullable(Int64)') as track_id,
  ingested_at
from rows
where point_id != 0
{% if is_incremental() -%}
  and point_id not in (select point_id from {{ this }})
{%- endif %}
order by ingested_at desc
limit 1 by point_id
