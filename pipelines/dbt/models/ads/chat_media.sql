-- The photos and videos sent in Telegram and VK chats, as they are in
-- Immich: one row per picture and message it was sent in - who sent it,
-- when, in which chat, with what text, and what Claude saw in it.
--
-- The tie is the hash in the file's name (ods.immich_assets), made when
-- the file was fetched: for Telegram the first 12 hex digits of
-- sha256("<account's user id>/<chat id>/<message id>")
-- (pipelines/tools/telegram_media.py, ingest_telegram), for VK of
-- sha256(<the link>) (pipelines/tools/vk_media.py). A VK link sent in
-- several messages is one file, and a row for each; the same file sent in
-- two Telegram chats is stored once by Immich, under the first name it
-- came with, so only that message has it. A picture whose message is not
-- in the warehouse - a VK wall or album entry, a Telegram group with
-- --groups - is a row with the message's columns empty.
--
-- `sent_at` is UTC, for Telegram; VK's archive wrote local time, so for VK
-- it is empty and `sent_at_local` holds it. `sender` is the chat's person
-- for what they sent, NULL for the account's own. `immich_url` opens the
-- picture; `type` and `description` are immich_sort's, once it has looked.
with
assets as (
  select asset_id, file_name, kind, source, file_hash, taken_at
  from {{ ref('immich_assets') }}
  where file_hash is not null
),
owners as (
  select account, any(user_id) as owner_id
  from {{ ref('telegram_chats') }}
  where is_self
  group by account
),
telegram as (
  select
    substring(lower(hex(SHA256(concat(toString(o.owner_id), '/', toString(m.chat_id), '/', toString(m.message_id))))), 1, 12) as file_hash,
    m.account as account,
    m.chat_key as chat_key,
    c.name as chat_name,
    m.message_key as message_key,
    m.sent_at as sent_at,
    CAST(NULL, 'Nullable(DateTime)') as sent_at_local,
    m.is_outgoing as is_outgoing,
    if(m.is_outgoing, NULL, c.name) as sender,
    m.text as text,
    m.media_kind as media_kind,
    m.is_forwarded as is_forwarded,
    m.forwarded_from_name as forwarded_from,
    m.reply_to_message_id as reply_to_message_id,
    m.album_id as album_id
  from {{ ref('telegram_messages') }} m
  inner join owners o on o.account = m.account
  left join {{ ref('telegram_chats') }} c on c.chat_key = m.chat_key
  where m.media_kind is not null
),
vk as (
  select
    substring(lower(hex(SHA256(link))), 1, 12) as file_hash,
    'vk' as account,
    m.conversation_id as chat_key,
    m.conversation_name as chat_name,
    m.message_key as message_key,
    CAST(NULL, 'Nullable(DateTime64(3, \'UTC\'))') as sent_at,
    m.sent_at_local as sent_at_local,
    m.is_outgoing as is_outgoing,
    if(m.is_outgoing, NULL, m.sender_name) as sender,
    m.text as text,
    CAST(NULL, 'Nullable(String)') as media_kind,
    false as is_forwarded,
    CAST(NULL, 'Nullable(String)') as forwarded_from,
    CAST(NULL, 'Nullable(Int64)') as reply_to_message_id,
    CAST(NULL, 'Nullable(Int64)') as album_id
  from {{ ref('vk_messages') }} m
  array join m.attachment_links as link
),
messages as (
  select 'telegram' as source, * from telegram
  union all
  select 'vk' as source, * from vk
)
select
  a.asset_id as asset_id,
  concat('https://photos.lab.baakhoff.com/photos/', a.asset_id) as immich_url,
  a.file_name as file_name,
  a.kind as kind,
  a.source as source,
  m.account as account,
  m.chat_key as chat_key,
  m.chat_name as chat_name,
  m.message_key as message_key,
  m.sent_at as sent_at,
  m.sent_at_local as sent_at_local,
  m.is_outgoing as is_outgoing,
  m.sender as sender,
  m.text as text,
  m.media_kind as media_kind,
  m.is_forwarded as is_forwarded,
  m.forwarded_from as forwarded_from,
  m.reply_to_message_id as reply_to_message_id,
  m.album_id as album_id,
  p.type as type,
  p.description as description,
  p.city as city,
  p.country as country,
  a.taken_at as taken_at
from assets a
left join messages m on m.source = a.source and m.file_hash = a.file_hash
left join {{ ref('immich_photos') }} p on p.asset_id = a.asset_id
settings join_use_nulls = 1
