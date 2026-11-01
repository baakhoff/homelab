-- The photos and videos in Immich that came from Telegram or VK, one row
-- each, deleted ones too (pipelines/dags/immich_sort.py, its assets task):
-- Immich's id, the file's name, image or video, when it reached Immich and
-- the date it carries - the message's. The name, TG_<date>_<time>_<hash>.<ext>
-- or VK_..., holds the hash that ties it to its message: ads.chat_media.
--
-- `status` is active while the file is in Immich; once it is gone - into
-- the trash or for good - duplicate if Immich had it in a duplicate group
-- (`duplicate_group`), which is how its duplicate review removes the copies
-- it does not keep, else deleted. Back out of the trash, it is active again.
-- `status_at` is when the task saw the newest status, within the hour.
with records as (
  select
    JSONExtractString(payload, 'id') as asset_id,
    JSONExtractRaw(payload, 'record') as record,
    JSONHas(record, 'file_name') as full,
    parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC') as extracted_at,
    kafka_ts
  from {{ source('raw', 'immich') }}
  where JSONExtractString(payload, 'endpoint') = 'assets'
),
-- A file's newest status, and its details from the newest record that has
-- them: the one for its going carries the status alone.
latest as (
  select
    asset_id,
    argMax(record, kafka_ts) as last,
    argMaxIf(record, kafka_ts, full) as details,
    max(extracted_at) as status_at
  from records
  group by asset_id
)
select
  asset_id,
  JSONExtractString(details, 'file_name') as file_name,
  JSONExtractString(details, 'kind') as kind,
  multiIf(startsWith(file_name, 'TG_'), 'telegram', startsWith(file_name, 'VK_'), 'vk', '') as source,
  nullIf(extract(file_name, '^(?:TG|VK)_\\d{8}_\\d{6}_([0-9a-f]{12})\\.'), '') as file_hash,
  coalesce(nullIf(JSONExtractString(last, 'status'), ''), 'active') as status,
  nullIf(JSONExtractString(details, 'duplicate_group'), '') as duplicate_group,
  {{ ts("JSONExtractString(details, 'uploaded_at')") }} as uploaded_at,
  {{ ts("JSONExtractString(details, 'taken_at')") }} as taken_at,
  status_at
from latest
