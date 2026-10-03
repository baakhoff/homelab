-- Per day, in the lab's time zone: messages sent and received in the
-- private chats, how many people were written with, voice messages, and
-- calls with their minutes. Days without a message are absent.
select
  toDate(sent_at, 'Europe/Copenhagen') as day,
  countIf(is_outgoing and action is null) as sent,
  countIf(not is_outgoing and action is null) as received,
  uniqExactIf(chat_id, action is null) as chats,
  countIf(media_kind = 'voice') as voice_messages,
  countIf(action = 'PhoneCall' and coalesce(call_duration_s, 0) > 0) as calls,
  countIf(action = 'PhoneCall' and call_end_reason = 'Missed') as missed_calls,
  round(sumIf(coalesce(call_duration_s, 0), action = 'PhoneCall') / 60, 1) as call_minutes
from {{ ref('telegram_messages') }}
where sent_at is not null
group by day
