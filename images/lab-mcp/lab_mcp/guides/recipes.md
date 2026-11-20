# recipes: Mealie

REST with JSON. Lists answer {"items", "page", "total"}. A recipe is known
by its slug. api_find("recipes", "keyword") searches the full API.

## Endpoints
- GET /recipes?search=soup&perPage=20&page=1&orderBy=created_at&orderDirection=desc
- GET /recipes/{slug}
- POST /recipes {"name": "..."}                 answers the new slug; then PATCH the rest in
- PATCH /recipes/{slug} {"description": "...", "recipeYield": "4", "recipeIngredient": [{"note": "3 beets"}], "recipeInstructions": [{"text": "Boil."}]}
- DELETE /recipes/{slug}
- POST /recipes/create/url {"url": "https://...", "includeTags": true}     import a recipe from a web page
- GET /organizers/categories    GET /organizers/tags    GET /foods    GET /units
- GET /households/mealplans?start_date=2026-11-17&end_date=2026-11-23
- POST /households/mealplans {"date": "2026-11-21", "entryType": "dinner", "recipeId": "...", "title": ""}
- GET /households/mealplans/today
- GET /households/shopping/lists                GET /households/shopping/lists/{id}
- POST /households/shopping/items {"shoppingListId": "...", "note": "milk", "quantity": 1}
- PUT /households/shopping/items/{id} {whole item, "checked": true}
- DELETE /households/shopping/items/{id}
- GET /households/cookbooks     GET /users/self
