-- Places the account keeps in Google Maps, one row each, from Takeout
-- exports: starred and saved places and reviews ("your places"), labelled
-- places such as Home and Work, and followed places. `kind` says which.
-- Coordinates are WGS84; Takeout's GeoJSON lists longitude first.
select
  id as place_key,
  multiIf(
    endpoint = 'takeout/maps/labeled_places', 'labeled',
    endpoint = 'takeout/maps/followed_places', 'followed',
    JSONExtractString(record, '_file') ilike '%review%', 'review',
    'saved') as kind,
  coalesce(
    nullIf(JSONExtractString(record, 'properties', 'location', 'name'), ''),
    nullIf(JSONExtractString(record, 'properties', 'Title'), ''),
    nullIf(JSONExtractString(record, 'properties', 'name'), ''),
    nullIf(JSONExtractString(record, 'Place'), '')) as name,
  coalesce(
    nullIf(JSONExtractString(record, 'properties', 'location', 'address'), ''),
    nullIf(JSONExtractString(record, 'properties', 'address'), ''),
    nullIf(JSONExtractString(record, 'Address'), '')) as address,
  if(JSONLength(record, 'geometry', 'coordinates') >= 2,
     JSONExtractFloat(record, 'geometry', 'coordinates', 2), NULL) as lat,
  if(JSONLength(record, 'geometry', 'coordinates') >= 2,
     JSONExtractFloat(record, 'geometry', 'coordinates', 1), NULL) as lon,
  coalesce(
    nullIf(JSONExtractString(record, 'properties', 'google_maps_url'), ''),
    nullIf(JSONExtractString(record, 'URL'), '')) as url,
  coalesce(
    nullIf(JSONExtractString(record, 'properties', 'review_text_published'), ''),
    nullIf(JSONExtractString(record, 'properties', 'Comment'), '')) as comment,
  JSONExtract(record, 'properties', 'five_star_rating_published', 'Nullable(Int64)') as rating,
  {{ ts("JSONExtractString(record, 'properties', 'date')") }} as saved_at,
  extracted_at
from ({{ accumulated_records('google', [
  'takeout/maps/saved_places', 'takeout/maps/labeled_places', 'takeout/maps/followed_places',
]) }})
