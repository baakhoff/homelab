-- One row per BMM post: its text, where it stands, when it is due, and how
-- many accounts it goes to. How it went on each account is bmm_post_targets.
select
  id as post_id,
  JSONExtractString(record, 'profileId') as profile_id,
  JSONExtractString(record, 'text') as text,
  JSONExtractString(record, 'status') as status,
  {{ ts("JSONExtractString(record, 'scheduledAt')") }} as scheduled_at,
  length(JSONExtractArrayRaw(record, 'media')) as images,
  length(JSONExtractArrayRaw(record, 'targets')) as targets,
  JSONExtractString(record, 'createdBy') as created_by,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updatedAt')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('bmm', 'posts') }})
