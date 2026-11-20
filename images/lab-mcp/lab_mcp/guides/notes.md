# notes: Outline, the household wiki

Every call is a POST with a JSON body, to /<thing>.<action>. Answers are
{"data": ..., "pagination": ...}. Text is Markdown.

## Endpoints
- POST /documents.search {"query": "boiler", "limit": 10, "collectionId": "..."}
- POST /documents.list {"collectionId": "...", "limit": 25, "offset": 0, "sort": "updatedAt", "direction": "DESC"}
- POST /documents.info {"id": "..."}
- POST /documents.create {"title": "...", "text": "...", "collectionId": "...", "parentDocumentId": "...", "publish": true}
- POST /documents.update {"id": "...", "title": "...", "text": "...", "append": false}
- POST /documents.move {"id": "...", "collectionId": "...", "parentDocumentId": "..."}
- POST /documents.archive {"id": "..."}   and /documents.restore {"id": "..."}
- POST /documents.delete {"id": "..."}    moves it to the trash; add "permanent": true to destroy it
- POST /collections.list {}   /collections.info {"id": "..."}   /collections.create {"name": "..."}
- POST /collections.documents {"id": "..."}   the tree of documents in a collection
- POST /comments.list {"documentId": "..."}   /comments.create {"documentId": "...", "data": {...}}
- POST /users.list {}   /auth.info {}

## Example
api_call("notes", "POST", "/documents.list", body={"limit": 10})
