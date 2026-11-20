# models: Manyfold, the 3D model library

REST with JSON-LD answers. Lists page with ?page=. The site's own /api page
is the full reference. The server signs in with the scope in MANYFOLD_SCOPE
("read" unless changed), so writing needs a key made with more scopes.

## Endpoints
- GET /models?page=1                 add ?creator=ID, ?collection=ID or ?tag=name to narrow
- GET /models/{id}                   one model, with its files
- GET /models/{id}/model_files/{file_id}        one file's details; its download address is in the answer
- GET /creators      GET /creators/{id}
- GET /collections   GET /collections/{id}
- PATCH /models/{id} {...}           with a write scope
- DELETE /models/{id}                with a delete scope

The warehouse also has every model and file: see warehouse_tables("manyfold").
