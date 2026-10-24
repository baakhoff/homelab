-- The VK music list, one row per track, from the data archive: artist and
-- title as VK showed them ("Artist — Title"), and the length.
with tracks as (
  select
    id,
    JSONExtractString(record, 'title') as full_title,
    JSONExtractString(record, 'duration') as duration_text,
    JSONExtractString(record, 'album') as album,
    extracted_at,
    splitByString(' — ', full_title) as dash_parts
  from ({{ accumulated_records('vk', ['vk/audio']) }})
)
select
  id as track_key,
  if(length(dash_parts) > 1, dash_parts[1], '') as artist,
  if(length(dash_parts) > 1, arrayStringConcat(arraySlice(dash_parts, 2), ' — '), full_title) as title,
  full_title,
  -- m:ss or h:mm:ss
  arraySum(arrayMap((x, i) -> toUInt32OrZero(x) * pow(60, i - 1),
                    arrayReverse(splitByChar(':', duration_text)),
                    arrayEnumerate(splitByChar(':', duration_text)))) as duration_s,
  nullIf(album, '') as album,
  extracted_at
from tracks
