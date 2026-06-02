# W-9 Catch-Up

A self-hosted Flask web app for OCR + manual review of a backlog of
IRS Form W-9 PDFs, with optional fuzzy-matching against a vendor master
in an external ERP via ODBC.

## What problem it solves

Most ERPs (Sage 300, Spectrum, Viewpoint, etc.) have a vendor-compliance
table tracking which vendors have a current W-9 on file. In real life,
the physical/scanned W-9 PDFs accumulate in a shared folder for years
without that table being kept up to date. Catching up by manually
opening each PDF, copy/pasting the TIN, EIN, business name, and
address, then keying it into the ERP is painful and slow.

This tool automates the OCR + extraction and gives you a side-by-side
review UI so you confirm each one quickly, then exports a clean CSV
ready for a separate bulk-INSERT into your ERP.

The actual ERP write is intentionally **outside this tool** — keep
destructive database writes in a deliberate, reviewable SQL run that
you can roll back if needed.

## What it does

1. **Scans configured folders** for `.pdf` files (W-9s)
2. **OCRs each PDF:**
   - `pdfplumber` for PDFs that already have a text layer (fast)
   - Tesseract for fully-scanned image-only PDFs (slower, but works)
3. **Extracts the seven Form W-9 fields:** business name, DBA, TIN/SSN/EIN,
   federal tax classification, address, exemption codes, signature date
4. **Fuzzy-matches** the extracted business name to a vendor record in
   your ERP via ODBC (optional — runs in offline mode if no ODBC
   connection is configured)
5. **Side-by-side review UI:**
   - Left pane: the original PDF
   - Right pane: extracted fields + editable form
   - You confirm or correct each value, mark reviewed, advance
6. **Caches everything** in `cache/ocr_results.json` so re-runs and
   crashes don't lose work
7. **Exports CSV** for downstream bulk-INSERT into your ERP

## Prerequisites

| Item | Notes |
|---|---|
| Python 3.8+ | Tested on 3.11 and 3.14 |
| Tesseract OCR | Must be on `PATH` (or set `pytesseract.pytesseract.tesseract_cmd` in `app.py`). On Windows install via the [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki). On macOS: `brew install tesseract`. On Linux: distro package. |
| `pyodbc` ODBC driver (optional) | Only required for vendor matching. The app runs in offline mode without it. |
| Read access to your W-9 PDF folder | Configured in `settings.json` |
| Read access to your ERP's ODBC DSN (optional) | Configured in `settings.json` via a path to a JSON file containing the ODBC config |

## Setup

