# money: Firefly III, the household's books

REST with JSON:API answers: {"data": [{"id", "attributes": {...}}], "meta"}.
Paths here map onto Firefly's /api/v1. GET, POST, PUT and DELETE work (no
PATCH). Amounts are strings. A DELETE is final: Firefly has no trash.

## Endpoints
- GET /accounts?type=asset&limit=50        types: asset, expense, revenue, liabilities, cash, all
- GET /accounts/{id}                       GET /accounts/{id}/transactions?start=2026-11-01&end=2026-11-30
- GET /transactions?start=2026-11-01&end=2026-11-30&type=all&limit=50&page=1
  types: all, withdrawal, deposit, transfer
- GET /transactions/{id}
- POST /transactions {"transactions": [{"type": "withdrawal", "date": "2026-11-20", "amount": "12.50",
    "description": "Bread", "source_name": "Main account", "destination_name": "Bakery",
    "category_name": "Groceries", "budget_name": "Food", "tags": ["x"], "notes": "..."}]}
  a deposit goes from a revenue name to an asset account; a transfer between two asset accounts
- PUT /transactions/{id} {"transactions": [{...the fields to change...}]}
- DELETE /transactions/{id}
- GET /search/transactions?query=bread      also: category:Groceries amount_more:50 date_after:2026-01-01
- GET /budgets     GET /budgets/{id}/limits?start=&end=      GET /categories     GET /tags
- GET /bills       GET /piggy-banks       GET /recurrences   GET /rules
- GET /summary/basic?start=2026-11-01&end=2026-11-30         totals: earned, spent, net worth
- GET /insight/expense/category?start=&end=                  spending by category
- GET /insight/income/category?start=&end=                   GET /insight/expense/budget?start=&end=
- GET /data/export/transactions?start=&end=&type=csv         saved as a file
