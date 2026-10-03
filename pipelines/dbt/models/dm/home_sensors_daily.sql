-- Every numeric sensor, one row per day: the table for climate, energy and
-- the like over weeks and seasons.
select
  toDate(hour) as day,
  entity_id,
  any(friendly_name) as friendly_name,
  any(unit) as unit,
  avg(avg_value) as avg_value,
  min(min_value) as min_value,
  max(max_value) as max_value,
  sum(changes) as readings
from {{ ref('ha_numeric_hourly') }}
group by day, entity_id
