{#
  One row per log record out of raw tables that hold OTLP JSON, the format
  the Alloy collectors send (clusters/lab/logging/alloy.yaml):

    {"resourceLogs": [{"resource": {"attributes": [...]},
      "scopeLogs": [{"logRecords": [{"timeUnixNano": "...",
        "body": {"stringValue": "..."}, "attributes": [...]}]}]}]}

  A message may carry several records; each becomes a row. `attrs` is the
  record's attributes merged over its resource's, as a Map(String, String) -
  the Loki labels (namespace, pod, container, node) land in one or the
  other depending on the collector's version, so both are read.
#}
{% macro otlp_records(source_table) -%}
  select
    ingested_at,
    kafka_ts,
    fromUnixTimestamp64Nano(toInt64OrZero(JSONExtractString(lr, 'timeUnixNano')), 'UTC') as ts_raw,
    if(toUInt64OrZero(JSONExtractString(lr, 'timeUnixNano')) = 0, kafka_ts, ts_raw) as ts,
    JSONExtractString(lr, 'body', 'stringValue') as body,
    mapUpdate(
      mapFromArrays(
        arrayMap(a -> JSONExtractString(a, 'key'), JSONExtractArrayRaw(rl, 'resource', 'attributes')),
        arrayMap(a -> JSONExtractString(a, 'value', 'stringValue'), JSONExtractArrayRaw(rl, 'resource', 'attributes'))
      ),
      mapFromArrays(
        arrayMap(a -> JSONExtractString(a, 'key'), JSONExtractArrayRaw(lr, 'attributes')),
        arrayMap(a -> JSONExtractString(a, 'value', 'stringValue'), JSONExtractArrayRaw(lr, 'attributes'))
      )
    ) as attrs
  from {{ source('raw', source_table) }}
  array join JSONExtractArrayRaw(payload, 'resourceLogs') as rl
  array join JSONExtractArrayRaw(rl, 'scopeLogs') as sl
  array join JSONExtractArrayRaw(sl, 'logRecords') as lr
  {% if is_incremental() -%}
  where ingested_at > (select max(ingested_at) from {{ this }})
  {%- endif %}
{%- endmacro %}
