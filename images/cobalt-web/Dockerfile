# cobalt's web page, built for this lab. Upstream publishes the API as an
# image but not the web page; it is a static site with the API's address baked
# in at build time, and a hosted instance is expected to build its own.
#
# Built from the API image itself. That image carries the repository's .git,
# a shallow clone of the exact commit it was built from, so checking it out
# gives the web source that belongs with this API version and no other.
# cobalt tags no source releases, so this is the one pin that keeps the two
# halves in step. Renovate bumps the line below; the tag published is the
# same version, for the Deployment to pin - README.md has the two-PR flow.
FROM ghcr.io/imputnet/cobalt:11.7.1 AS api

FROM node:24.21.0-alpine AS build
WORKDIR /src
RUN apk add --no-cache git
COPY --from=api /app/.git .git
RUN git checkout HEAD -- .

# The page calls the API at its own origin: the Deployment serves both from
# one host, so the Pocket ID cookie covers the API calls too.
ENV WEB_HOST=cobalt.lab.baakhoff.com \
    WEB_DEFAULT_API=https://cobalt.lab.baakhoff.com/ \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable \
 && pnpm install --frozen-lockfile --filter "@imput/cobalt-web..." \
 && pnpm --filter @imput/cobalt-web build

# Static files only. The server config - which paths go to the API, and the
# headers the page needs - lives with the Deployment, in a ConfigMap.
FROM nginxinc/nginx-unprivileged:1.31.6-alpine
COPY --from=build /src/web/build /usr/share/nginx/html
