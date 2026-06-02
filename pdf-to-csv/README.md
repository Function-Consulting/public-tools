# PDF to CSV

A double-click desktop utility that extracts every table from a PDF and
saves it as a CSV file, with a visual preview step so you can confirm
each detected table before writing.

## What it does

1. **Open a PDF** via a file-picker dialog (or pass the path on the command line)
2. **Detect tables** on each page:
   - Primary: `pymupdf`'s vector-aware table finder (accurate for ruled
     and financial tables with explicit grid lines)
   - Fallback: `pdfplumber`'s text-clustering detector (handles unruled
     tables where rows/cols are inferred from text positioning)
3. **Stitch continuations:** consecutive pages with an identical header
   row are merged into a single CSV (handles multi-page tables)
4. **Show a preview dialog** with every detected table — scroll through,
   confirm the detection looks right, then save
5. **Save** as one CSV per table (or a single CSV if only one was detected)
   in the same folder as the source PDF

## Best for

- Financial statements, bank statements, brokerage reports
- Anything with explicit ruled grid lines (where pymupdf's vector detector excels)
- Multi-page tables with repeating headers
- Quick one-off conversions when you'd otherwise be copy/pasting cells

## Not great for

- Complex nested or merged-cell layouts
- Tables with no grid lines AND no consistent text alignment
- Image-only / scanned PDFs (this tool does no OCR — see `w9-catchup` if you need OCR)

## Prerequisites

- **Python 3.8+**
- The dependencies in `requirements.txt`

## Setup

```powershell
cd pdf-to-csv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

### Double-click (Windows)

The included `PDF to CSV.bat` launcher just runs the script from its own
folder. Double-click the .bat (or, if your `.py` extension is associated
with `python.exe`, the script itself). A file-picker opens, you pick a
PDF, you get the preview dialog, click Save.

### Command line

```powershell
python pdf_to_csv.py path\to\file.pdf
```

The preview dialog still appears. Cancel out of it to abort without writing.

### Drag and drop (Windows)

If you drag a PDF onto the script or the .bat file in Explorer, Windows
passes the PDF path as `sys.argv[1]` — same as the command-line form.

## External connections

**None.** Fully local. No network calls, no cloud services.

## Output

For a PDF named `report.pdf` containing 3 detected tables, you get:

- `report - Table 1.csv`
- `report - Table 2.csv`
- `report - Table 3.csv`

(Or just `report.csv` if only one table was detected.)

Files are written to the same folder as the source PDF.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "No tables detected" on a PDF that obviously has tables | The tables are probably image-based (a scanned PDF). This tool doesn't OCR. Either OCR first with a separate tool, or use `w9-catchup`'s extractor as a reference for adding OCR support. |
| Detected table is split awkwardly across rows | pymupdf's grid detector misread the cell boundaries. Edit the resulting CSV manually, or try opening the PDF in a tool like Tabula for a different detection algorithm. |
| Multi-page table not stitched | The header row text isn't identical across pages (Page 1 says "Vendor Name", Page 2 says "Vendor name"). Adjust the header in the source PDF if possible, or merge CSVs manually post-export. |
| Preview dialog cut off / unreadable | Resize the window. The dialog uses tkinter's default sizing which can be cramped on small displays. |
| Crash with `ModuleNotFoundError` | `pip install -r requirements.txt` wasn't run, or you're in the wrong virtualenv. |

## License

This tool is licensed under [AGPL-3.0](../LICENSE).

It depends on `pymupdf` (dual-licensed AGPL-3.0 OR Artifex commercial) and
`pdfplumber` (MIT). See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
at the repository root for the full dependency license list.
