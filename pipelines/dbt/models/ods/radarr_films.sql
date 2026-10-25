-- One row per film Radarr follows: whether it is wanted, whether a file is
-- in the library yet, and how much space that file takes.
select
  toUInt64OrZero(id) as film_id,
  JSONExtractString(record, 'title') as title,
  nullIf(JSONExtractString(record, 'originalTitle'), '') as original_title,
  JSONExtract(record, 'year', 'Nullable(UInt16)') as year,
  JSONExtract(record, 'tmdbId', 'Nullable(UInt64)') as tmdb_id,
  nullIf(JSONExtractString(record, 'imdbId'), '') as imdb_id,
  JSONExtractString(record, 'status') as status,
  JSONExtractBool(record, 'monitored') as monitored,
  JSONExtractBool(record, 'hasFile') as has_file,
  JSONExtractUInt(record, 'sizeOnDisk') as size_bytes,
  {{ ts("JSONExtractString(record, 'added')") }} as added_at,
  extracted_at
from ({{ snapshot_records('radarr', 'movie') }})
