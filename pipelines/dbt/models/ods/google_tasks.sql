-- Google Tasks, one row per task, with its list's name. Completed and
-- hidden (cleared) tasks are included.
with lists as (
  select id as list_id, JSONExtractString(record, 'title') as list_title
  from ({{ snapshot_records('google', 'tasks/lists') }})
)
select
  t.id as task_key,
  splitByChar('/', t.id)[1] as list_id,
  l.list_title as list,
  JSONExtractString(t.record, 'id') as task_id,
  JSONExtractString(t.record, 'parent') as parent_task_id,
  JSONExtractString(t.record, 'title') as title,
  JSONExtractString(t.record, 'notes') as notes,
  JSONExtractString(t.record, 'status') = 'completed' as done,
  {{ ts("JSONExtractString(t.record, 'due')") }} as due_at,
  {{ ts("JSONExtractString(t.record, 'completed')") }} as done_at,
  {{ ts("JSONExtractString(t.record, 'updated')") }} as updated_at,
  t.extracted_at as extracted_at
from ({{ snapshot_records('google', 'tasks/tasks') }}) t
left join lists l on l.list_id = splitByChar('/', t.id)[1]
