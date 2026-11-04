-- The Steam library, one row per game as it stands now: total playtime,
-- and per platform - Windows, Mac, Linux, Steam Deck - the last two weeks'
-- playtime, and when it was last played. Steam counts minutes. A game gone
-- from the library drops out at the next run.
with recent as (
  select id, record from ({{ snapshot_records('steam', 'recently_played') }})
)
select
  toUInt32(g.id) as appid,
  JSONExtractString(g.record, 'name') as name,
  JSONExtractUInt(g.record, 'playtime_forever') as playtime_minutes,
  JSONExtractUInt(g.record, 'playtime_windows_forever') as windows_minutes,
  JSONExtractUInt(g.record, 'playtime_mac_forever') as mac_minutes,
  JSONExtractUInt(g.record, 'playtime_linux_forever') as linux_minutes,
  JSONExtractUInt(g.record, 'playtime_deck_forever') as deck_minutes,
  JSONExtractUInt(g.record, 'playtime_disconnected') as offline_minutes,
  JSONExtractUInt(r.record, 'playtime_2weeks') as two_weeks_minutes,
  if(JSONExtractUInt(g.record, 'rtime_last_played') = 0, NULL,
     toDateTime(JSONExtractUInt(g.record, 'rtime_last_played'), 'UTC')) as last_played_at,
  JSONExtractBool(g.record, 'has_community_visible_stats') as has_achievements,
  g.extracted_at
from ({{ snapshot_records('steam', 'owned_games') }}) g
left join recent r on r.id = g.id
