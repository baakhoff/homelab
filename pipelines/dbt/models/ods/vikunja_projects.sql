select
  toUInt64OrZero(id) as project_id,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'description') as description,
  JSONExtractBool(record, 'is_archived') as archived,
  JSONExtractUInt(record, 'parent_project_id') as parent_project_id,
  {{ ts("JSONExtractString(record, 'created')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updated')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('vikunja', 'projects') }})
