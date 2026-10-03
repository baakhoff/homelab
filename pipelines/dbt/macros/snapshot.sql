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


{#
  Every record an endpoint has ever sent, the newest version of each, from
  a source whose DAG sends only what changed (pipelines/dags/google.py) -
  so the newest run alone is not the current state, as it is for
  snapshot_records(). A record whose newest version is a tombstone
  ("deleted": true in the envelope) has been deleted and is left out.

  `endpoints` is a list; the endpoint comes back as a column.

  Columns: id, endpoint, record, file, extracted_at.
#}
{% macro accumulated_records(source_table, endpoints) -%}
  select id, endpoint, record, file, extracted_at
  from (
    select
      JSONExtractString(payload, 'id') as id,
      JSONExtractString(payload, 'endpoint') as endpoint,
      JSONExtractRaw(payload, 'record') as record,
      JSONExtractString(payload, 'file') as file,
      JSONExtractBool(payload, 'deleted') as deleted,
      parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at,
      kafka_ts
    from {{ source('raw', source_table) }}
    where JSONExtractString(payload, 'endpoint') in (
      {%- for e in endpoints %}'{{ e }}'{{ ", " if not loop.last }}{% endfor -%}
    )
    order by kafka_ts desc
    limit 1 by endpoint, id
  )
  where not deleted
{%- endmacro %}
