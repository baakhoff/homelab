# paperless-ngx image

Upstream `ghcr.io/paperless-ngx/paperless-ngx` with the Danish tesseract
language added at build time, for `clusters/lab/paperless/`. Nothing else
changes: same entrypoint, same user, same ports.

## Why a build at all

Paperless installs extra OCR languages with `apt-get` when the container
starts, which needs root. The Deployment runs the container as uid 1000, the
image's rootless mode, and its documentation is explicit that the two do not
combine. A layer with the package already in it is the whole difference.

## How it is built

`.github/workflows/paperless-ngx-image.yml` builds this directory on every push
to `main` that touches it and publishes
`ghcr.io/baakhoff/paperless-ngx:<upstream-version>`, the version read from the
`FROM` line. Renovate's dockerfile manager bumps that line; the kubernetes
manager then sees the new tag on GHCR and offers it to the Deployment. Two
PRs per upgrade, as for the agent image.

The tag is mutable in the same way the agent image's is, and the Deployment
does not pin `imagePullPolicy: Always` because the only thing that changes
under a tag here is this one apt package. If that ever stops being true, the
agent image README has the trade written out.

The first build is the one to watch: the package is created by that push, and
the nodes pull anonymously. If the pod reports `ErrImagePull`, the package's
visibility on GitHub → Packages is the first thing to check.
