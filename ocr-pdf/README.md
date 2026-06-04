# ocr-pdf

Turn a scanned PDF (or image) into a **searchable** PDF: the same page images
with an invisible OCR text layer added on top, so the text becomes
selectable, copyable, and readable by other tools. A plain-text `.txt`
sidecar is written alongside it.

Use this when you want a reusable searchable PDF. The `pdf-to-csv` and
`pdf-to-markdown` tools already OCR scans internally, so you only need
`ocr-pdf` when you want the searchable PDF file itself.

## Usage

Double-click **OCR PDF.bat**, or run it from a terminal:

```
python ocr_pdf.py file.pdf [more.pdf ...]
```

With no arguments it opens a file picker. It accepts PDFs and images
(`.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`). For each input, next to
the source file, it writes:

- `<name>_ocr.pdf` (the searchable PDF)
- `<name>_ocr.txt` (the extracted text)

## Requirements

- Python 3.10+ (the script auto-installs its Python packages on first run)
- The **Tesseract OCR engine**, installed separately:
  https://github.com/UB-Mannheim/tesseract/wiki

The script finds `tesseract.exe` on your PATH, via the `TESSERACT_CMD`
environment variable, or in the default install folder. If it cannot be
found, the tool tells you how to fix it.

## License

GNU AGPL-3.0. See the repository [LICENSE](../LICENSE) and
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
