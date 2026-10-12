{{ config(materialized='table', order_by='(source, found_at)') }}

-- Everything the pipelines masked, in one place: one row per record, log
-- line or event in which something was found - which source, which record,
-- what kinds (card, private_key, password, ...) and, for the ingest jobs,
-- the keyed fingerprints of the masked values. The values themselves are
-- nowhere: they were replaced before they left the source
-- (pipelines/sensitive.md).
--
-- A fingerprint is the same wherever the same secret turned up, so
--   select * from ods.sensitive_findings where has(fingerprints, '...')
-- answers "where else did this key appear?". The collectors cannot compute
-- fingerprints, so log lines and events have kinds only.
--
-- A table rebuilt every run rather than a view: a view would read raw as
-- whoever queries it, and the brand agent's user may not read raw.
{% set envelope_sources = ['firefly', 'vikunja', 'mealie', 'paperless', 'sparkyfitness', 'dawarich', 'cloudbeaver', 'outline', 'telegram'] %}
{% for s in envelope_sources %}
select
  '{{ s }}' as source,
  JSONExtractString(payload, 'endpoint') as endpoint,
  JSONExtractString(payload, 'id') as record_id,
  JSONExtract(payload, 'sensitive_kinds', 'Array(String)') as kinds,
  JSONExtract(payload, 'sensitive_fingerprints', 'Array(String)') as fingerprints,
  -- Not Nullable: found_at is in the sorting key, which ClickHouse refuses
  -- to build from a Nullable column. A record without a readable
  -- extracted_at sorts first, at the epoch.
  coalesce(
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC'),
    toDateTime64(0, 3, 'UTC')
  ) as found_at,
  '' as namespace,
  '' as pod
from {{ source('raw', s) }}
where JSONExtractBool(payload, 'sensitive')
union all
{% endfor %}
select
  'logs' as source, container as endpoint, '' as record_id, sensitive_kinds as kinds,
  [] :: Array(String) as fingerprints, ts as found_at, namespace, pod
from {{ ref('logs') }}
where sensitive
union all
select
  'k8s_events' as source, kind as endpoint, name as record_id, sensitive_kinds as kinds,
  [] :: Array(String) as fingerprints, ts as found_at, namespace, '' as pod
from {{ ref('k8s_events') }}
where sensitive
