# pdf: Stirling-PDF, heavy PDF work

Every call is a POST that uploads workspace files as a form and answers
with a file, which is saved to the workspace (name it with save_as). The
file field is "fileInput". api_find("pdf", "keyword") gives the exact
fields of any operation: check it before a first use.

For joining, taking pages out and reading text, the pdf_merge, pdf_split
and file_text tools are quicker and need none of this.

## Endpoints
- POST /misc/ocr-pdf            form: languages (repeatable: eng, rus, srp, kaz), ocrType (skip-text | force-ocr), ocrRenderType (hocr | sandwich)
- POST /misc/compress-pdf       form: optimizeLevel (1-9)
- POST /general/rotate-pdf      form: angle (90, 180, 270)
- POST /general/merge-pdfs      files: {"fileInput": ["a.pdf", "b.pdf"]}
- POST /general/split-pages     form: pageNumbers ("1,3,5-9")
- POST /general/remove-pages    form: pageNumbers
- POST /convert/pdf/img         form: imageFormat (png | jpg), singleOrMultiple (single | multiple), dpi
- POST /convert/img/pdf         images to one PDF
- POST /convert/file/pdf        an office document (docx, xlsx, pptx, odt) to PDF
- POST /convert/pdf/word        form: outputFormat (docx | odt)
- POST /convert/pdf/text        form: outputFormat (txt | rtf)
- POST /convert/html/pdf        POST /convert/markdown/pdf
- POST /security/add-password   form: password      POST /security/remove-password   form: password
- POST /security/add-watermark  form: watermarkType (text), watermarkText
- POST /misc/add-page-numbers   POST /misc/extract-images   POST /misc/flatten   POST /misc/repair

## Example
api_call("pdf", "POST", "/misc/compress-pdf", files={"fileInput": "scan.pdf"},
  form={"optimizeLevel": 5}, save_as="scan-small.pdf")
