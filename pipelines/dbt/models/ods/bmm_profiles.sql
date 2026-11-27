-- One row per BMM profile: a persona, with its own accounts, images and
-- calendar.
select
  id as profile_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'timezone') as timezone,
  JSONExtractString(record, 'notes') as notes,
  JSONExtractUInt(record, 'accountCount') as accounts,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  extracted_at
from ({{ snapshot_records('bmm', 'profiles') }})
