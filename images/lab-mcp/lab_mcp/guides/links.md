# links: Karakeep, saved links and notes

REST with JSON. Lists page with ?limit= and ?cursor= (the answer's nextCursor).

## Endpoints
- GET /bookmarks?limit=20&archived=false&favourited=true
- GET /bookmarks/search?q=text&limit=20      q also takes is:fav, #tag, url:example.com, after:2026-01-01
- POST /bookmarks {"type": "link", "url": "https://...", "title": "...", "note": "..."}
- POST /bookmarks {"type": "text", "text": "a note", "title": "..."}
- GET /bookmarks/{id}                        add ?includeContent=true for the saved page text
- PATCH /bookmarks/{id} {"title": "...", "note": "...", "archived": true, "favourited": true}
- DELETE /bookmarks/{id}
- POST /bookmarks/{id}/tags {"tags": [{"tagName": "diy"}]}      DELETE with the same body removes them
- GET /tags      GET /tags/{id}/bookmarks      DELETE /tags/{id}
- GET /lists     POST /lists {"name": "...", "icon": "📚"}      GET /lists/{id}/bookmarks
- PUT /lists/{listId}/bookmarks/{bookmarkId}                    DELETE the same path removes it
- GET /highlights
