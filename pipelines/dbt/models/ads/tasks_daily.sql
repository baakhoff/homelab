-- Tasks created and finished per day and project.
with created as (
  select toDate(created_at) as day, project_id, count() as created
  from {{ ref('vikunja_tasks') }} where created_at is not null
  group by day, project_id
),
finished as (
  select toDate(done_at) as day, project_id, count() as finished
  from {{ ref('vikunja_tasks') }} where done and done_at is not null
  group by day, project_id
)
select
  coalesce(c.day, f.day) as day,
  coalesce(c.project_id, f.project_id) as project_id,
  p.title as project,
  coalesce(c.created, 0) as created,
  coalesce(f.finished, 0) as finished
from created c
full outer join finished f on c.day = f.day and c.project_id = f.project_id
left join {{ ref('vikunja_projects') }} p on p.project_id = coalesce(c.project_id, f.project_id)
settings join_use_nulls = 1
