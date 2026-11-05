-- Google Pay: purchases through Google (Play, subscriptions, Store) and
-- money sent or requested, one row each, from Takeout exports. Amounts
-- come as text with their currency ("€4.99", "RSD 1,200.00"): `amount` is
-- the number with thousands separators dropped, `currency` what is left -
-- check `amount_text` for a locale that writes a decimal comma.
select
  id as transaction_key,
  if(endpoint = 'takeout/pay/money_sends', 'money_send', 'purchase') as kind,
  nullIf(JSONExtractString(record, 'Transaction ID'), '') as transaction_id,
  JSONExtractString(record, 'Time') as time_text,
  parseDateTime64BestEffortOrNull(JSONExtractString(record, 'Time'), 3, 'UTC') as happened_at,
  JSONExtractString(record, 'Description') as description,
  nullIf(JSONExtractString(record, 'Product'), '') as product,
  nullIf(JSONExtractString(record, 'Memo'), '') as memo,
  JSONExtractString(record, 'Payment method') as payment_method,
  JSONExtractString(record, 'Status') as status,
  JSONExtractString(record, 'Amount') as amount_text,
  toFloat64OrNull(replaceRegexpAll(JSONExtractString(record, 'Amount'), '[^0-9.-]', '')) as amount,
  nullIf(trimBoth(replaceRegexpAll(JSONExtractString(record, 'Amount'), '[0-9.,\\s-]', '')), '') as currency,
  extracted_at
from ({{ accumulated_records('google', ['takeout/pay/transactions', 'takeout/pay/money_sends']) }})
