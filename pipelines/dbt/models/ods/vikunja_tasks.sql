-- Vikunja tasks as they are now.
select
  toUInt64OrZero(id) as task_id,
  JSONExtractString(record, 'title') as title,
  JSONExtractString(record, 'description') as description,
  JSONExtractBool(record, 'done') as done,
  {{ ts("JSONExtractString(record, 'done_at')") }} as done_at,
  {{ ts("JSONExtractString(record, 'due_date')") }} as due_date,
  JSONExtractInt(record, 'priority') as priority,
  JSONExtractFloat(record, 'percent_done') as percent_done,
  JSONExtractUInt(record, 'project_id') as project_id,
  arrayMap(l -> JSONExtractString(l, 'title'), JSONExtractArrayRaw(record, 'labels')) as labels,
  arrayMap(a -> JSONExtractString(a, 'username'), JSONExtractArrayRaw(record, 'assignees')) as assignees,
  JSONExtractString(record, 'created_by', 'username') as created_by,
  {{ ts("JSONExtractString(record, 'created')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updated')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('vikunja', 'tasks') }})
