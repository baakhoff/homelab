{{ config(materialized='incremental', incremental_strategy='append', order_by='(ts)', partition_by='toYYYYMM(ts)') }}

-- Every Kubernetes event. The collector writes each event as a JSON body;
-- the common fields are pulled out and the whole body kept beside them.
select
  ts,
  JSONExtractString(body, 'type') as type,
  JSONExtractString(body, 'reason') as reason,
  JSONExtractString(body, 'kind') as kind,
  JSONExtractString(body, 'name') as name,
  coalesce(nullIf(attrs['namespace'], ''), JSONExtractString(body, 'namespace')) as namespace,
  JSONExtractString(body, 'msg') as message,
  body,
  ingested_at
from ({{ otlp_records('k8s_events') }})
