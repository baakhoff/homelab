# social: BMM, social media management

REST with JSON. A list answers {"items": [...]}. An error answers
{"error": {"code": "...", "message": "..."}}, and a 403 names the scope the
server's token lacks. BMM is young: today it has sign-in, API tokens and the
audit log. Profiles, accounts, posts, media and analytics come with later
releases, and api_find("social", "word") shows what the running version has.

## Endpoints
- GET /auth/me                    who this token is and the scopes it holds: call it first
- GET /system/version             the running version, and whether a newer one exists
- GET /audit?limit=50             the audit log, newest first; add &action=... to narrow,
                                  and &before=<nextBefore from the last answer> for the next page
- GET /tokens                     the API tokens, without their secrets
- POST /tokens {"name": "...", "scopes": ["posts:read"], "expiresInDays": 30}
                                  only with scopes this token holds itself; the secret is in the answer once
- DELETE /tokens/{id}
