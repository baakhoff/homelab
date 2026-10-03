-- Documents added to Paperless per day, by correspondent and type.
select
  toDate(d.added_at) as day,
  if(c.name = '', '(none)', c.name) as correspondent,
  if(t.name = '', '(none)', t.name) as document_type,
  count() as documents,
  sum(d.page_count) as pages
from {{ ref('paperless_documents') }} d
left join {{ ref('paperless_correspondents') }} c on c.id = d.correspondent_id
left join {{ ref('paperless_document_types') }} t on t.id = d.document_type_id
where d.added_at is not null
group by day, correspondent, document_type
