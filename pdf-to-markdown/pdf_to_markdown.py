# pdf_to_markdown.py -- part of the public-tools collection.
# Copyright (C) 2026 Chad Aaland.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.  It is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero
# General Public License at <https://www.gnu.org/licenses/> for details.
#
# Third-party components and their licenses: see THIRD_PARTY_NOTICES.md.
"""
PDF -> clean Markdown for LLM consumption.

Uses pymupdf4llm, which handles: reading order across multi-column pages,
font-metric heading detection, tables rendered as GitHub-flavored markdown,
and image/chart suppression. This is substantially more accurate than
block-by-block text extraction.

Usage: double-click, or `python pdf_to_markdown.py file.pdf`.
"""
from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path
from tkinter import Tk, filedialog, messagebox

import pymupdf
import pymupdf4llm


def extract_markdown(pdf_path: Path) -> str:
    """Convert a PDF to clean Markdown.

    A scanned PDF (no text layer) is OCR'd page-by-page with Tesseract and the
    recognized text is returned directly, because pymupdf4llm cannot read the
    invisible text layer of an OCR'd image.  OCR needs the Tesseract engine
    installed; without it a scan converts to near-empty Markdown.
    """
    pdf_path = Path(pdf_path)
    if pdf_path.suffix.lower() == ".pdf" and not _has_text_layer(pdf_path):
        ocr_text = _ocr_pages_to_text(pdf_path)
        if ocr_text.strip():
            return _tidy(ocr_text)
    md = pymupdf4llm.to_markdown(
        str(pdf_path),
        write_images=False,
        embed_images=False,
        ignore_images=True,
        ignore_graphics=True,
        table_strategy="lines_strict",  # stricter = fewer false-positive tables
        show_progress=False,
    )
    return _tidy(md)


# ---------- OCR fallback for scanned / image-only PDFs ----------
# pymupdf4llm reads nothing from a scan, and even a Tesseract "searchable PDF"
# overlay is invisible to it.  So we render each page, run Tesseract directly,
# and return the recognized text.  Tesseract is the external OCR engine
# (https://github.com/UB-Mannheim/tesseract/wiki); without it this fallback is
# skipped and a scan converts to near-empty Markdown.

def _locate_tesseract() -> str | None:
    """Find tesseract.exe via TESSERACT_CMD, PATH, or the default install dir."""
    import os
    import shutil
    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).is_file():
        return env
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _has_text_layer(pdf_path: Path) -> bool:
    """True if the PDF already carries a real text layer (OCR not needed).

    A born-digital PDF has hundreds of characters; a scan has ~none, so a low
    threshold cleanly separates the two.
    """
    doc = pymupdf.open(pdf_path)
    try:
        chars = 0
        for page in doc:
            chars += len(page.get_text("text").strip())
            if chars > 16:
                return True
    finally:
        doc.close()
    return False


def _ocr_pages_to_text(pdf_path: Path) -> str:
    """OCR each page with Tesseract and return the recognized text, or '' if
    the Tesseract engine isn't installed."""
    tcmd = _locate_tesseract()
    if not tcmd:
        return ""
    import io
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "pytesseract", "Pillow"])
        import pytesseract
        from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = tcmd
    parts: list[str] = []
    doc = pymupdf.open(pdf_path)
    try:
        for page in doc:
            png = page.get_pixmap(dpi=300).tobytes("png")
            parts.append(pytesseract.image_to_string(Image.open(io.BytesIO(png))))
    finally:
        doc.close()
    return "\n\n".join(parts)


def _tidy(text: str) -> str:
    # Drop image/figure placeholders pymupdf4llm may leave behind
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # Page-break markers -> blank line
    text = text.replace("\f", "\n\n")
    # Repair hyphenated line-wraps: "exam-\nple" -> "example"
    text = re.sub(r"(\w)[-\u00ad]\n(\w)", r"\1\2", text)
    # Trim trailing whitespace on every line
    text = re.sub(r"[ \t]+\n", "\n", text)
    # Collapse 3+ blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Drop lines that are just a page number (common header/footer artifact)
    text = re.sub(r"\n\s*\d{1,4}\s*\n", "\n", text)
    return text.strip() + "\n"


def run_gui() -> None:
    root = Tk()
    root.withdraw()
    try:
        pdf_path_str = filedialog.askopenfilename(
            title="Select a PDF to convert",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not pdf_path_str:
            return
        pdf_path = Path(pdf_path_str)

        out_str = filedialog.asksaveasfilename(
            title="Save markdown as...",
            defaultextension=".md",
            initialdir=str(pdf_path.parent),
            initialfile=pdf_path.with_suffix(".md").name,
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")],
        )
        if not out_str:
            return
        out_path = Path(out_str)

        markdown = extract_markdown(pdf_path)
        out_path.write_text(markdown, encoding="utf-8")

        size_kb = out_path.stat().st_size / 1024
        messagebox.showinfo(
            "Done",
            f"Saved {out_path.name}\n{size_kb:.1f} KB  \u00b7  {len(markdown):,} chars",
        )
    except Exception:
        messagebox.showerror("Error", traceback.format_exc())
    finally:
        root.destroy()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        dst = src.with_suffix(".md")
        dst.write_text(extract_markdown(src), encoding="utf-8")
        print(f"Wrote {dst}")
    else:
        run_gui()
