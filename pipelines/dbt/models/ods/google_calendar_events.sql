-- Calendar events, one row per occurrence: a recurring event is one row per
-- time it happens, up to a year ahead (pipelines/dags/google.py). The key
-- is calendar and event together - the same event can sit in two calendars.
-- All-day events start and end at midnight UTC of their dates.
select
  id as event_key,
  splitByChar('/', id)[1] as calendar_id,
  JSONExtractString(record, 'id') as event_id,
  JSONExtractString(record, 'recurringEventId') as recurring_event_id,
  JSONExtractString(record, 'status') as status,
  JSONExtractString(record, 'eventType') as event_type,
  JSONExtractString(record, 'summary') as summary,
  JSONExtractString(record, 'location') as location,
  JSONExtractString(record, 'start', 'date') != '' as all_day,
  {{ ts("if(JSONExtractString(record, 'start', 'dateTime') != '', JSONExtractString(record, 'start', 'dateTime'), JSONExtractString(record, 'start', 'date'))") }} as starts_at,
  {{ ts("if(JSONExtractString(record, 'end', 'dateTime') != '', JSONExtractString(record, 'end', 'dateTime'), JSONExtractString(record, 'end', 'date'))") }} as ends_at,
  JSONExtractString(record, 'organizer', 'email') as organizer,
  JSONExtractBool(record, 'organizer', 'self') as organized_by_me,
  length(JSONExtractArrayRaw(record, 'attendees')) as attendees,
  JSONExtractString(arrayFirst(a -> JSONExtractBool(a, 'self'), JSONExtractArrayRaw(record, 'attendees')), 'responseStatus') as my_response,
  JSONExtractString(record, 'hangoutLink') != '' or JSONExtractString(record, 'conferenceData', 'conferenceId') != '' as is_video_call,
  {{ ts("JSONExtractString(record, 'created')") }} as created_at,
  {{ ts("JSONExtractString(record, 'updated')") }} as updated_at,
  extracted_at
from ({{ snapshot_records('google', 'calendar/events') }})