```powershell
git clone https://github.com/Function-Consulting/public-tools.git
cd public-tools\w9-catchup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then create the settings file:

```powershell
copy settings.example.json settings.json
notepad settings.json
```

Edit it to point at your W-9 folder(s) and (optionally) your ERP's ODBC
config file:

```json
{
  "scan_roots": [
    "C:\\path\\to\\your\\W-9s"
  ],
  "spectrum_config_path": "C:\\path\\to\\your\\erp-config.json"
}
```

`settings.json` is gitignored so your local paths don't leak into commits.

### ODBC config file format

The file referenced by `spectrum_config_path` must be a JSON file with
an `odbc` block:

```json
{
  "odbc": {
    "dsn": "Your DSN Name",
    "username": "...",
    "password": "..."
  }
}
```

The app reads this file at runtime and uses pyodbc to connect with
`DSN=...;UID=...;PWD=...`. **The password is read fresh each run; the
app does not cache or transmit it.**

If the file is unreachable or `pyodbc` isn't installed, the vendor-match
column is left blank. You can re-run **Incremental Scan** later (when on
the right network) to backfill matches.

### Vendor table schema expected by the matcher

The default matcher query in `app.py` looks for a vendor master table
named something like `VN_VENDOR_MASTER_MC` with columns:

- `Vendor_Code` (the unique vendor ID)
- `Vendor_Name`
- `Alpha_Sort` (used for the fuzzy match)
- `Status_Code` (filter to active vendors)
- `Company_Code` (multi-company filter)

If your ERP's vendor table is shaped differently, edit the
`match_vendor()` function in `app.py`.

## Running

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Open <http://127.0.0.1:5099/> in a browser.

You'll see an empty list on first run. Click **Run Initial Scan** to OCR
every PDF under the configured roots. Initial scan can take a while
(text-layer PDFs are fast; fully-scanned ones go through Tesseract and
are slower). Subsequent **Incremental Scan** only re-OCRs new or modified
files based on `mtime`.

## Review workflow

1. Filter the list (by year extracted from folder structure, reviewed
   status, vendor-match status)
2. Click a filename to open the side-by-side review page
3. Left pane is the original PDF (rendered via the browser's PDF viewer
   from the local file path)
4. Right pane shows OCR results and an editable form
5. Correct any field OCR got wrong. Confirm or replace the suggested
   vendor code.
6. **Save & Mark Reviewed** → stores edits, marks the row reviewed,
   auto-advances to the next entry
7. **Save (Unreviewed)** → stores edits but leaves the row pending for
   another pass
8. Keyboard shortcuts:
   - `←` / `p` → previous
   - `→` / `n` → next
   - `Ctrl+S` → save & advance

## Cache

OCR results land in `cache/ocr_results.json`. The cache is the source
of truth between runs — re-launching the app or rebooting the machine
doesn't lose work.

**Don't hand-edit the cache while the app is running.** The app writes
to it on every save.

The cache contains TIN/SSN/EIN data extracted from real W-9s. **It is
excluded from this repository via `.gitignore`** and should never be
committed.

## Export

Click **Export CSV** in the UI to produce a CSV of reviewed entries.
Pass `?all=1` in the URL to include unreviewed entries too.

The CSV columns are designed to feed a bulk-INSERT into a vendor-compliance
tracking table. Columns:

- `vendor_code` (matched ERP vendor)
- `business_name`, `dba`, `tin`, `tax_class`, `address`, `signed_date`
- `reviewed_at`, `reviewed_by`
- `source_pdf_path`

## External connections

| Connection | Required? | Purpose |
|---|---|---|
| Local file system (read) | Yes | Reading the W-9 PDFs in the configured roots |
| Local file system (write) | Yes | Writing `cache/ocr_results.json` |
| Tesseract OCR binary | Required for image-only PDFs | OCR fallback when no text layer exists |
| ERP database via ODBC | Optional | Fuzzy-matching extracted business names to vendor records |
| Network: 127.0.0.1:5099 | Yes | Local web UI (Flask development server) |
| Outbound internet | No | App makes no outbound HTTP calls |

## Files

```
w9-catchup/
  app.py                       Main Flask app (single file)
  requirements.txt
  README.md                    (this file)
  settings.example.json        Copy to settings.json and edit
  W9-Catchup.spec              PyInstaller spec for building a standalone .exe
  cache/                       Auto-created at runtime; gitignored
    ocr_results.json
  templates/
    index.html                 List view
    review.html                Side-by-side review
    settings.html              Config UI
```

## Building a standalone .exe (optional)

`W9-Catchup.spec` is a PyInstaller spec file for bundling the app into
a single executable so non-Python users can run it. Build with:

```powershell
.\.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller W9-Catchup.spec
```

Output lands in `dist/`. The bundled .exe still requires Tesseract to be
installed separately on the target machine.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "Tesseract not found" | Install Tesseract and put it on `PATH`, or set `pytesseract.pytesseract.tesseract_cmd` in `app.py` to the full path. |
| `pyodbc` not installed → vendor matches all blank | Either run in offline mode (matches will just be blank — OCR/review still work), or `pip install pyodbc` and ensure the ODBC driver for your ERP is installed. |
| All PDFs OCR to empty text | The PDFs are image-only AND Tesseract isn't actually being invoked. Verify with `pytesseract.get_tesseract_version()`. |
| App slow on first scan | Normal for large scanned PDFs. Tesseract OCR is the bottleneck. Initial scans of 700+ W-9s can take 30–60 minutes; incremental scans are fast. |
| Browser shows blank PDF in left pane | The PDF path in the review URL isn't accessible to your browser. Check that you're running the app on the machine that has the PDF folder mounted. |

## Scope notes

This tool is built for a **one-time historical backfill**. For ongoing
W-9-on-receipt processing as vendors are onboarded, integrate the OCR
and extraction logic directly into your AP intake workflow.

## License

[MIT](../LICENSE) — the source code in this folder is MIT-licensed.

Third-party dependencies (Flask, pdfplumber, pytesseract, pypdfium2,
pyodbc, Pillow) are all under permissive licenses (BSD-3-Clause, MIT,
Apache-2.0). See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) at
the repository root for the full list, copyright notices, and Apache-2.0
NOTICE preservation requirements.

Tesseract OCR is an external binary you install separately — that
install is governed by Tesseract's own Apache 2.0 license, not by this
repository.
