-- One row per day across the household's systems: what was spent, what got
-- done, what was cooked and what was filed. Days with no activity in any
-- system are absent. Money is a map of currency to amount - adding dinars to
-- euros would be a number that means nothing.
with
  spend as (
    select day,
      sumMapIf(map(currency_code, amount), type = 'withdrawal') as spent,
      sumMapIf(map(currency_code, amount), type = 'deposit') as earned
    from {{ ref('finance_daily') }} group by day
  ),
  tasks as (
    select day, sum(created) as tasks_created, sum(finished) as tasks_finished
    from {{ ref('tasks_daily') }} group by day
  ),
  meals as (
    select day, sum(planned) as meals_planned from {{ ref('meals_daily') }} group by day
  ),
  docs as (
    select day, sum(documents) as documents_added from {{ ref('documents_daily') }} group by day
  ),
  days as (
    select day from spend union distinct select day from tasks
    union distinct select day from meals union distinct select day from docs
  )
select
  d.day as day,
  s.spent as spent,
  s.earned as earned,
  coalesce(t.tasks_created, 0) as tasks_created,
  coalesce(t.tasks_finished, 0) as tasks_finished,
  coalesce(m.meals_planned, 0) as meals_planned,
  coalesce(o.documents_added, 0) as documents_added
from days d
left join spend s on s.day = d.day
left join tasks t on t.day = d.day
left join meals m on m.day = d.day
left join docs o on o.day = d.day
-- No join_use_nulls here: a Map cannot be Nullable, and a missing day's
-- defaults (an empty map, zero) are the right answer anyway.
