# Upstream Paperless-ngx plus tesseract's models for the household's languages:
# Russian, Serbian in both scripts, and Kazakh. English is upstream's own.
#
# The upstream image ships English, German, French, Italian and Spanish, and
# offers PAPERLESS_OCR_LANGUAGES to apt-get any other at container start. That
# install runs as root, and this cluster runs the container as uid 1000 - the
# image's own rootless mode, which its docs say plainly cannot install
# languages. So the languages move from boot time to build time: this file,
# built once per upstream release, and nothing at start needs root or the
# internet.
#
# The tag published is the upstream version below, so Renovate can offer the
# next one to the Deployment that pins it. Bumping FROM here is the first of
# the two PRs an upgrade takes - README.md.
FROM ghcr.io/paperless-ngx/paperless-ngx:3.2.1

RUN apt-get update \
 && apt-get install --yes --quiet --no-install-recommends \
      tesseract-ocr-rus \
      tesseract-ocr-srp \
      tesseract-ocr-srp-latn \
      tesseract-ocr-kaz \
 && rm -rf /var/lib/apt/lists/*
