-- My Activity: every search, YouTube video watched or searched, Maps
-- search and direction, Play and Shopping activity, and the ads Google
-- showed - from the Data Portability exports, one row per thing done.
-- `resource` is which (search, youtube, maps, play, shopping, myadcenter).
--
-- The fields are those of Takeout's My Activity JSON, which the Data
-- Portability API shares. Anything else an item carries is in record.
select
  id as activity_id,
  replaceOne(endpoint, 'portability/myactivity.', '') as resource,
  JSONExtractString(record, 'header') as header,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'titleUrl') as url,
  JSONExtractString(JSONExtractArrayRaw(record, 'subtitles')[1], 'name') as subtitle,
  JSONExtract(record, 'products', 'Array(String)') as products,
  {{ ts("JSONExtractString(record, 'time')") }} as happened_at,
  arrayExists(d -> JSONExtractString(d, 'name') = 'From Google Ads', JSONExtractArrayRaw(record, 'details')) as from_ads,
  record,
  extracted_at
from ({{ accumulated_records('google', [
  'portability/myactivity.search', 'portability/myactivity.youtube', 'portability/myactivity.maps',
  'portability/myactivity.play', 'portability/myactivity.shopping', 'portability/myactivity.myadcenter',
]) }})
