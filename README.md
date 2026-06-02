# Public Tools

A collection of utility scripts and small applications from [Function Consulting](https://chadaaland.com).
Each tool is self-contained in its own subfolder with its own README.

## Tools

### [extract-convert-combine-to-pdf/](extract-convert-combine-to-pdf/)

One-click receipt packager. Drop the script into a folder, double-click, and it:

1. Extracts real attachments (PDFs, scans) from `.msg` emails — skipping signature logos
2. Converts `.heic` / `.heif` files to `.jpg`
3. Combines every image and PDF in the folder into a single output PDF

Designed for monthly expense-receipt workflows where receipts come in from
multiple sources (phone photos, emailed PDFs, scanned hard copies) and need
to land as one tidy PDF.

### [w9-catchup/](w9-catchup/)

OCR + review tool for catching up on a backlog of historical IRS Form W-9 PDFs.
Flask web app that:

- OCRs every PDF in a configured root folder (`pdfplumber` for text-layer PDFs, Tesseract for scans)
- Fuzzy-matches each W-9 to a vendor in your ERP via ODBC
- Provides a side-by-side review UI (PDF on the left, extracted fields on the right) for manual verification
- Exports a CSV ready for bulk vendor-compliance import

Built for a one-time historical backfill of ~700 W-9s, but reusable wherever
W-9 OCR + vendor matching is useful.

## License

[MIT](LICENSE) — use, modify, redistribute freely with attribution. No warranty.

The MIT license covers the source code authored by Function Consulting in
this repository. Each tool depends on third-party Python packages with their
own licenses; see **[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)** for
the full list, including one notable copyleft (GPL-3.0) dependency in the
receipt-packager tool.

## Contributing

Issues and PRs welcome. These tools were originally built for internal use
and have rough edges; clean-ups, bug reports, and feature suggestions all
appreciated.
