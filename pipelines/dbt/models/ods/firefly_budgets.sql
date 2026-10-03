select
  toUInt64OrZero(id) as budget_id,
  JSONExtractString(record, 'attributes', 'name') as name,
  JSONExtractBool(record, 'attributes', 'active') as active,
  {{ ts("JSONExtractString(record, 'attributes', 'created_at')") }} as created_at,
  extracted_at
from ({{ snapshot_records('firefly', 'budgets') }})
