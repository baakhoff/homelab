-- The photos and videos in Immich that came from Telegram or VK, one row
-- each (pipelines/dags/immich_sort.py, its assets task): Immich's id, the
-- file's name, image or video, when it reached Immich and the date it
-- carries - the message's. The name, TG_<date>_<time>_<hash>.<ext> or
-- VK_..., holds the hash that ties it to its message: ads.chat_media.
-- A picture deleted in Immich - the trash included - is gone from here
-- within the hour: the task's tombstone is its newest record.
with latest as (
  select
    JSONExtractString(payload, 'id') as asset_id,
    JSONExtractRaw(payload, 'record') as record,
    JSONExtractBool(payload, 'deleted') as deleted,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at
  from {{ source('raw', 'immich') }}
  where JSONExtractString(payload, 'endpoint') = 'assets'
  order by kafka_ts desc
  limit 1 by asset_id
)
select
  asset_id,
  JSONExtractString(record, 'file_name') as file_name,
  JSONExtractString(record, 'kind') as kind,
  multiIf(startsWith(file_name, 'TG_'), 'telegram', startsWith(file_name, 'VK_'), 'vk', '') as source,
  nullIf(extract(file_name, '^(?:TG|VK)_\\d{8}_\\d{6}_([0-9a-f]{12})\\.'), '') as file_hash,
  {{ ts("JSONExtractString(record, 'uploaded_at')") }} as uploaded_at,
  {{ ts("JSONExtractString(record, 'taken_at')") }} as taken_at,
  extracted_at
from latest
where not deleted
