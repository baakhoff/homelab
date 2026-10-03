{{ config(materialized='incremental', incremental_strategy='append', order_by='(entity_id, last_updated)', partition_by='toYYYYMM(last_updated)') }}

-- Every Home Assistant state change, typed. One row per change, in the
-- order they happened; state_num is the state as a number when it is one
-- (a temperature, a power reading), NULL when it is not ("on", "home").
select
  JSONExtractString(payload, 'entity_id') as entity_id,
  splitByChar('.', entity_id)[1] as domain,
  JSONExtractString(payload, 'state') as state,
  toFloat64OrNull(state) as state_num,
  JSONExtractString(JSONExtractRaw(payload, 'attributes'), 'friendly_name') as friendly_name,
  JSONExtractString(JSONExtractRaw(payload, 'attributes'), 'unit_of_measurement') as unit,
  JSONExtractRaw(payload, 'attributes') as attributes,
  coalesce({{ ts("JSONExtractString(payload, 'last_changed')") }}, kafka_ts) as last_changed,
  coalesce({{ ts("JSONExtractString(payload, 'last_updated')") }}, kafka_ts) as last_updated,
  ingested_at
from {{ source('raw', 'homeassistant') }}
where entity_id != ''
{% if is_incremental() -%}
  and ingested_at > (select max(ingested_at) from {{ this }})
{%- endif %}
