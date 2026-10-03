-- Per day: calories and macros eaten, calories burned in workouts, water,
-- and the day's weight if there was a check-in. Days with none of these
-- are absent.
--
-- The sums are Nullable so that a day missing from one side joins as NULL,
-- not 0: a day with a weigh-in and no food logged did not eat zero calories,
-- and a day with no check-in did not weigh zero. (ClickHouse fills a missed
-- join with the column type's default, and Nullable's default is NULL.)
with
  food as (
    select entry_date as day,
      toNullable(sum(calories)) as calories_eaten, toNullable(sum(protein_g)) as protein_g,
      toNullable(sum(carbs_g)) as carbs_g, toNullable(sum(fat_g)) as fat_g, count() as entries
    from {{ ref('sparkyfitness_food_entries') }} where entry_date is not null group by day
  ),
  exercise as (
    select entry_date as day, toNullable(sum(calories_burned)) as calories_burned,
      toNullable(sum(duration_minutes)) as exercise_minutes
    from {{ ref('sparkyfitness_exercise') }} where entry_date is not null group by day
  ),
  water as (
    select entry_date as day, toNullable(sum(water_ml)) as water_ml
    from {{ ref('sparkyfitness_water') }} where entry_date is not null group by day
  ),
  weight as (
    select entry_date as day, argMax(weight, updated_at) as day_weight
    from {{ ref('sparkyfitness_measurements') }}
    where entry_date is not null and weight is not null group by day
  ),
  days as (
    select day from food union distinct select day from exercise
    union distinct select day from water union distinct select day from weight
  )
select
  d.day as day,
  f.calories_eaten as calories_eaten,
  f.protein_g as protein_g,
  f.carbs_g as carbs_g,
  f.fat_g as fat_g,
  coalesce(f.entries, 0) as food_entries,
  e.calories_burned as calories_burned,
  e.exercise_minutes as exercise_minutes,
  w.water_ml as water_ml,
  wt.day_weight as weight
from days d
left join food f on f.day = d.day
left join exercise e on e.day = d.day
left join water w on w.day = d.day
left join weight wt on wt.day = d.day
