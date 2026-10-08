-- Every sign-in to CloudBeaver, successful or not (pipelines/dags/cloudbeaver.py).
-- Through the gate it is the reverse-proxy provider, once per session;
-- `local` is the admin account's password form.
select
  id as auth_id,
  {{ ts("JSONExtractString(record, 'create_time')") }} as attempted_at,
  JSONExtractString(record, 'auth_status') as status,
  JSONExtractString(record, 'auth_username') as username,
  JSONExtractString(record, 'auth_error') as error,
  JSONExtractString(record, 'error_code') as error_code,
  JSONExtractString(record, 'session_id') as session_id,
  JSONExtractString(record, 'is_main_auth') = 'Y' as is_main_auth,
  extracted_at
from ({{ snapshot_records('cloudbeaver', 'auth-attempts') }})
