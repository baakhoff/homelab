-- Numeric Home Assistant entities (sensors with a number as their state),
-- one row per entity and hour.
select
  entity_id,
  any(domain) as domain,
  any(friendly_name) as friendly_name,
  any(unit) as unit,
  toStartOfHour(last_updated) as hour,
  avg(state_num) as avg_value,
  min(state_num) as min_value,
  max(state_num) as max_value,
  count() as changes
from {{ ref('ha_states') }}
where state_num is not null
group by entity_id, hour
