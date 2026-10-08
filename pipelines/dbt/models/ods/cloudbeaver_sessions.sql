-- CloudBeaver's sessions, from its own database (pipelines/dags/cloudbeaver.py):
-- who, from which address and browser, from when until their last request.
-- A session is one browser's sign-in; it ends 30 minutes after its last
-- request (clusters/lab/cloudbeaver/config.yaml).
select
  id as session_id,
  JSONExtractString(record, 'user_id') as user_id,
  JSONExtractString(record, 'session_type') as session_type,
  {{ ts("JSONExtractString(record, 'create_time')") }} as started_at,
  {{ ts("JSONExtractString(record, 'last_access_time')") }} as last_seen_at,
  JSONExtractString(record, 'last_access_remote_address') as client_address,
  JSONExtractString(record, 'last_access_user_agent') as user_agent,
  extracted_at
from ({{ snapshot_records('cloudbeaver', 'sessions') }})
