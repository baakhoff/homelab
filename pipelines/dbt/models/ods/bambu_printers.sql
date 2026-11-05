-- The Bambu Lab printers bound to the account, as they stand at the newest
-- run: name, product, nozzle, and whether it was online and what it was
-- doing then. `device_id` is what bambu_prints.device_id points at. The
-- printer's LAN access code is dropped before it leaves the DAG.
select
  id as device_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'dev_product_name') as product,
  JSONExtractString(record, 'dev_model_name') as model,
  JSONExtract(record, 'nozzle_diameter', 'Nullable(Float64)') as nozzle_mm,
  JSONExtractBool(record, 'online') as online,
  nullIf(JSONExtractString(record, 'print_status'), '') as print_status,
  record,
  extracted_at
from ({{ snapshot_records('bambu', 'devices') }})
