-- One row per request made in Seerr: the film or series asked for, by
-- whom, whether it was approved, and whether it has arrived. Seerr's
-- numbers are spelled out: a request is pending, approved, declined,
-- failed or completed; its media is unknown, pending, processing, partly
-- or fully available, blocklisted or deleted. A number Seerr adds later
-- comes out as an empty string.
select
  toUInt64OrZero(id) as request_id,
  JSONExtractString(record, 'type') as type,
  JSONExtract(record, 'media', 'tmdbId', 'Nullable(UInt64)') as tmdb_id,
  JSONExtract(record, 'media', 'tvdbId', 'Nullable(UInt64)') as tvdb_id,
  JSONExtractUInt(record, 'requestedBy', 'id') as user_id,
  arrayElement(['pending', 'approved', 'declined', 'failed', 'completed'],
               JSONExtractUInt(record, 'status')) as status,
  arrayElement(['unknown', 'pending', 'processing', 'partly available', 'available', 'blocklisted', 'deleted'],
               JSONExtractUInt(record, 'media', 'status')) as media_status,
  JSONExtractBool(record, 'is4k') as is_4k,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as requested_at,
  {{ ts("JSONExtractString(record, 'updatedAt')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('seerr', 'request') }})
