# location: Dawarich, location history

REST with JSON, for the account the key belongs to. Times are ISO 8601.
The site's own /api-docs page is the full reference.

## Endpoints
- GET /points?start_at=2026-11-01T00:00:00Z&end_at=2026-11-02T00:00:00Z&per_page=500&page=1&order=asc
- GET /stats                          distance and places, by year and month
- GET /visits?start_at=...&end_at=...
- GET /areas       POST /areas {"name": "Home", "latitude": 0, "longitude": 0, "radius": 100}       DELETE /areas/{id}
- GET /countries/visited_cities?start_at=...&end_at=...
- GET /health

The warehouse also has the points: see warehouse_tables("dawarich").
