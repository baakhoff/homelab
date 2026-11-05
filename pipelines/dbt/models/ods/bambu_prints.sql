-- Bambu Lab's prints, one row each, as the cloud lists them: every print
-- the account's printers ran through it, newest copy of each, from
-- ingest_bambu, which reads the whole list every run. One deleted in the
-- app stays. `status` is Bambu's code - 2 finished, 3 failed or cancelled;
-- `outcome` names those two and calls the rest, a print still running
-- among them, 'other'. `estimated_s` and `weight_g` are the slicer's
-- figures for the whole job, so a failed print still shows the full
-- estimate; `duration_s` is the real time from start to end. The filament
-- of each AMS slot is bambu_print_filaments.
select
  toInt64(id) as task_id,
  JSONExtractString(record, 'title') as title,
  nullIf(JSONExtractString(record, 'designTitle'), '') as design_title,
  nullIf(JSONExtractString(record, 'plateName'), '') as plate_name,
  JSONExtract(record, 'plateIndex', 'Nullable(Int64)') as plate_index,
  JSONExtractString(record, 'deviceId') as device_id,
  nullIf(JSONExtractString(record, 'deviceName'), '') as device_name,
  nullIf(JSONExtractString(record, 'deviceModel'), '') as device_model,
  JSONExtractInt(record, 'status') as status,
  multiIf(status = 2, 'finished', status = 3, 'failed', 'other') as outcome,
  {{ ts("JSONExtractString(record, 'startTime')") }} as started_at,
  {{ ts("JSONExtractString(record, 'endTime')") }} as ended_at,
  dateDiff('second', started_at, ended_at) as duration_s,
  JSONExtract(record, 'costTime', 'Nullable(Float64)') as estimated_s,
  JSONExtract(record, 'weight', 'Nullable(Float64)') as weight_g,
  nullIf(JSONExtractString(record, 'bedType'), '') as bed_type,
  nullIf(JSONExtractString(record, 'mode'), '') as mode,
  nullIf(JSONExtractInt(record, 'designId'), 0) as design_id,
  nullIf(JSONExtractString(record, 'modelId'), '') as model_id,
  JSONExtractBool(record, 'isDelete') as deleted_in_app,
  record,
  extracted_at
from ({{ accumulated_records('bambu', ['tasks']) }})
where toInt64OrZero(id) != 0
