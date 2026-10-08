{{ config(materialized='incremental', incremental_strategy='append', order_by='(event_time, query_id)', partition_by='toYYYYMM(event_time)') }}

-- Every query CloudBeaver ran on ClickHouse, finished or failed: one row per
-- query, from the server's own system.query_log (pipelines/dags/cloudbeaver.py).
-- The text, the tables touched, the time taken, the rows and bytes read and
-- returned - never the results. CloudBeaver's own catalog reads are here
-- too: browsing the tree is queries against system.*.
--
-- The DAG reads ten minutes back each run, so most queries arrive twice;
-- each run adds the ones not here yet.
with rows as (
  select
    JSONExtractString(payload, 'id') as id,
    JSONExtractRaw(payload, 'record') as record,
    ingested_at
  from {{ source('raw', 'cloudbeaver') }}
  where JSONExtractString(payload, 'endpoint') = 'clickhouse-queries'
  {% if is_incremental() -%}
    and ingested_at > (select max(ingested_at) from {{ this }})
  {%- endif %}
)
select
  id,
  JSONExtractString(record, 'query_id') as query_id,
  parseDateTime64BestEffort(JSONExtractString(record, 'event_time'), 6, 'UTC') as event_time,
  -- QueryFinish, or the stage it failed at: ExceptionBeforeStart (did not
  -- parse, not allowed) or ExceptionWhileProcessing.
  JSONExtractString(record, 'type') as status,
  JSONExtractString(record, 'query_kind') as query_kind,
  JSONExtractString(record, 'current_database') as current_database,
  JSONExtract(record, 'databases', 'Array(String)') as databases,
  JSONExtract(record, 'tables', 'Array(String)') as tables,
  JSONExtractString(record, 'query') as query,
  JSONExtractString(record, 'normalized_query_hash') as normalized_query_hash,
  JSONExtractUInt(record, 'query_duration_ms') as duration_ms,
  JSONExtractUInt(record, 'read_rows') as read_rows,
  JSONExtractUInt(record, 'read_bytes') as read_bytes,
  JSONExtractUInt(record, 'result_rows') as result_rows,
  JSONExtractUInt(record, 'result_bytes') as result_bytes,
  JSONExtractInt(record, 'memory_usage') as memory_bytes,
  JSONExtractInt(record, 'exception_code') as error_code,
  JSONExtractString(record, 'exception') as error,
  JSONExtractString(record, 'http_user_agent') as client,
  ingested_at
from rows
where id != ''
{% if is_incremental() -%}
  and id not in (select id from {{ this }})
{%- endif %}
order by ingested_at desc
limit 1 by id
