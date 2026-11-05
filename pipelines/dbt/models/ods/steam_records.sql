-- The rest of Steam, as it came, one row per record of the newest run: the
-- profile with its level, the badges, the recently played games. `endpoint`
-- says which.
select
  id as record_key,
  endpoint,
  record,
  extracted_at
from (
  select
    JSONExtractString(payload, 'id') as id,
    JSONExtractString(payload, 'endpoint') as endpoint,
    JSONExtractString(payload, 'run_id') as run_id,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at,
    kafka_ts
  from {{ source('raw', 'steam') }}
  where JSONExtractString(payload, 'endpoint') in ('profile', 'badges', 'recently_played')
)
where (endpoint, run_id) in (
  select JSONExtractString(payload, 'endpoint'), argMax(JSONExtractString(payload, 'run_id'), kafka_ts)
  from {{ source('raw', 'steam') }}
  where JSONExtractString(payload, 'endpoint') in ('profile', 'badges', 'recently_played')
  group by JSONExtractString(payload, 'endpoint')
)
order by kafka_ts desc
limit 1 by endpoint, id
