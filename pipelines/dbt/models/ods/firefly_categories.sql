select
  toUInt64OrZero(id) as category_id,
  JSONExtractString(record, 'attributes', 'name') as name,
  JSONExtractString(record, 'attributes', 'notes') as notes,
  {{ ts("JSONExtractString(record, 'attributes', 'created_at')") }} as created_at,
  extracted_at
from ({{ snapshot_records('firefly', 'categories') }})
