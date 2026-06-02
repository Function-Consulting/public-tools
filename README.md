# Public Tools

A collection of utility scripts and small applications from [Function Consulting](https://chadaaland.com).
Each tool is self-contained in its own subfolder with its own README.

## Prerequisite: install Python

All four tools are written in Python. Before running any of them, you
need Python 3.10 or newer installed.

If `python --version` in a terminal returns something like `Python 3.12.4`,
you're already set. If not, install one of two ways:

**Easiest (Windows): Microsoft Store**
1. Open Microsoft Store, search "Python 3.12"
2. Click Get / Install
3. Done — PATH is configured automatically

**Cross-platform: python.org**
1. Download from https://www.python.org/downloads/
2. Run the installer
3. **On Windows: check the box "Add python.exe to PATH"** at the bottom of the first screen
4. Open a fresh terminal and verify with `python --version`

`pip` (Python's package installer) is bundled with Python, so you don't need to install it separately.

## Tools

### [extract-convert-combine-to-pdf/](extract-convert-combine-to-pdf/)

One-click receipt packager. Drop the script into a folder, double-click, and it:

1. Extracts real attachments (PDFs, scans) from `.msg` emails — skipping signature logos
2. Converts `.heic` / `.heif` files to `.jpg`
3. Combines every image and PDF in the folder into a single output PDF

Designed for monthly expense-receipt workflows where receipts come in from
multiple sources (phone photos, emailed PDFs, scanned hard copies) and need
to land as one tidy PDF.

### [pdf-to-csv/](pdf-to-csv/)

Double-click desktop utility that extracts every table from a PDF as CSV
files, with a visual preview step before saving. Uses pymupdf's vector-aware
table detection with pdfplumber as a fallback for unruled tables. Stitches
multi-page tables that share an identical header row.

### [pdf-to-markdown/](pdf-to-markdown/)

Double-click desktop utility that converts a PDF into clean, LLM-ready
Markdown using `pymupdf4llm`. Handles multi-column reading order, font-based
heading detection, and tables-as-GitHub-Markdown — substantially better
than block-by-block text extraction when the output is destined for an LLM.

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

[GNU AGPL-3.0](LICENSE) — see the LICENSE file for full text.

In plain English:

- **You can** use these tools for any purpose, including in a commercial business
- **You can** modify them
- **You can** redistribute them
- **You can** charge for your time helping someone implement or use them
- **You must** keep modified copies under AGPL-3.0 (no taking the code closed-source)
- **You must** publish your modifications if you host a modified version as a
  network service (the AGPL "no SaaS loophole" clause)

Intent: free, open-source distribution. Improve it and share back. Don't sell
the software itself as a proprietary product.

### Third-party dependencies

Each tool depends on third-party Python packages with their own licenses.
See **[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)** for the full list —
notably, `pymupdf`, `pymupdf4llm`, and `extract-msg` are all themselves
AGPL/GPL, which is one reason the primary license is AGPL.

## Contributing

Issues and PRs welcome. These tools were originally built for internal use
and have rough edges; clean-ups, bug reports, and feature suggestions all
appreciated.
