import os

import uvicorn

from .app import build_app

uvicorn.run(build_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="warning", access_log=False)
