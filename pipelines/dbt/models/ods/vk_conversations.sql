-- VK conversations, one row each: the name VK showed for it, whether it was
-- a group chat, and the messages in it - from the data archive. A
-- conversation the archive's index does not name still appears, named
-- from its messages.
with named as (
  select id as conversation_id, JSONExtractString(record, 'name') as name
  from ({{ accumulated_records('vk', ['vk/conversations']) }})
),
stats as (
  select
    conversation_id,
    any(conversation_name) as name_from_messages,
    count() as messages,
    countIf(is_outgoing) as sent,
    min(sent_at_local) as first_at_local,
    max(sent_at_local) as last_at_local
  from {{ ref('vk_messages') }}
  group by conversation_id
)
select
  cid as conversation_id,
  if(index_name != '', index_name, message_name) as name,
  toInt64OrZero(cid) >= 2000000000 as is_group_chat,
  messages,
  sent,
  first_at_local,
  last_at_local
from (
  -- One side of the outer join can be missing: its columns are then empty
  -- or NULL, depending on join_use_nulls.
  select
    if(ifNull(n.conversation_id, '') != '', n.conversation_id, s.conversation_id) as cid,
    ifNull(n.name, '') as index_name,
    ifNull(s.name_from_messages, '') as message_name,
    ifNull(s.messages, 0) as messages,
    ifNull(s.sent, 0) as sent,
    nullIf(s.first_at_local, toDateTime(0)) as first_at_local,
    nullIf(s.last_at_local, toDateTime(0)) as last_at_local
  from named as n
  full outer join stats as s on s.conversation_id = n.conversation_id
)
