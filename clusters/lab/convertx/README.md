# ConvertX

File conversion in the browser: drop files in, pick a format, download the
results. Behind it are the usual command-line converters - FFmpeg, ImageMagick
and libvips, LibreOffice, Pandoc, Calibre, Inkscape, Ghostscript and more - so
HEIC to JPG, DOCX to PDF, MKV to MP4 and EPUB to MOBI are all one page.
Everything runs in the pod; no file leaves the cluster.

At <https://convert.lab.baakhoff.com>, and on Homepage under Lab.

## Login

Pocket ID through oauth2-proxy, like Homepage. ConvertX's own accounts are
switched off, so there is no ConvertX user to create and no first-run setup
page. Who may reach it is the oauth2-proxy client's *Allowed User Groups* in
Pocket ID - the same setting as every other gated host.

Nobody shares a conversion history. Each visit is its own anonymous user, so
people behind the gate never see each other's files, and history does not
survive leaving the page: download results before closing it.

## What it keeps

Nothing, deliberately. Uploads, results and the job list are on an `emptyDir`
and deleted a day after each job. A pod restart loses them sooner, which costs
a re-upload. So there is no volume and no backup entry.

## What it is not for

Several images into one PDF, in an order you choose. ConvertX converts each
file on its own, so ten photos become ten PDFs. Merging and reordering pages is
a PDF tool's job: Stirling-PDF, at <https://pdf.lab.baakhoff.com>.

## When a conversion fails

The results page says which file failed, not why. The reason is in the log:

```bash
kubectl -n convertx logs deploy/convertx --tail=100
```

A large file that fails with a killed process in the log has usually hit the
container's 2Gi memory limit, most often with a long video or a very large
document. If that happens routinely, raise the limit in `deployment.yaml`.
