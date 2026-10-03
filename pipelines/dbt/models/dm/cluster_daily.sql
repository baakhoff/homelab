-- The lab's own health per day and namespace: how much it logged, how much
-- of that was errors, and how many warning events Kubernetes raised.
with logs as (
  select toDate(hour) as day, namespace,
    sum(lines) as log_lines, sum(warnings) as log_warnings, sum(errors) as log_errors
  from {{ ref('logs_hourly') }}
  group by day, namespace
),
events as (
  select day, namespace, sumIf(events, type = 'Warning') as warning_events, sum(events) as all_events
  from {{ ref('k8s_events_daily') }}
  group by day, namespace
)
select
  coalesce(l.day, e.day) as day,
  coalesce(l.namespace, e.namespace) as namespace,
  coalesce(l.log_lines, 0) as log_lines,
  coalesce(l.log_warnings, 0) as log_warnings,
  coalesce(l.log_errors, 0) as log_errors,
  coalesce(e.all_events, 0) as events,
  coalesce(e.warning_events, 0) as warning_events
from logs l
full outer join events e on l.day = e.day and l.namespace = e.namespace
settings join_use_nulls = 1
