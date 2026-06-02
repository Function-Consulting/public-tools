"""
PDF -> CSV table extractor.

Uses pymupdf's vector-aware table finder (accurate for ruled/financial
tables), with pdfplumber text-clustering as a fallback for unruled tables.
Consecutive pages with an identical header row are stitched into one table.

A preview dialog shows every detected table before saving so
misreads can be caught.

Usage: double-click, or `python pdf_to_csv.py file.pdf`.
"""
from __future__ import annotations

import csv
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pdfplumber
import pymupdf


Table = list[list[str]]


def extract_tables(pdf_path: Path) -> list[Table]:
    """Detect tables page-by-page, then stitch continuations."""
    per_page = _extract_per_page(pdf_path)
    return _stitch_continuations(per_page)


def _extract_per_page(pdf_path: Path) -> list[Table]:
    tables: list[Table] = []
    # Primary: pymupdf vector-aware detection
    doc = pymupdf.open(pdf_path)
    try:
        for page in doc:
            found = page.find_tables(strategy="lines_strict")
            page_tables = [t.extract() for t in found.tables] if found.tables else []
            # Fallback: pdfplumber text clustering when nothing vector-detectable
            if not page_tables:
                page_tables = _pdfplumber_page(pdf_path, page.number)
            for rows in page_tables:
                cleaned = _clean_table(rows)
                if _looks_like_table(cleaned):
                    tables.append(cleaned)
    finally:
        doc.close()
    return tables


def _pdfplumber_page(pdf_path: Path, page_index: int) -> list[list[list[str | None]]]:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        found = page.find_tables(
            table_settings={
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "snap_tolerance": 4,
                "text_tolerance": 2,
            }
        )
        return [t.extract() for t in found] if found else []


def _clean_table(rows: list[list[str | None]] | None) -> Table:
    if not rows:
        return []
    out: Table = []
    for row in rows:
        # Preserve newlines inside cells as spaces (multi-line cells are common
        # in financial tables and must not be split across rows).
        norm = [
            " ".join(((c or "").replace("\n", " ")).split()) for c in row
        ]
        if any(cell for cell in norm):
            out.append(norm)
    if not out:
        return out
    width = max(len(r) for r in out)
    for r in out:
        while len(r) < width:
            r.append("")
    keep = [i for i in range(width) if any(r[i] for r in out)]
    return [[r[i] for i in keep] for r in out]


def _looks_like_table(rows: Table) -> bool:
    """Guard against stray 1-col or 1-row 'tables' that are really paragraphs."""
    if len(rows) < 2:
        return False
    if max(len(r) for r in rows) < 2:
        return False
    return True


def _stitch_continuations(tables: list[Table]) -> list[Table]:
    """Merge tables on consecutive pages that share the same header row."""
    if not tables:
        return tables
    merged: list[Table] = [tables[0]]
    for tbl in tables[1:]:
        prev = merged[-1]
        if tbl and prev and tbl[0] == prev[0] and len(tbl[0]) == len(prev[0]):
            merged[-1] = prev + tbl[1:]  # drop duplicated header
        elif tbl and prev and len(tbl[0]) == len(prev[0]) and _is_numeric_row(tbl[0]):
            # Same column count, first row is data (no header repeated) -> append
            merged[-1] = prev + tbl
        else:
            merged.append(tbl)
    return merged


def _is_numeric_row(row: list[str]) -> bool:
    numericish = sum(1 for c in row if any(ch.isdigit() for ch in c))
    return numericish >= max(1, len(row) // 2)


def write_csv(rows: Table, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)


# ---------- Preview UI ----------

def preview_and_save(tables: list[Table], default_out: Path) -> list[Path]:
    """Show tables in a tabbed preview; user confirms per table or cancels."""
    result: dict = {"written": [], "cancelled": False}
    win = tk.Tk()
    win.title(f"Preview: {len(tables)} table(s) detected")
    win.geometry("1000x600")

    nb = ttk.Notebook(win)
    nb.pack(fill="both", expand=True, padx=6, pady=6)

    keep_vars: list[tk.BooleanVar] = []
    for i, tbl in enumerate(tables, start=1):
        frame = ttk.Frame(nb)
        nb.add(frame, text=f"Table {i} ({len(tbl)}x{len(tbl[0]) if tbl else 0})")

        var = tk.BooleanVar(value=True)
        keep_vars.append(var)
        ttk.Checkbutton(frame, text="Save this table", variable=var).pack(anchor="w", padx=4, pady=2)

        cols = [f"c{j}" for j in range(len(tbl[0]))] if tbl else ["c0"]
        tv = ttk.Treeview(frame, columns=cols, show="headings", height=20)
        for j, name in enumerate(tbl[0] if tbl else []):
            tv.heading(cols[j], text=name or f"col{j+1}")
            tv.column(cols[j], width=120, anchor="w")
        for row in tbl[1:]:
            tv.insert("", "end", values=row)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")

    def on_save() -> None:
        keep = [tables[i] for i, v in enumerate(keep_vars) if v.get()]
        if not keep:
            messagebox.showwarning("Nothing selected", "No tables selected to save.")
            return
        if len(keep) == 1:
            write_csv(keep[0], default_out)
            result["written"] = [default_out]
        else:
            stem = default_out.with_suffix("")
            for i, tbl in enumerate(keep, start=1):
                p = stem.parent / f"{stem.name}_table{i:02d}.csv"
                write_csv(tbl, p)
                result["written"].append(p)
        win.destroy()

    def on_cancel() -> None:
        result["cancelled"] = True
        win.destroy()

    btns = ttk.Frame(win)
    btns.pack(fill="x", pady=4)
    ttk.Button(btns, text="Save selected", command=on_save).pack(side="right", padx=6)
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right")

    win.mainloop()
    return result["written"]


def run_gui() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        pdf_path_str = filedialog.askopenfilename(
            title="Select a PDF with tables",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not pdf_path_str:
            return
        pdf_path = Path(pdf_path_str)

        out_str = filedialog.asksaveasfilename(
            title="Save CSV as... (suffix added per table if multiple)",
            defaultextension=".csv",
            initialdir=str(pdf_path.parent),
            initialfile=pdf_path.with_suffix(".csv").name,
            filetypes=[("CSV", "*.csv")],
        )
        if not out_str:
            return
        out_path = Path(out_str)

        root.destroy()  # close hidden root before opening preview

        tables = extract_tables(pdf_path)
        if not tables:
            messagebox.showwarning(
                "No tables found",
                "No tables detected. If the PDF is scanned, it needs OCR first.",
            )
            return

        written = preview_and_save(tables, out_path)
        if written:
            summary = "\n".join(f"- {p.name}" for p in written)
            messagebox.showinfo("Done", f"Saved {len(written)} file(s):\n\n{summary}")
    except Exception:
        messagebox.showerror("Error", traceback.format_exc())


if __name__ == "__main__":
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        tables = extract_tables(src)
        if not tables:
            print("No tables found.")
            sys.exit(1)
        if len(tables) == 1:
            dst = src.with_suffix(".csv")
            write_csv(tables[0], dst)
            print(f"Wrote {dst}")
        else:
            stem = src.with_suffix("")
            for i, tbl in enumerate(tables, start=1):
                p = stem.parent / f"{stem.name}_table{i:02d}.csv"
                write_csv(tbl, p)
                print(f"Wrote {p}")
    else:
        run_gui()
