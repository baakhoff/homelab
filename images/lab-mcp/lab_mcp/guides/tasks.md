# tasks: Vikunja, to-do lists

REST. Unusual: PUT creates and POST updates. An update replaces the whole
object, so GET it first, change fields, and POST all of it back.
api_find("tasks", "keyword") searches the full API.

## Endpoints
- GET /projects            PUT /projects {"title": "..."}          DELETE /projects/{id}
- GET /tasks?s=text&filter=done = false&sort_by=due_date&order_by=asc&per_page=50
- GET /projects/{id}/tasks
- PUT /projects/{id}/tasks {"title": "...", "description": "...", "due_date": "2026-12-01T12:00:00Z", "priority": 3}
- GET /tasks/{id}          POST /tasks/{id} {whole task}           DELETE /tasks/{id}
- GET /labels              PUT /labels {"title": "...", "hex_color": "ff0000"}
- PUT /tasks/{id}/labels {"label_id": 3}       DELETE /tasks/{id}/labels/{label_id}
- GET /tasks/{id}/comments PUT /tasks/{id}/comments {"comment": "..."}
- PUT /tasks/{id}/assignees {"user_id": 1}
- GET /projects/{id}/views/{view}/buckets      the kanban columns

Filters look like: done = false && due_date < now+7d && priority >= 3
A due date of 0001-01-01 means "none".
