# cobalt-web image

cobalt's web page, for `clusters/lab/cobalt/`. Upstream publishes the download
API as `ghcr.io/imputnet/cobalt` but not the page. The page is a static
SvelteKit build with the API's address compiled in, so every instance builds
its own. This directory is that build, served by unprivileged nginx.

## Where the source comes from

From the API image. It ships the repository's `.git`, a shallow clone of the
commit the API was built from. The first stage copies that and checks it out,
so the page is always built from the same commit as the API it talks to. cobalt
does not tag source releases, so there is no better pin. If a future API image
drops `.git`, the build fails at the checkout, before anything is published.

## How it is built

`.github/workflows/cobalt-web-image.yml` builds this directory on every push to
`main` that touches it and publishes `ghcr.io/baakhoff/cobalt-web:<version>`,
the version read from the API image's tag in the `FROM` line. Renovate bumps
that line. Then the kubernetes manager sees the new web tag on GHCR and offers
it to the Deployment, along with the API image of the same version. Two PRs
per upgrade, as for the Paperless image. Merge them in that order: the
Deployment PR only makes sense once the build has published.

The hostname is compiled into the page. Moving cobalt to another host means
changing `WEB_HOST` and `WEB_DEFAULT_API` here, and the Ingress, together.

The first build creates the package, and the nodes pull anonymously. If the
pod reports `ErrImagePull`, check the package's visibility under GitHub →
Packages first.

## Licence

cobalt's web code is CC BY-NC-SA 4.0, and its branding may be used only by an
unmodified, non-commercial instance. This build changes nothing in the source;
it only sets the two build variables upstream documents.
