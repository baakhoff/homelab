-- Every calendar the account has in its list: its own, shared ones,
-- subscriptions such as holidays.
select
  id as calendar_id,
  if(JSONExtractString(record, 'summaryOverride') != '',
     JSONExtractString(record, 'summaryOverride'),
     JSONExtractString(record, 'summary')) as name,
  JSONExtractString(record, 'accessRole') as access_role,
  JSONExtractBool(record, 'primary') as is_primary,
  JSONExtractBool(record, 'hidden') as is_hidden,
  JSONExtractString(record, 'timeZone') as time_zone,
  extracted_at
from ({{ snapshot_records('google', 'calendar/calendars') }})
