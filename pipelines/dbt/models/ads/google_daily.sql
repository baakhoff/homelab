-- Per day, from the Google account: mail in and out, time in meetings,
-- searches, YouTube and pages browsed. A source with no rows that day
-- counts zero - mail and the calendar are complete, but My Activity and
-- Chrome go back only as far as Google kept them.
--
-- Meetings are timed events (not all-day) that were not cancelled and
-- that the account did not decline.
with
  mail as (
    select toDate(received_at) as day,
      countIf(not is_sent and not is_spam) as mails_received,
      countIf(is_sent) as mails_sent
    from {{ ref('google_gmail_messages') }} group by day
  ),
  meetings as (
    select toDate(starts_at) as day, count() as meetings,
      sum(dateDiff('minute', starts_at, ends_at)) / 60 as meeting_hours
    from {{ ref('google_calendar_events') }}
    where not all_day and status != 'cancelled' and my_response != 'declined'
      and starts_at is not null and ends_at is not null
    group by day
  ),
  activity as (
    select toDate(happened_at) as day,
      countIf(resource = 'search' and not from_ads) as searches,
      countIf(resource = 'youtube' and startsWith(title, 'Watched ') and not from_ads) as youtube_watched,
      countIf(resource = 'maps' and not from_ads) as maps_actions,
      countIf(from_ads) as ads_seen
    from {{ ref('google_activity') }} where happened_at is not null group by day
  ),
  browsing as (
    select toDate(visited_at) as day, count() as pages_visited
    from {{ ref('google_chrome_history') }} where visited_at is not null group by day
  ),
  days as (
    select day from mail union distinct select day from meetings
    union distinct select day from activity union distinct select day from browsing
  )
select
  d.day as day,
  m.mails_received as mails_received,
  m.mails_sent as mails_sent,
  c.meetings as meetings,
  coalesce(c.meeting_hours, 0) as meeting_hours,
  a.searches as searches,
  a.youtube_watched as youtube_watched,
  a.maps_actions as maps_actions,
  a.ads_seen as ads_seen,
  b.pages_visited as pages_visited
from days d
left join mail m on m.day = d.day
left join meetings c on c.day = d.day
left join activity a on a.day = d.day
left join browsing b on b.day = d.day
