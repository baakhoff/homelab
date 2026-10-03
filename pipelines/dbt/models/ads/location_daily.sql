-- Per day, in the lab's time zone: how many points were recorded, how far
-- they cover, the first and last of them, the countries they fall in, and
-- the visits that started that day. Days with no points are absent.
--
-- The distance is straight lines between consecutive points, so it is a
-- little under the road distance on a sparse track, and a little over when
-- GPS jitter accumulates while standing still.
with
  p as (
    select
      toDate(ts, 'Europe/Copenhagen') as day,
      ts,
      assumeNotNull(lat) as lat,
      assumeNotNull(lon) as lon,
      country
    from {{ ref('dawarich_points') }}
    where lat is not null and lon is not null
  ),
  legs as (
    select
      day, ts, country,
      geoDistance(
        lon, lat,
        lagInFrame(lon, 1, lon) over w,
        lagInFrame(lat, 1, lat) over w
      ) as meters
    from p
    window w as (partition by day order by ts rows between 1 preceding and current row)
  ),
  days as (
    select
      day,
      count() as points,
      round(sum(meters) / 1000, 2) as distance_km,
      min(ts) as first_point,
      max(ts) as last_point,
      arraySort(groupUniqArrayIf(country, country != '')) as countries
    from legs
    group by day
  ),
  visits as (
    select
      toDate(started_at, 'Europe/Copenhagen') as day,
      count() as visits,
      groupArray(name) as visited
    from {{ ref('dawarich_visits') }}
    where started_at is not null and status != 'declined'
    group by day
  )
select
  d.day as day,
  d.points as points,
  d.distance_km as distance_km,
  d.first_point as first_point,
  d.last_point as last_point,
  d.countries as countries,
  coalesce(v.visits, 0) as visits,
  v.visited as visited
from days d
left join visits v on v.day = d.day
