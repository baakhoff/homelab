# Stirling-PDF

The PDF workbench: merge, split, reorder, rotate, compress, sign, redact and
watermark PDFs, convert them to and from images and Office files, and build one
PDF from a stack of images. Every operation runs in the pod; no file leaves the
cluster.

At <https://pdf.lab.baakhoff.com>, and on Homepage under Lab.

## Several images into one PDF

**Convert**, from image to PDF: drop the images in, put them in order, and
leave *Combine Images* on. The result downloads as one file.
A scanned letter made this way is ready for Paperless, which OCRs it on
upload in the household's languages.

For single files between formats (HEIC to JPG, DOCX to PDF, video) ConvertX is
the better tool, at <https://convert.lab.baakhoff.com>.

## Login

Pocket ID through oauth2-proxy, like Homepage and ConvertX. Stirling-PDF's own
login is switched off with `SECURITY_ENABLELOGIN=false`: it is on by default in
the image, and would otherwise put a first-run admin account behind the gate.
Who may reach it is the oauth2-proxy client's *Allowed User Groups* in
Pocket ID.

## What it keeps

Nothing. Each operation is one request in and one file out, and every
directory the app writes is an `emptyDir`, including the settings file, which
is regenerated from the image's template and the Deployment's env on every
start. No volume, no backup entry. Configuration is changed in
`deployment.yaml`, not in the UI's settings page, which would be forgotten at
the next restart.

## OCR here, and why it is left alone

Stirling-PDF has an OCR tool, and its image carries English, German, French,
Portuguese and Chinese. None of the household's other languages (Russian,
Serbian, Kazakh) are in it. Adding them would mean our own image, as for
Paperless. That is not worth doing for a tool whose output goes to Paperless
anyway, which already OCRs in all of them.

## When an operation fails

The browser shows an error; the reason is in the log:

```bash
kubectl -n stirling-pdf logs deploy/stirling-pdf --tail=100
```

A 504 from nginx means the operation outran the Ingress's 10-minute read
timeout, which is only likely for OCR of a very long scan. A restart with
`OOMKilled` in `kubectl -n stirling-pdf describe pod` means it outgrew the 2Gi
limit. Both are raised in this directory.
