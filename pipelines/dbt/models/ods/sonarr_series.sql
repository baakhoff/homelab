-- One row per series Sonarr follows: whether it is still airing, whether it
-- is wanted, and how many of its episodes are in the library.
select
  toUInt64OrZero(id) as series_id,
  JSONExtractString(record, 'title') as title,
  JSONExtract(record, 'year', 'Nullable(UInt16)') as year,
  JSONExtract(record, 'tvdbId', 'Nullable(UInt64)') as tvdb_id,
  nullIf(JSONExtractString(record, 'imdbId'), '') as imdb_id,
  JSONExtractString(record, 'status') as status,
  JSONExtractBool(record, 'monitored') as monitored,
  JSONExtractUInt(record, 'statistics', 'seasonCount') as seasons,
  JSONExtractUInt(record, 'statistics', 'episodeCount') as episodes,
  JSONExtractUInt(record, 'statistics', 'episodeFileCount') as episodes_in_library,
  JSONExtractUInt(record, 'statistics', 'sizeOnDisk') as size_bytes,
  {{ ts("JSONExtractString(record, 'added')") }} as added_at,
  extracted_at
from ({{ snapshot_records('sonarr', 'series') }})
