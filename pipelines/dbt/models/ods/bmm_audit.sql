-- One row per entry in BMM's audit log: a sign-in or a change, who did it
-- (a person, an API token, or BMM itself) and to what.
select
  id as event_id,
  {{ ts("JSONExtractString(record, 'at')") }} as at,
  JSONExtractString(record, 'action') as action,
  JSONExtractString(record, 'actorType') as actor_type,
  JSONExtractString(record, 'actorId') as actor_id,
  JSONExtractString(record, 'actorLabel') as actor,
  JSONExtractString(record, 'targetType') as target_type,
  JSONExtractString(record, 'targetId') as target_id,
  JSONExtractString(record, 'ip') as ip,
  JSONExtractRaw(record, 'metadata') as metadata,
  extracted_at
from ({{ snapshot_records('bmm', 'audit') }})
