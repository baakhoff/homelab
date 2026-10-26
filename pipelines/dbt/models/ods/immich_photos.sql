-- One row per photo or video in Immich that immich_sort has looked at
-- (pipelines/dags/immich_sort.py): the file's name, when and where it was
-- taken, the type Claude gave it, Claude's description of it, and whether
-- it was set aside into the album "To delete". asset_id is Immich's own:
-- photos.lab.baakhoff.com/photos/<asset_id> opens it.
--
-- The place is Immich's, from the file's GPS and Immich's reverse
-- geocoding - never Claude's. The newest answer wins: a picture whose
-- Type/ tag was removed in Immich is looked at again, and its new row
-- replaces the old. A picture deleted in Immich keeps its row.
with latest as (
  select
    JSONExtractString(payload, 'id') as asset_id,
    JSONExtractRaw(payload, 'record') as record,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'immich') }}
  where JSONExtractString(payload, 'endpoint') = 'photos'
  order by kafka_ts desc
  limit 1 by asset_id
)
select
  asset_id,
  JSONExtractString(record, 'file_name') as file_name,
  JSONExtractString(record, 'kind') as kind,
  nullIf(JSONExtractString(record, 'duration'), '') as duration,
  {{ ts("JSONExtractString(record, 'taken_at')") }} as taken_at,
  nullIf(JSONExtractString(record, 'city'), '') as city,
  nullIf(JSONExtractString(record, 'state'), '') as state,
  nullIf(JSONExtractString(record, 'country'), '') as country,
  JSONExtract(record, 'latitude', 'Nullable(Float64)') as lat,
  JSONExtract(record, 'longitude', 'Nullable(Float64)') as lon,
  JSONExtractString(record, 'type') as type,
  JSONExtractString(record, 'description') as description,
  JSONExtractBool(record, 'to_delete') as claude_would_delete,
  JSONExtractBool(record, 'set_aside') as is_set_aside,
  JSONExtractString(record, 'model') as model,
  extracted_at as described_at
from latest
