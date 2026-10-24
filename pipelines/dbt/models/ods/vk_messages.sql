-- VK messages, one row each, from the account's data archive (the account
-- was deleted in 2020; pipelines/vk.md). `conversation_id` is VK's: a
-- person's user id, or 2000000000 and up for a group chat.
--
-- `sent_at_local` is the time as the archive wrote it, in the time zone the
-- account was set to - stored as a date-time without a zone, so compare it
-- with other sources' UTC times with that in mind. Attachments are VK's
-- description of each ("Фотография", "Аудиозапись", ...) and its links,
-- which mostly no longer resolve.
select
  id as message_key,
  JSONExtractString(record, 'conversation_id') as conversation_id,
  toInt64OrZero(conversation_id) >= 2000000000 as is_group_chat,
  JSONExtractString(record, 'conversation_name') as conversation_name,
  JSONExtractBool(record, 'outgoing') as is_outgoing,
  nullIf(JSONExtractString(record, 'sender_name'), '') as sender_name,
  nullIf(JSONExtractString(record, 'sender_link'), '') as sender_link,
  nullIf(extract(JSONExtractString(record, 'sender_link'), 'vk\\.com/id(\\d+)'), '') as sender_vk_id,
  parseDateTimeBestEffortOrNull(JSONExtractString(record, 'time')) as sent_at_local,
  JSONExtractString(record, 'time_text') as sent_text,
  JSONExtractBool(record, 'edited') as is_edited,
  JSONExtractString(record, 'text') as text,
  arrayMap(a -> JSONExtractString(a, 'description'), JSONExtractArrayRaw(record, 'attachments')) as attachments,
  arrayFlatten(arrayMap(a -> JSONExtract(a, 'links', 'Array(String)'), JSONExtractArrayRaw(record, 'attachments'))) as attachment_links,
  extracted_at
from ({{ accumulated_records('vk', ['vk/messages']) }})
