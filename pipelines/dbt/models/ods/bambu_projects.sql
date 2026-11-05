-- The account's projects in Bambu Lab's cloud - the models it has sliced
-- and sent - one row each, newest copy; one deleted stays. Times are as
-- Bambu writes them, without a zone, taken as UTC.
select
  id as project_id,
  JSONExtractString(record, 'name') as name,
  nullIf(JSONExtractString(record, 'model_id'), '') as model_id,
  JSONExtractString(record, 'status') as status,
  {{ ts("JSONExtractString(record, 'create_time')") }} as created_at,
  {{ ts("JSONExtractString(record, 'update_time')") }} as updated_at,
  record,
  extracted_at
from ({{ accumulated_records('bambu', ['projects']) }})
