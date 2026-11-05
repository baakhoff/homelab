-- The filament each Bambu Lab print used, one row per AMS slot it drew
-- from: type, Bambu's filament id, colour and grams. The grams are the
-- slicer's figure for the whole job, as in bambu_prints - a failed print
-- shows what it would have used. Colours are RRGGBBAA hex, both as Bambu
-- names them: `source_color` and `target_color`.
select
  concat(id, '/', toString(n)) as filament_key,
  toInt64(id) as task_id,
  n as position,
  JSONExtract(m, 'amsId', 'Nullable(Int64)') as ams_id,
  JSONExtract(m, 'slotId', 'Nullable(Int64)') as slot_id,
  nullIf(JSONExtractString(m, 'filamentType'), '') as filament_type,
  nullIf(JSONExtractString(m, 'filamentId'), '') as filament_id,
  nullIf(JSONExtractString(m, 'sourceColor'), '') as source_color,
  nullIf(JSONExtractString(m, 'targetColor'), '') as target_color,
  JSONExtract(m, 'weight', 'Nullable(Float64)') as weight_g,
  {{ ts("JSONExtractString(record, 'startTime')") }} as started_at,
  m as mapping,
  extracted_at
from ({{ accumulated_records('bambu', ['tasks']) }})
array join
  JSONExtractArrayRaw(record, 'amsDetailMapping') as m,
  arrayEnumerate(JSONExtractArrayRaw(record, 'amsDetailMapping')) as n
where toInt64OrZero(id) != 0
