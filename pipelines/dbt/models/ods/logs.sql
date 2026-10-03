{{ config(materialized='incremental', incremental_strategy='append', order_by='(namespace, ts)', partition_by='toYYYYMM(ts)', ttl='toDateTime(ts) + INTERVAL 90 DAY') }}

-- Every pod log line with its Kubernetes coordinates. Kept 90 days, like
-- raw.logs beneath it.
select
  ts,
  attrs['namespace'] as namespace,
  attrs['pod'] as pod,
  attrs['container'] as container,
  attrs['node'] as node,
  body,
  -- A rough severity, from the line itself: most containers log no level
  -- field, and this is the question asked of them most.
  multiIf(
    match(body, '(?i)\\b(panic|fatal|critical)\\b'), 'fatal',
    match(body, '(?i)\\b(error|err|exception|traceback)\\b'), 'error',
    match(body, '(?i)\\b(warn|warning)\\b'), 'warning',
    'info'
  ) as level,
  ingested_at
from ({{ otlp_records('logs') }})
