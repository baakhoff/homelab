{#
  The latest snapshot of one API endpoint, from a raw table the ingest DAGs
  fill (pipelines/dags/ingest.py).

  Every run of an ingest DAG sends every record the endpoint lists, under
  the run's run_id. The newest run_id that has rows is the current state:
  a record missing from it has been deleted at the source, so it is not in
  the result either. A record sent twice in one run (a retried task) counts
  once.

  Columns: id, record (the API's JSON for the record), extracted_at.
#}
{% macro snapshot_records(source_table, endpoint) -%}
  with rows as (
    select
      JSONExtractString(payload, 'run_id') as run_id,
      JSONExtractString(payload, 'id') as id,
      JSONExtractRaw(payload, 'record') as record,
      parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at,
      kafka_ts
    from {{ source('raw', source_table) }}
    where JSONExtractString(payload, 'endpoint') = '{{ endpoint }}'
  ),
  latest as (
    select argMax(run_id, kafka_ts) as run_id from rows
  )
  select id, record, extracted_at
  from rows
  where run_id = (select run_id from latest)
  order by kafka_ts desc
  limit 1 by id
{%- endmacro %}


{#
  A timestamp out of an API string, or NULL. The APIs here write "no date"
  in several ways - an empty string, null, or Go's zero time
  0001-01-01T00:00:00Z - and all of them become NULL rather than 1970.
#}
{% macro ts(expr) -%}
  if(
    parseDateTime64BestEffortOrNull({{ expr }}, 3, 'UTC') < toDateTime64('1971-01-01 00:00:00', 3, 'UTC'),
    NULL,
    parseDateTime64BestEffortOrNull({{ expr }}, 3, 'UTC')
  )
{%- endmacro %}


{# A number out of a JSON string such as "12.50" (Firefly sends amounts as strings). #}
{% macro num(json, path) -%}
  toDecimal64OrNull(JSONExtractString({{ json }}, {{ path }}), 4)
{%- endmacro %}
