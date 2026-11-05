-- One row per Immich account: its name, whether it is an admin, and when
-- it was created, changed or deleted. No email: the name tells the
-- accounts apart, and the address stays in raw.
select
  id as user_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractBool(record, 'isAdmin') as is_admin,
  JSONExtractString(record, 'status') as status,
  JSONExtract(record, 'quotaSizeInBytes', 'Nullable(UInt64)') as quota_bytes,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updatedAt')") }} as updated_at,
  {{ ts("JSONExtractString(record, 'deletedAt')") }} as deleted_at,
  extracted_at
from ({{ snapshot_records('immich', 'admin/users') }})
