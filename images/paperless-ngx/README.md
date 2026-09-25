# paperless-ngx image

Upstream `ghcr.io/paperless-ngx/paperless-ngx` with the Russian, Serbian
(Cyrillic and Latin) and Kazakh tesseract languages added at build time, for `clusters/lab/paperless/`. Nothing else
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

The tag is mutable in the same way the agent image's is: changing the
languages here rebuilds the same upstream version under the same tag. So the
Deployment pins `imagePullPolicy: Always`, for the reason the agent image
README writes out - with `IfNotPresent` a node that already holds the tag never
pulls the rebuild, however often the pod restarts.

Adding a language is therefore two PRs as well: this file first, and only once
the build has published, the `PAPERLESS_OCR_LANGUAGE` change in the
Deployment. The other order restarts the pod on the old image with a language
it does not have.

The first build is the one to watch: the package is created by that push, and
the nodes pull anonymously. If the pod reports `ErrImagePull`, the package's
visibility on GitHub → Packages is the first thing to check.
