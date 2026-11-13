# This machine

You are running in an agent pod on the homelab cluster, reached through
Remote Control. These notes apply to every project in the pod.

## Sending a file to the person

The app opens a file you send by reading it back from this machine, and it
refuses anything outside the session's working directory. So:

- Put a file meant for the person in `.outbox/` under the current working
  directory, then send it from there. Create the directory if it is missing.
- `.outbox/` is ignored by git on this machine. Never commit or push a file
  only to deliver it.
- Do not send from `/tmp`, the scratchpad or the home directory: the send
  reports success and the person then gets "Can't read this file".
- An image opens in the app. Other files download. To show a rendered page,
  publish it with the Artifact tool; an `.html` file sent as a file is only
  offered as a download.
- Leave what you sent in `.outbox/`. The card in the app stops opening once
  the file is gone.

## Connectors

A notice that a connector "requires authentication" is often stale here. If
the task needs that connector, try the call once before telling the person
to sign in again.

## What is installed

- Documents: `python3` with pypdf, reportlab, python-docx, openpyxl,
  python-pptx, Pillow, pandas, matplotlib, PyYAML, requests and lxml;
  `pdftotext` and `pdftoppm`; `pandoc`; LibreOffice
  (`soffice --headless --convert-to pdf FILE`).
- Media: ImageMagick (`convert`) and `ffmpeg`.
- A screenshot of a web page:
  `chromium --headless --no-sandbox --screenshot=OUT.png --window-size=1280,800 URL`
- Anything else in Python: `uv run --with PACKAGE script.py`. There is no
  `pip` for the system Python.
- `git`, `gh`, `glab`, `jq`, `curl`.
