# ocr_pdf.py -- part of the public-tools collection.
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
OCR a scanned PDF (or image) into a SEARCHABLE PDF.

Renders each page, runs Tesseract OCR, and overlays an invisible text
layer on top of the original page image. The output looks identical to the
scan but its text is now selectable -- so you can run it through
pdf_to_csv.py or pdf_to_markdown.py, which need a text layer. A plain-text
sidecar (<name>_ocr.txt) is written too.

Outputs (next to the source file):
    <name>_ocr.pdf   searchable PDF
    <name>_ocr.txt   extracted text

Requires the Tesseract OCR engine installed and findable -- on PATH, or via
the TESSERACT_CMD environment variable, or in the default install folder.
Windows installer: https://github.com/UB-Mannheim/tesseract/wiki

Usage: double-click, or  python ocr_pdf.py file.pdf [more.pdf ...]
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path


def _ensure(pip_name: str, import_name: str | None = None) -> None:
    """Import a dependency, pip-installing it on first run if missing."""
    mod = import_name or pip_name
    try:
        __import__(mod)
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", pip_name])
        __import__(mod)


for _pip, _mod in (("pymupdf", "pymupdf"), ("pytesseract", "pytesseract"), ("Pillow", "PIL")):
    _ensure(_pip, _mod)

import pymupdf          # noqa: E402  (after _ensure)
import pytesseract      # noqa: E402
from PIL import Image   # noqa: E402


RENDER_DPI = 300        # good accuracy/speed balance for OCR
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def _locate_tesseract() -> str | None:
    """Find tesseract.exe via TESSERACT_CMD, PATH, or the default install dir."""
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


def _pdf_has_text(doc) -> bool:
    """True if the PDF already carries a real text layer (OCR redundant)."""
    chars = 0
    for page in doc:
        chars += len(page.get_text("text").strip())
        if chars > 100:
            return True
    return False


def ocr_file(src: Path) -> tuple[Path, Path, bool]:
    """OCR one PDF or image into a searchable PDF + a .txt sidecar.

    Returns (pdf_out, txt_out, already_had_text).
    """
    src = Path(src)
    out_pdf = src.with_name(f"{src.stem}_ocr.pdf")
    out_txt = src.with_name(f"{src.stem}_ocr.txt")

    page_pngs: list[bytes] = []
    already_had_text = False

    suffix = src.suffix.lower()
    if suffix == ".pdf":
        doc = pymupdf.open(src)
        try:
            already_had_text = _pdf_has_text(doc)
            for page in doc:
                pix = page.get_pixmap(dpi=RENDER_DPI)
                page_pngs.append(pix.tobytes("png"))
        finally:
            doc.close()
    elif suffix in _IMAGE_EXTS:
        page_pngs.append(src.read_bytes())
    else:
        raise ValueError(
            f"Unsupported file type '{src.suffix}'. Use a PDF or one of: "
            f"{', '.join(sorted(_IMAGE_EXTS))}"
        )

    if not page_pngs:
        raise ValueError("No pages found in the file.")

    writer = pymupdf.open()
    text_parts: list[str] = []
    try:
        for png in page_pngs:
            img = Image.open(io.BytesIO(png))
            # Tesseract emits a single-page searchable PDF (image + hidden text).
            page_pdf = pytesseract.image_to_pdf_or_hocr(img, extension="pdf")
            text_parts.append(pytesseract.image_to_string(img))
            page_doc = pymupdf.open(stream=page_pdf, filetype="pdf")
            try:
                writer.insert_pdf(page_doc)
            finally:
                page_doc.close()
        writer.save(out_pdf)
    finally:
        writer.close()

    out_txt.write_text("\n\n".join(text_parts).strip() + "\n", encoding="utf-8")
    return out_pdf, out_txt, already_had_text


def _run_cli(args: list[str]) -> int:
    tcmd = _locate_tesseract()
    if not tcmd:
        print("ERROR: Tesseract OCR not found. Install it and put tesseract.exe "
              "on PATH, or set TESSERACT_CMD. https://github.com/UB-Mannheim/"
              "tesseract/wiki", file=sys.stderr)
        return 2
    pytesseract.pytesseract.tesseract_cmd = tcmd
    rc = 0
    for arg in args:
        try:
            out_pdf, out_txt, had_text = ocr_file(Path(arg))
            note = "  (note: this PDF already had a text layer)" if had_text else ""
            print(f"OK  {Path(arg).name} -> {out_pdf.name} (+ {out_txt.name}){note}")
        except Exception as exc:
            print(f"ERR {Path(arg).name}: {exc}", file=sys.stderr)
            rc = 1
    return rc


def _run_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()

    tcmd = _locate_tesseract()
    if not tcmd:
        messagebox.showerror(
            "OCR PDF",
            "Tesseract OCR was not found.\n\n"
            "Install it from\n"
            "https://github.com/UB-Mannheim/tesseract/wiki\n\n"
            "then make sure tesseract.exe is on your PATH, or set the "
            "TESSERACT_CMD environment variable to its full path.",
        )
        return
    pytesseract.pytesseract.tesseract_cmd = tcmd

    paths = filedialog.askopenfilenames(
        title="Pick scanned PDF(s) or image(s) to OCR",
        filetypes=[
            ("PDF / images", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
            ("All files", "*.*"),
        ],
    )
    if not paths:
        return

    done, already, errors = [], [], []
    for p in paths:
        try:
            out_pdf, _txt, had_text = ocr_file(Path(p))
            done.append(out_pdf.name)
            if had_text:
                already.append(Path(p).name)
        except Exception as exc:
            errors.append(f"{Path(p).name}: {exc}")

    lines = []
    if done:
        lines.append("Created searchable PDF(s) (a .txt was written too):")
        lines += [f"    {n}" for n in done]
        lines.append("\nYou can now run pdf_to_csv.py or pdf_to_markdown.py on these.")
    if already:
        lines.append("\nThese already had a text layer (OCR may be redundant):")
        lines += [f"    {n}" for n in already]
    if errors:
        lines.append("\nErrors:")
        lines += [f"    {e}" for e in errors]

    text = "\n".join(lines) or "Nothing was processed."
    (messagebox.showerror if errors else messagebox.showinfo)("OCR PDF", text)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(_run_cli(sys.argv[1:]))
    try:
        _run_gui()
    except Exception:
        traceback.print_exc()
        input("\nPress Enter to close...")
