# PDF to Markdown

A double-click desktop utility that converts a PDF into clean, LLM-ready
Markdown. Designed for cases where you want to paste a PDF's contents
into ChatGPT, Claude, a vector DB, or similar — and you want the output
to actually be readable, not a wall of broken text.

## What it does

1. **Open a PDF** via a file-picker dialog (or pass the path on the command line)
2. **Convert to Markdown** using `pymupdf4llm`, which handles:
   - Reading order across multi-column pages (so a 2-column research paper
     reads left-column-then-right-column, not interleaved)
   - Font-metric-based heading detection (big bold text becomes `#`/`##`,
     not a random paragraph)
   - Tables rendered as GitHub-flavored Markdown tables
   - Image/chart suppression (kept out of the output to avoid noise)
3. **Post-process** to clean up common artifacts:
   - Strip leftover `![](...)` image placeholders
   - Fix hyphenated line-wraps (`exam-\nple` → `example`)
   - Collapse 3+ blank lines to 2
   - Drop standalone page-number lines (header/footer noise)
   - Trim trailing whitespace
4. **Save** as a `.md` file in the same folder as the source PDF

## Why this vs. just selecting/copying text from a PDF

Block-by-block text extraction (the default in most tools, including
Acrobat's "Save As Text") produces output that:

- Interleaves text from multi-column pages randomly
- Loses heading structure entirely
- Mangles tables into space-separated mush
- Includes every header/footer page-number artifact

`pymupdf4llm` is substantially smarter — it uses the actual PDF font
metrics and layout positions to reconstruct logical reading order and
document structure. For feeding PDFs to LLMs, it's the difference between
"the LLM can actually answer questions about this" and "the LLM
hallucinates because the input is garbage."

## Best for

- Research papers (multi-column academic PDFs)
- Reports with proper heading hierarchy and tables
- Anything you'd want an LLM to summarize, extract from, or analyze
- Documentation conversion (PDF → Markdown for a wiki or knowledge base)

## Not great for

- Image-only / scanned PDFs (this tool does no OCR — see `w9-catchup` if you need OCR)
- Forms with lots of checkboxes and field markings (those become weird symbols)
- Heavily-designed marketing PDFs where the "structure" is visual, not semantic

## Prerequisites

- **Python 3.8+**
- The dependency in `requirements.txt` (just `pymupdf4llm`, which pulls in `pymupdf`)

## Setup

```powershell
cd pdf-to-markdown
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Usage

### Double-click (Windows)

The included `PDF to Markdown.bat` launcher just runs the script from its
own folder. Double-click the .bat (or, if your `.py` extension is
associated with `python.exe`, the script itself). A file-picker opens,
you pick a PDF, the `.md` is written next to it.

### Command line

```powershell
python pdf_to_markdown.py path\to\file.pdf
```

### Drag and drop (Windows)

Drag a PDF onto the script or the .bat file in Explorer — Windows passes
the PDF path as `sys.argv[1]`.

## External connections

**None.** Fully local. No network calls, no LLM API usage. The "LLM-ready"
in the description means the output format suits LLM input; the tool
itself talks to no AI service.

## Output

For a PDF named `whitepaper.pdf`, you get `whitepaper.md` in the same folder.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Output is mostly blank | The PDF is image-only (scanned). This tool doesn't OCR. Either OCR first with a separate tool, or extract using `w9-catchup`'s extractor as a reference. |
| Tables look mangled | pymupdf4llm couldn't detect cell boundaries. The `table_strategy="lines_strict"` setting trades recall for precision; if you want fewer false-negative tables, edit the call in `pdf_to_markdown.py` to use `"lines"` instead. |
| Reading order wrong on a multi-column PDF | Rare with pymupdf4llm, but possible on unusual layouts. No easy workaround beyond manual fixup. |
| Headings missing (everything is plain text) | The source PDF probably uses uniform font size with no visual hierarchy (common in poorly-designed reports). pymupdf4llm can't infer heading structure from a flat font. |

## License

This tool is licensed under [AGPL-3.0](../LICENSE).

It depends on `pymupdf4llm` and `pymupdf`, both dual-licensed AGPL-3.0 OR
Artifex commercial. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
at the repository root for the full dependency license list.
