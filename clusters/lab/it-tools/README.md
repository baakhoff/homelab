# IT-Tools

About eighty small tools on one page: QR codes, base64 and URL encoding, JSON
and YAML formatting, UUIDs and passwords, hashes, JWT decoding, cron
expressions, time zones, colour pickers, and more. Everything runs in the
browser. The pod only serves the page, and nothing typed into a tool is sent
anywhere.

At <https://tools.lab.baakhoff.com>, and on Homepage under Lab. Behind Pocket ID
through oauth2-proxy, like ConvertX.

## How it runs

Upstream's image is stock `nginx:alpine` with the built site in it, set up to
run as root on port 80. `nginx.yaml` replaces its server block with the same
site on 8080, and the Deployment runs it as the image's unprivileged `nginx`
user with a read-only root filesystem. No custom build.

Upstream releases rarely. Its image tags are `<date>-<commit>`, and a rule in
`renovate.json5` tells Renovate to compare the dates, which it would not do
otherwise.
