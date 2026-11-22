# photos: Immich, the photo and video library

REST with JSON. Ids are UUIDs. An image or video answer is saved to the
workspace. Many at once: photos_export. What the key may do is set where the key was made in Immich.

## Endpoints
- POST /search/smart {"query": "dog on a beach", "size": 20, "takenAfter": "2026-01-01T00:00:00Z", "city": "..."}
- POST /search/metadata {"originalFileName": "IMG_", "takenAfter": "...", "takenBefore": "...", "country": "...", "isFavorite": true, "type": "IMAGE", "size": 50}
- GET /assets/{id}                       everything about one photo, EXIF and people included
- PUT /assets/{id} {"description": "...", "isFavorite": true, "rating": 5, "dateTimeOriginal": "...", "latitude": 0, "longitude": 0}
- PUT /assets {"ids": ["..."], "isFavorite": true}          the same change on many
- DELETE /assets {"ids": ["..."], "force": false}           to the trash; force true destroys
- GET /assets/{id}/thumbnail?size=preview                   (or size=thumbnail)
- GET /assets/{id}/original
- GET /albums          POST /albums {"albumName": "...", "assetIds": ["..."]}
- GET /albums/{id}     PATCH /albums/{id} {"albumName": "...", "description": "..."}     DELETE /albums/{id}
- PUT /albums/{id}/assets {"ids": ["..."]}                  DELETE with the same body takes them out
- GET /people          GET /people/{id}      PUT /people/{id} {"name": "..."}
- GET /people/{id}/statistics            how many photos the person is in
- GET /faces?id={asset id}               the faces in one photo: person, and the box in pixels of imageWidth x imageHeight
- POST /search/metadata {"personIds": ["..."], "size": 50}   one person's photos

## People and datasets
photos_people lists the people, photos_by_person one person's photos with
the face boxes, and photos_export puts many photos, whole or cut to the
face, into one zip in the workspace. Use those before the endpoints above.
- GET /tags            GET /memories         GET /server/statistics
- GET /timeline/buckets      GET /search/explore      GET /map/markers

## Uploading a workspace file
api_call("photos", "POST", "/assets", files={"assetData": "holiday.jpg"},
  form={"deviceAssetId": "holiday.jpg-1", "deviceId": "lab-mcp",
        "fileCreatedAt": "2026-07-04T12:00:00Z", "fileModifiedAt": "2026-07-04T12:00:00Z"})
