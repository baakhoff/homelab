-- How CloudBeaver was used, per day and database: statements run, how many
-- failed, the time they took, and on ClickHouse what they read. CloudBeaver's
-- own catalog reads count too - browsing is queries.
select
  toDate(event_time) as day,
  'clickhouse' as server,
  current_database as database,
  count() as statements,
  countIf(error_code != 0) as errors,
  toFloat64(sum(duration_ms)) / 1000 as seconds,
  sum(read_rows) as read_rows,
  sum(read_bytes) as read_bytes
from {{ ref('cloudbeaver_clickhouse_queries') }}
group by day, database

union all

select
  toDate(ts) as day,
  server,
  database,
  countIf(kind in ('statement', 'execute')) as statements,
  countIf(kind = 'error') as errors,
  toFloat64(ifNull(sumIf(duration_ms, kind in ('statement', 'execute', 'parse', 'bind')), 0)) / 1000 as seconds,
  toUInt64(0) as read_rows,
  toUInt64(0) as read_bytes
from {{ ref('cloudbeaver_postgres_log') }}
group by day, server, database
