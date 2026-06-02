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

import pymupdf4llm


def extract_markdown(pdf_path: Path) -> str:
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
