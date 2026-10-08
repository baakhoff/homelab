{{ config(materialized='incremental', incremental_strategy='append', order_by='(server, ts)', partition_by='toYYYYMM(ts)') }}

-- What CloudBeaver did on the lab's Postgres servers, from their logs: one
-- row per log entry of the `cloudbeaver` role. Each server logs that role's
-- every statement with its duration, its errors, and each session's end
-- with how long it lasted (cloudbeaver-reader.yaml in each namespace). The
-- collectors carry the lines to raw.logs and ods.logs keeps them 90 days;
-- this keeps them for good.
--
-- A line looks like
--   2026-10-08 12:00:00.123 UTC [4242] cloudbeaver@dawarich [DBeaver 26.2.2 - SQLEditor <x>] LOG:  duration: 3.104 ms  execute <unnamed>: SELECT ...
-- Statements over several lines arrive as one entry: the collectors join
-- Postgres's continuation lines (clusters/lab/logging/alloy.yaml).
--
-- kind:
--   statement / execute  a statement run, with its duration; JDBC sends
--                        most as execute, after a parse and a bind
--   parse / bind         the steps before an execute, with their own times
--   error                the statement failed; the next row, kind
--                        failed_statement, is its text
--   disconnection        a session ended; session_s is how long it lasted,
--                        so ts - session_s is when it began
--   detail               the parameters of the statement before it
with lines as (
  select
    namespace,
    body,
    ingested_at,
    extractGroups(body,
      '(?s)^(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3}) \\w+ \\[(\\d+)\\] ([^@ ]*)@(\\S*) \\[(.*?)\\] ([A-Z]+):  (.*)$'
    ) as g
  from {{ ref('logs') }}
  where container = 'postgres'
    and namespace in ('airflow', 'sparkyfitness', 'dawarich', 'epicurus')
    and position(body, ' cloudbeaver@') > 0
  {% if is_incremental() -%}
    and ingested_at > (select max(ingested_at) from {{ this }})
  {%- endif %}
),
parsed as (
  select
    namespace as server,
    -- %m is the server's time zone; every server here runs in UTC.
    parseDateTime64BestEffort(g[1], 3, 'UTC') as ts,
    toUInt32OrZero(g[2]) as pid,
    g[4] as database,
    g[5] as application,
    g[6] as severity,
    g[7] as message,
    ingested_at
  from lines
  where length(g) = 7 and g[3] = 'cloudbeaver'
)
select
  server,
  ts,
  pid,
  database,
  application,
  severity,
  multiIf(
    match(message, '^duration: [0-9.]+ ms  statement: '), 'statement',
    match(message, '^duration: [0-9.]+ ms  execute '), 'execute',
    match(message, '^duration: [0-9.]+ ms  parse '), 'parse',
    match(message, '^duration: [0-9.]+ ms  bind '), 'bind',
    startsWith(message, 'disconnection: '), 'disconnection',
    severity in ('ERROR', 'FATAL'), 'error',
    severity = 'STATEMENT', 'failed_statement',
    severity = 'DETAIL', 'detail',
    'other'
  ) as kind,
  toFloat64OrNull(extract(message, '^duration: ([0-9.]+) ms')) as duration_ms,
  multiIf(
    kind in ('statement', 'execute', 'parse', 'bind'),
      extract(message, '(?s)^duration: [0-9.]+ ms  (?:statement|execute [^:]*|parse [^:]*|bind [^:]*): (.*)$'),
    kind = 'failed_statement', message,
    ''
  ) as query,
  if(kind = 'error', message, '') as error,
  if(kind = 'disconnection',
     toUInt32OrZero(extract(message, 'session time: (\\d+):')) * 3600
       + toUInt32OrZero(extract(message, 'session time: \\d+:(\\d+):')) * 60
       + toFloat64OrZero(extract(message, 'session time: \\d+:\\d+:([0-9.]+)')),
     NULL) as session_s,
  if(kind = 'disconnection', extract(message, ' host=(\\S+)'), '') as client_address,
  message,
  ingested_at
from parsed
