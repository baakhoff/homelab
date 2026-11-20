# documents: Paperless-ngx, scanned paper

REST with JSON. Every path ends in a slash. Lists answer
{"count", "next", "results"}. Tags, correspondents and types are numbers:
look their ids up first. api_find("documents", "keyword") searches the full API.

## Endpoints
- GET /documents/?query=warranty&page_size=20&ordering=-created
  more filters: tags__id__all=1,2  correspondent__id=3  document_type__id=4  created__date__gt=2026-01-01  title__icontains=x
- GET /documents/{id}/                    its fields and full text ("content")
- PATCH /documents/{id}/ {"title": "...", "correspondent": 3, "document_type": 4, "tags": [1, 2], "created": "2026-03-02"}
- DELETE /documents/{id}/                 to the trash
- GET /documents/{id}/download/           the PDF (add ?original=true for the file as scanned)
- GET /documents/{id}/preview/            GET /documents/{id}/thumb/
- GET /documents/{id}/notes/              POST /documents/{id}/notes/ {"note": "..."}
- GET /documents/{id}/suggestions/        what Paperless would file it as
- POST /documents/post_document/          upload: files={"document": "scan.pdf"}, form={"title": "..."}
- POST /documents/bulk_edit/ {"documents": [1, 2], "method": "add_tag", "parameters": {"tag": 5}}
  methods: set_correspondent, set_document_type, add_tag, remove_tag, modify_tags, delete, merge, split, rotate, reprocess
- GET /tags/   POST /tags/ {"name": "..."}      the same shape for /correspondents/, /document_types/, /storage_paths/, /custom_fields/
- GET /search/?query=x                    across documents, tags, correspondents
- GET /statistics/   GET /tasks/   GET /saved_views/   GET /trash/
