-- Firefly transactions, one row per split. A Firefly transaction is a
-- group of one or more splits; most groups have one. Amounts are positive,
-- the direction is `type` (withdrawal, deposit, transfer, ...).
select
  toUInt64OrZero(id) as group_id,
  JSONExtractString(record, 'attributes', 'group_title') as group_title,
  toUInt64OrZero(JSONExtractString(split, 'transaction_journal_id')) as journal_id,
  JSONExtractString(split, 'type') as type,
  {{ ts("JSONExtractString(split, 'date')") }} as date,
  -- The booking day as Firefly shows it. `date` above is that moment in
  -- UTC, which puts a transaction booked at midnight local time on the
  -- previous day; the day part of the original string does not.
  toDateOrNull(left(JSONExtractString(split, 'date'), 10)) as booked_on,
  {{ num("split", "'amount'") }} as amount,
  JSONExtractString(split, 'currency_code') as currency_code,
  {{ num("split", "'foreign_amount'") }} as foreign_amount,
  JSONExtractString(split, 'foreign_currency_code') as foreign_currency_code,
  JSONExtractString(split, 'description') as description,
  toUInt64OrZero(JSONExtractString(split, 'source_id')) as source_account_id,
  JSONExtractString(split, 'source_name') as source_name,
  toUInt64OrZero(JSONExtractString(split, 'destination_id')) as destination_account_id,
  JSONExtractString(split, 'destination_name') as destination_name,
  JSONExtractString(split, 'category_name') as category_name,
  JSONExtractString(split, 'budget_name') as budget_name,
  JSONExtractString(split, 'bill_name') as bill_name,
  JSONExtract(split, 'tags', 'Array(String)') as tags,
  JSONExtractString(split, 'notes') as notes,
  {{ ts("JSONExtractString(record, 'attributes', 'created_at')") }} as created_at,
  {{ ts("JSONExtractString(record, 'attributes', 'updated_at')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('firefly', 'transactions') }})
array join JSONExtractArrayRaw(record, 'attributes', 'transactions') as split
