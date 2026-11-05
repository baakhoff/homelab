-- One row per saved bookmark in the account whose key the ingest uses: a
-- link, a note or an uploaded image or PDF. For a link, its page's title,
-- site and readable text; for a note, its text; for a file, the text read
-- out of it. Then the tags - each marked as given by a person or by the AI -
-- the AI's summary, and your own note. A bookmark deleted in Karakeep is
-- gone from the next snapshot, and so from here.
--
-- text is plain text: a link's page arrives as HTML and is stripped here.
select
  id as bookmark_id,
  JSONExtractString(record, 'content', 'type') as kind,
  coalesce(
    nullIf(JSONExtractString(record, 'title'), ''),
    nullIf(JSONExtractString(record, 'content', 'title'), ''),
    nullIf(JSONExtractString(record, 'content', 'fileName'), '')
  ) as title,
  nullIf(coalesce(
    nullIf(JSONExtractString(record, 'content', 'url'), ''),
    nullIf(JSONExtractString(record, 'content', 'sourceUrl'), '')
  ), '') as url,
  nullIf(domain(JSONExtractString(record, 'content', 'url')), '') as site,
  nullIf(JSONExtractString(record, 'content', 'description'), '') as description,
  nullIf(JSONExtractString(record, 'content', 'author'), '') as author,
  nullIf(JSONExtractString(record, 'content', 'publisher'), '') as publisher,
  multiIf(
    JSONExtractString(record, 'content', 'type') = 'link',
      extractTextFromHTML(JSONExtractString(record, 'content', 'htmlContent')),
    JSONExtractString(record, 'content', 'type') = 'text',
      JSONExtractString(record, 'content', 'text'),
    JSONExtractString(record, 'content', 'content')
  ) as text,
  nullIf(JSONExtractString(record, 'summary'), '') as summary,
  nullIf(JSONExtractString(record, 'note'), '') as note,
  arrayMap(t -> JSONExtractString(t, 'name'), JSONExtractArrayRaw(record, 'tags')) as tags,
  arrayMap(t -> JSONExtractString(t, 'name'),
    arrayFilter(t -> JSONExtractString(t, 'attachedBy') = 'ai', JSONExtractArrayRaw(record, 'tags'))) as ai_tags,
  JSONExtractBool(record, 'favourited') as favourited,
  JSONExtractBool(record, 'archived') as archived,
  nullIf(JSONExtractString(record, 'source'), '') as saved_from,
  nullIf(JSONExtractString(record, 'content', 'videoAssetId'), '') is not null as has_video,
  {{ ts("JSONExtractString(record, 'createdAt')") }} as created_at,
  {{ ts("JSONExtractString(record, 'modifiedAt')") }} as modified_at,
  {{ ts("JSONExtractString(record, 'content', 'datePublished')") }} as published_at,
  extracted_at
from ({{ snapshot_records('karakeep', 'bookmarks') }})
