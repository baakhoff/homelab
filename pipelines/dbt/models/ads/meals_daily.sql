-- Meals planned per day and slot (breakfast, lunch, dinner, side).
select
  date as day,
  entry_type,
  count() as planned,
  groupArray(if(recipe_name != '', recipe_name, title)) as dishes
from {{ ref('mealie_mealplans') }}
where date is not null
group by day, entry_type
