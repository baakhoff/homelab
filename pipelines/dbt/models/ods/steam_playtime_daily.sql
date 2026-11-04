-- What was played on Steam, one row per day and game: the minutes its
-- total playtime grew by. Steam reports only totals, and ingest_steam
-- sends the whole library every 6 hours (pipelines/dags/steam.py), so the
-- growth between two runs is what was played in between - counted on the
-- day of the later run, in UTC: an evening's play shows on the next day
-- when no run fell between it and midnight.
--
-- Starts with the first run; nothing before it can be known. A game first
-- seen after that run is new to the library, so its first total counts
-- from zero.
with snaps as (
  select
    JSONExtractString(payload, 'id') as appid_text,
    JSONExtractString(payload, 'run_id') as run_id,
    argMax(JSONExtractRaw(payload, 'record'), kafka_ts) as record,
    max(parseDateTime64BestEffortOrNull(JSONExtractString(payload, 'extracted_at'), 3, 'UTC')) as at
  from {{ source('raw', 'steam') }}
  where JSONExtractString(payload, 'endpoint') = 'owned_games'
  group by appid_text, run_id
),
series as (
  select
    toUInt32(appid_text) as appid,
    at,
    JSONExtractString(record, 'name') as game,
    JSONExtractUInt(record, 'playtime_forever') as total,
    lagInFrame(toNullable(JSONExtractUInt(record, 'playtime_forever'))) over (
      partition by appid_text order by at
      rows between unbounded preceding and unbounded following
    ) as previous
  from snaps
)
select
  toDate(at) as day,
  appid,
  any(game) as game,
  sum(total - coalesce(previous, 0)) as minutes
from series
where (previous is not null or at > (select min(at) from snaps))
  and total > coalesce(previous, 0)
group by day, appid
