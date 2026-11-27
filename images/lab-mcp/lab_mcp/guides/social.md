# social: BMM, social media management

REST with JSON. A list answers {"items": [...]}. An error answers
{"error": {"code": "...", "message": "..."}}, and a 403 names the scope the
server's token lacks. Ids are text. Times are ISO 8601 with an offset.

A profile is a persona: it has accounts (X, Instagram), images and posts.
A post goes to one or more of its profile's accounts, the "targets".

PUBLISHING IS REAL. action "publish" posts at once and "schedule" posts at
the time given, with no confirmation step. Use "draft" unless the person
asked to publish or schedule, and call /posts/validate first.

## The order that works
1. GET /auth/me                     the scopes this token holds
2. GET /profiles                    pick the profile
3. GET /accounts?profileId=ID       the accounts a post can go to
4. POST /media/import               only if the post has an image
5. POST /posts/validate             fix every issue with level "error"
6. POST /posts                      draft, schedule or publish
7. GET /posts/{id}                  per account: the link, or the network's error

## Endpoints
- GET /profiles      POST /profiles {"name": "...", "timezone": "Europe/Belgrade", "notes": "..."}
- GET /profiles/{id}     PATCH /profiles/{id} {...}     DELETE /profiles/{id}
- GET /networks                     which networks are set up, and whether Instagram can publish
- GET /accounts?profileId=ID        DELETE /accounts/{id} disconnects one
  Connecting an account is done by a person in BMM's web app, not here.
- POST /media/import {"profileId": "ID", "url": "https://.../picture.jpg", "alt": "what it shows"}
  or "dataBase64" in place of "url". JPEG, PNG or WebP, up to 20 MB.
- GET /media?profileId=ID     GET /media/{id}     DELETE /media/{id}
- POST /posts/validate {"profileId": "ID", "text": "...", "mediaIds": ["..."], "targets": [{"accountId": "..."}]}
  answers {"ok": true|false, "issues": [{"level": "error|warning", "message": "...", "network": "..."}]}; saves nothing
- POST /posts  the same body, plus "action": "draft" | "schedule" | "publish",
  and for schedule "scheduledAt": "2026-12-01T09:30:00+01:00".
  A target may carry its own "text" for that account only.
- GET /posts?profileId=ID&status=scheduled&limit=50      newest first; &before=<nextBefore> for the next page
  status: draft, scheduled, publishing, published, partial, failed
- GET /posts/{id}     PATCH /posts/{id} {"text": "...", "action": "schedule", "scheduledAt": "..."}
- POST /posts/{id}/retry            try the failed accounts again
- DELETE /posts/{id}                removes it from BMM, not from the network
- GET /audit?limit=50               the audit log, newest first; &action=..., &before=<nextBefore>
- GET /tokens      POST /tokens {"name": "...", "scopes": ["posts:read"], "expiresInDays": 30}      DELETE /tokens/{id}
- GET /system/version
