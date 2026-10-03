-- How often each entity changed state per day - numeric or not. The
-- non-numeric ones (lights, doors, presence) are counted here.
select
  toDate(last_updated) as day,
  domain,
  entity_id,
  any(friendly_name) as friendly_name,
  count() as changes,
  uniqExact(state) as distinct_states
from {{ ref('ha_states') }}
group by day, domain, entity_id
