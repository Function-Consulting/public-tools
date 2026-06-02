# Extract / Convert / Combine to PDF

A single-file Python utility that packages a folder of mixed receipt
formats — Outlook `.msg` emails, iPhone `.heic` photos, scanned PDFs,
and any other images — into one tidy PDF, in one click.

## What problem it solves

Monthly expense receipts arrive from multiple sources:

- Forwarded emails (`.msg` files) with the actual receipt as a PDF attachment
  buried under a dozen signature-image logos
- Phone photos in Apple's `.heic` format that most tools can't open
- Scanned hard-copy PDFs from a multifunction printer
- Loose JPGs or PNGs

Manually opening each email, downloading the attachment, separating real
attachments from logo clutter, converting HEIC to something universal, and
then merging everything into a single PDF for upload is tedious. This
script does all of it in one run.

## What it does, step by step

When you run `python "Extract_Convert_Combine to PDF.py"` from inside a
folder, the script:

### Step 1 — Extract real attachments from `.msg` emails

For every `.msg` file in the folder:

1. Opens the email with `extract-msg`
2. Iterates each attachment and decides "real document" vs "signature/inline":
   - **Drop** if it has a `contentId` (HTML-inline image — almost always a signature element)
   - **Drop** if filename matches signature patterns: `image001..010`,
     `Outlook-*`, `ATT0000*`, `emailsignature*`, `linkedinlogo*`,
     `logo_*`, `PastedGraphic*`, `Thumbs.db`
   - **Drop** any file with no file extension (catches the AI-generated
     alt-text-as-filename junk some Outlook clients produce)
   - **Drop** any image smaller than 30 KB (real receipt scans are reliably larger)
   - **Keep** PDFs unconditionally
   - **Keep** images ≥ 30 KB with non-signature filenames
   - **Keep** any other file type (`.docx`, `.xlsx`, etc.)
3. Saves the kept attachments to the same folder (renaming with `_2`, `_3`
   on collision)
4. Moves the processed `.msg` to a `_processed_msgs/` subfolder — it's
   preserved (so you can verify manually if the filter missed something)
   but won't be re-processed on subsequent runs

### Step 2 — Convert HEIC → JPG

For every `.heic` / `.heif` file:

1. Loads with `pillow-heif` + Pillow
2. Saves as JPEG (quality 92, optimized) with the same base name
3. Preserves the original file's modification timestamp (so date-sorted
   receipts stay in order)
4. Deletes the HEIC source **only after** the JPG is verified on disk

### Step 3 — Combine into a single PDF

1. Scans the folder for every `.jpg`, `.jpeg`, `.png`, and `.pdf`
2. Sorts alphabetically — most monthly receipt folders use date-prefixed
   filenames, so this gives chronological order automatically
3. Walks the list: images convert to a single page each (RGB-converted
   if needed); existing PDFs have their pages merged in directly
4. Writes the output PDF, named per the convention below
5. **Excludes the output file itself from the scan** so re-runs cleanly
   overwrite without recursion

## Output filename convention

For folders named `Lastname, Firstname_MM-YYYY`, the output PDF is named
`Firstname Lastname Receipts MMYYYY.pdf`:

| Folder name | Output PDF |
|---|---|
| `Callsen, Dave_04-2026` | `Dave Callsen Receipts 042026.pdf` |
| `Smith, Jane_12-2025` | `Jane Smith Receipts 122025.pdf` |

Folders that don't match this pattern fall back to `<foldername>_combined.pdf`.

To use a different naming convention, edit `output_pdf_name()` in the script.

## Prerequisites

- **Python 3.8+** on Windows, macOS, or Linux
- That's it. The script auto-installs its dependencies on first run.

## Dependencies (auto-installed)

| Package | Used for |
|---|---|
| `pillow-heif` | Reading `.heic` / `.heif` files |
| `pypdf` | Merging existing PDFs and writing the combined output |
| `extract-msg` | Parsing Outlook `.msg` files |
| `Pillow` | Image conversion (auto-installed as a dependency of pillow-heif) |

First run on a new machine prints `First-time setup: installing ...` and
runs `pip install` for whatever's missing. Subsequent runs are immediate.

## External connections

**None.** The script is fully local. It does not call any APIs, network
services, or cloud storage. Everything it does happens on files in the
current folder.

## Usage

### Option A — Drop & double-click

1. Copy `Extract_Convert_Combine to PDF.py` into the folder you want to package
2. Double-click it (requires `.py` to be associated with `python.exe` on Windows)
3. The script prints progress to a console window and pauses on
   "Press Enter to close" so you can review the output

### Option B — Terminal

```powershell
cd "C:\path\to\receipt\folder"
python "Extract_Convert_Combine to PDF.py"
```

### Option C — Reuse one copy via command line

Keep one master copy somewhere on `PATH` and invoke it against any folder:

```powershell
python "C:\Tools\Extract_Convert_Combine to PDF.py"
```

Note: the script uses `Path(__file__).resolve().parent` to determine the
working folder, so it always operates on the folder **the script lives
in**, not the current directory. If you want command-line-target-folder
behavior, modify the `folder = ...` line in `main()`.

## What it does *not* do

- **Does not recurse into subfolders.** Only the folder the script is in.
- **Does not delete `.msg` files** — they move to `_processed_msgs/`.
- **Does not delete combined JPG/PNG/PDF source files** — only HEICs (after
  successful conversion). Clean up the rest manually once you've verified
  the combined PDF.
- **Does not OCR or rotate images.** Receipts are bundled as-is.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `LOCKED (open in Outlook?)` on a `.msg` | The `.msg` is currently open in Outlook. Close it and re-run. |
| Some real attachments are being skipped as signatures | Adjust the heuristics in `is_real_attachment()` and `JUNK_NAME_PATTERNS` near the top of the script. |
| Signature images are being kept | Same: tighten the patterns or lower `MIN_IMAGE_SIZE_BYTES`. |
| `First-time setup` install fails | Run `python -m pip install pillow-heif pypdf extract-msg` manually with admin rights or in a virtual environment. |
| Output PDF won't open in Adobe | Should be very rare; pypdf produces standard PDF 1.7. Try opening in Chrome or Preview to confirm; if those work, your Adobe install may be stale. |

## License

[MIT](../LICENSE) — the source code in this folder is MIT-licensed.

**Third-party dependencies have their own licenses, including one GPL-3.0
dependency (`extract-msg`).** See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
at the repository root for the full list. In particular, if you bundle and
redistribute this script (e.g., as a PyInstaller binary) you must comply
with the upstream licenses, including GPL-3.0's source-offer requirement.
Simply running the script locally after `pip install`ing the dependencies
is unrestricted.
