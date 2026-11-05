-- One row per Immich account: how many photos and videos it holds and the
-- bytes they take, from the server's statistics. Each photo's own row,
-- once it is described, is in immich_photos.
select
  id as user_id,
  JSONExtractString(record, 'userName') as user_name,
  JSONExtractUInt(record, 'photos') as photos,
  JSONExtractUInt(record, 'videos') as videos,
  JSONExtractUInt(record, 'usage') as usage_bytes,
  JSONExtractUInt(record, 'usagePhotos') as photos_bytes,
  JSONExtractUInt(record, 'usageVideos') as videos_bytes,
  JSONExtract(record, 'quotaSizeInBytes', 'Nullable(UInt64)') as quota_bytes,
  extracted_at
from ({{ snapshot_records('immich', 'server/statistics') }})
