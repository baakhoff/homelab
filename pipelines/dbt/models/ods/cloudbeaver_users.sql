-- CloudBeaver's accounts (pipelines/dags/cloudbeaver.py): one per Pocket ID
-- address that has signed in, and the local admin.
select
  id as user_id,
  JSONExtractString(record, 'is_active') = 'Y' as active,
  {{ ts("JSONExtractString(record, 'create_time')") }} as created_at,
  {{ ts("JSONExtractString(record, 'last_login_time')") }} as last_login_at,
  JSONExtractString(record, 'disabled_by') as disabled_by,
  JSONExtractString(record, 'disable_reason') as disable_reason,
  extracted_at
from ({{ snapshot_records('cloudbeaver', 'users') }})
