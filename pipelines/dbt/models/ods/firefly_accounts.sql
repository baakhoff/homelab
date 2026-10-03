-- Firefly accounts as they are now: asset, expense, revenue and liability.
select
  toUInt64OrZero(id) as account_id,
  JSONExtractString(record, 'attributes', 'name') as name,
  JSONExtractString(record, 'attributes', 'type') as type,
  JSONExtractString(record, 'attributes', 'account_role') as account_role,
  JSONExtractString(record, 'attributes', 'currency_code') as currency_code,
  {{ num("record", "'attributes', 'current_balance'") }} as current_balance,
  JSONExtractBool(record, 'attributes', 'active') as active,
  {{ ts("JSONExtractString(record, 'attributes', 'created_at')") }} as created_at,
  {{ ts("JSONExtractString(record, 'attributes', 'updated_at')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('firefly', 'accounts') }})
