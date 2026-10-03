-- Private chats: one row per person the account has a one-to-one chat with,
-- and one for its own Saved Messages. A snapshot every run, so a chat
-- deleted in Telegram drops out (its messages stay in telegram_messages).
select
  toInt64OrNull(id) as chat_id,
  JSONExtractString(record, 'name') as name,
  JSONExtractString(record, 'first_name') as first_name,
  JSONExtractString(record, 'last_name') as last_name,
  JSONExtractString(record, 'username') as username,
  JSONExtractBool(record, 'is_self') as is_self,
  JSONExtractBool(record, 'is_contact') as is_contact,
  JSONExtractBool(record, 'is_mutual_contact') as is_mutual_contact,
  JSONExtractBool(record, 'is_deleted') as is_deleted,
  JSONExtractBool(record, 'archived') as archived,
  JSONExtractInt(record, 'unread_count') as unread_count,
  {{ ts("JSONExtractString(record, 'last_message_at')") }} as last_message_at,
  extracted_at
from ({{ snapshot_records('telegram', 'chats') }})
