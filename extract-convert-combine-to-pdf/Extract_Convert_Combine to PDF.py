# Extract_Convert_Combine to PDF.py -- part of the public-tools collection.
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
"""Extract_Convert_Combine to PDF.

One-click workflow for a folder of receipts:
  1. Extract real attachments (PDFs, larger images) from any .msg email files,
     filtering out signature logos / inline images. Move processed .msg files
     into a _processed_msgs/ subfolder so nothing is lost.
  2. Convert every .heic / .heif file in this folder to .jpg. Delete the HEIC
     only after the JPG is verified.
  3. Combine every image (JPG/JPEG/PNG) and every PDF in the folder
     into a single output PDF.

Naming convention for the combined PDF:
  Folder named  'Lastname, Firstname_MM-YYYY'  ->  'Firstname Lastname Receipts MMYYYY.pdf'
    e.g. 'Callsen, Dave_04-2026'  ->  'Dave Callsen Receipts 042026.pdf'
  Folders that don't match the pattern fall back to '<foldername>_combined.pdf'.

Works whether or not any HEIC or MSG files are present.
The combined PDF excludes itself from the scan so re-runs cleanly overwrite.
Original JPGs/PNGs/PDFs are kept in place; delete them manually once you've
verified the combined PDF looks right.
"""

import os
import sys
import subprocess
import io
from pathlib import Path


# ---------------- Dependency bootstrap ----------------

def ensure_dependencies():
    """Install missing libraries on first run."""
    needed = []
    try: import pillow_heif  # noqa: F401
    except ImportError: needed.append('pillow-heif')
    try: import pypdf  # noqa: F401
    except ImportError: needed.append('pypdf')
    try: import extract_msg  # noqa: F401
    except ImportError: needed.append('extract-msg')

    if needed:
        print(f"First-time setup: installing {', '.join(needed)} (one-time)...")
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--quiet'] + needed,
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("ERROR: pip install failed.")
            print(result.stderr)
            sys.exit(1)
        print(f"Installed: {', '.join(needed)}. Continuing...\n")


def safe_filename(folder: Path, filename: str) -> str:
    """Append _2, _3 to avoid overwriting an existing file."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 2
    while (folder / candidate).exists():
        candidate = f"{base}_{n}{ext}"
        n += 1
    return candidate


def output_pdf_name(folder_name: str) -> str:
    """Build the combined-PDF filename from the folder name.

    Expected pattern:  'Lastname, Firstname_MM-YYYY'
      e.g. 'Callsen, Dave_04-2026'  ->  'Dave Callsen Receipts 042026.pdf'

    Falls back to '<foldername>_combined.pdf' if the folder name
    doesn't match the expected pattern.
    """
    # Need an underscore separating name from date
    if '_' in folder_name:
        name_part, date_part = folder_name.rsplit('_', 1)
        # Need 'Last, First' on the left side
        if ', ' in name_part:
            last, first = name_part.split(', ', 1)
            full_name = f"{first.strip()} {last.strip()}"
            date_clean = date_part.replace('-', '').strip()
            return f"{full_name} Receipts {date_clean}.pdf"
    # Fallback
    return f"{folder_name}_combined.pdf"


# ---------------- Step 0: .msg attachment extraction ----------------

# Filename substrings that almost always mean "signature / inline image, not a real attachment"
JUNK_NAME_PATTERNS = (
    'image001', 'image002', 'image003', 'image004', 'image005',
    'image006', 'image007', 'image008', 'image009', 'image010',
    'outlook-image', 'outlook-', 'att0000',
    'emailsignature', 'linkedinlogo', 'logo_',
    'pastedgraphic', 'thumbs.db',
)

# Minimum size for an image attachment to be considered "real" (not a signature)
MIN_IMAGE_SIZE_BYTES = 30 * 1024  # 30 KB


def is_real_attachment(att, raw_name: str) -> tuple[bool, str]:
    """Return (is_real, reason)."""
    name_lower = raw_name.lower()
    ext = os.path.splitext(name_lower)[1]

    # Files with no extension: probably the weird AI-described image names; skip
    if not ext:
        return False, "no file extension"

    # PDFs: always real (receipts are almost always PDFs)
    if ext == '.pdf':
        return True, "PDF (always included)"

    # Inline attachments (have a contentId) are signature/embedded images
    cid = getattr(att, 'cid', None) or getattr(att, 'contentId', None)
    if cid:
        return False, f"inline image (contentId={cid!r})"

    # For images, apply junk-name + size filter
    if ext in ('.png', '.jpg', '.jpeg', '.gif', '.bmp'):
        if any(p in name_lower for p in JUNK_NAME_PATTERNS):
            return False, "matches signature filename pattern"
        try:
            size = len(att.data)
        except Exception:
            size = 0
        if size < MIN_IMAGE_SIZE_BYTES:
            return False, f"too small ({size} bytes < {MIN_IMAGE_SIZE_BYTES})"
        return True, f"image, {size:,} bytes"

    # Other (docx, xlsx, etc) — include
    return True, f"other file type ({ext})"


def extract_msg_attachments(folder: Path):
    """Process all .msg files: extract real attachments, delete .msg files.
    Returns (msg_processed, attachments_saved, errors_list)."""
    import extract_msg

    msg_files = sorted(folder.glob('*.msg'))
    if not msg_files:
        return 0, 0, []

    print(f"Found {len(msg_files)} .msg file(s) to process.")
    processed, saved_count, errors = 0, 0, []

    for msg_path in msg_files:
        try:
            msg = extract_msg.openMsg(str(msg_path))
            atts = list(msg.attachments)
            kept, dropped = [], []

            for att in atts:
                raw_name = (att.longFilename or att.shortFilename or '').strip()
                if not raw_name:
                    raw_name = 'attachment.bin'
                clean_name = os.path.basename(raw_name)
                is_real, reason = is_real_attachment(att, clean_name)
                if is_real:
                    final = safe_filename(folder, clean_name)
                    (folder / final).write_bytes(att.data)
                    kept.append((final, reason))
                    saved_count += 1
                else:
                    dropped.append((clean_name, reason))

            msg.close()
            processed += 1

            print(f"  {msg_path.name}:")
            for n, r in kept:
                print(f"    KEPT     {n}  ({r})")
            for n, r in dropped:
                print(f"    skipped  {n}  ({r})")

            # Move the .msg to a "_processed_msgs" subfolder so it's
            # preserved (in case extraction missed something) but won't
            # be re-processed on the next run.
            archive_dir = folder / '_processed_msgs'
            archive_dir.mkdir(exist_ok=True)
            archive_target = archive_dir / msg_path.name
            n = 2
            while archive_target.exists():
                archive_target = archive_dir / f"{msg_path.stem}_{n}{msg_path.suffix}"
                n += 1
            msg_path.rename(archive_target)
            print(f"    -> .msg moved to _processed_msgs/  (kept for review)")

        except PermissionError:
            print(f"  {msg_path.name}: LOCKED (open in Outlook?) — left in place")
            errors.append((msg_path.name, 'locked'))
        except Exception as e:
            print(f"  {msg_path.name}: ERROR {e}")
            errors.append((msg_path.name, str(e)))

    return processed, saved_count, errors


# ---------------- Step 1: HEIC -> JPG ----------------

def convert_heic_to_jpg(folder: Path):
    import pillow_heif
    from PIL import Image
    pillow_heif.register_heif_opener()

    heic_files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in ('.heic', '.heif')
    )
    if not heic_files:
        return 0, 0, []

    print(f"Found {len(heic_files)} HEIC/HEIF file(s) to convert.")
    converted, skipped, errors = 0, 0, []

    for src in heic_files:
        dst = src.with_suffix('.jpg')
        if dst.exists():
            print(f"  SKIP   {src.name}  (target {dst.name} already exists)")
            skipped += 1
            continue
        try:
            img = Image.open(src)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(dst, format='JPEG', quality=92, optimize=True)
            stat = src.stat()
            os.utime(dst, (stat.st_atime, stat.st_mtime))
            if dst.exists() and dst.stat().st_size > 0:
                src.unlink()
                print(f"  OK     {src.name}  ->  {dst.name}  (HEIC deleted)")
                converted += 1
            else:
                raise RuntimeError("JPG save appears to have failed")
        except Exception as e:
            print(f"  ERROR  {src.name}: {e}")
            errors.append((src.name, str(e)))
            if dst.exists():
                try: dst.unlink()
                except: pass

    return converted, skipped, errors


# ---------------- Step 2: combine into single PDF ----------------

def combine_folder_into_pdf(folder: Path, output_path: Path):
    from PIL import Image
    from pypdf import PdfWriter, PdfReader

    IMAGE_EXTS = {'.jpg', '.jpeg', '.png'}
    sources = sorted(
        f for f in folder.iterdir()
        if f.is_file()
        and f.resolve() != output_path.resolve()
        and (f.suffix.lower() in IMAGE_EXTS or f.suffix.lower() == '.pdf')
    )

    if not sources:
        print("  Nothing to combine (no JPG/PNG/PDF files in folder).")
        return 0

    print(f"Combining {len(sources)} file(s) into PDF (sorted by filename):")
    for f in sources:
        print(f"  - {f.name}")

    writer = PdfWriter()
    errors = []

    for f in sources:
        try:
            if f.suffix.lower() == '.pdf':
                reader = PdfReader(str(f))
                for page in reader.pages:
                    writer.add_page(page)
            else:
                img = Image.open(f)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='PDF')
                buf.seek(0)
                reader = PdfReader(buf)
                for page in reader.pages:
                    writer.add_page(page)
        except Exception as e:
            print(f"  ERROR processing {f.name}: {e}")
            errors.append((f.name, str(e)))

    if len(writer.pages) == 0:
        print("  No pages were successfully added; combined PDF NOT written.")
        return 0

    with open(output_path, 'wb') as out_f:
        writer.write(out_f)

    print(f"\n  Wrote: {output_path.name}  ({len(writer.pages)} pages)")
    if errors:
        print(f"  ({len(errors)} source file(s) had errors and were skipped)")
    return len(sources) - len(errors)


# ---------------- Main ----------------

def main():
    ensure_dependencies()
    folder = Path(__file__).resolve().parent
    print(f"Working folder:\n  {folder}\n")

    # Step 0: .msg attachment extraction
    print("--- Step 0: Extract attachments from .msg files ---")
    msg_processed, attachments_saved, msg_errors = extract_msg_attachments(folder)
    if msg_processed == 0 and not msg_errors:
        print("  (no .msg files to process)")
    print()

    # Step 1: HEIC -> JPG
    print("--- Step 1: Convert HEIC -> JPG ---")
    converted, heic_skipped, heic_errors = convert_heic_to_jpg(folder)
    if converted == 0 and heic_skipped == 0 and not heic_errors:
        print("  (no HEIC/HEIF files to convert)")
    print()

    # Step 2: combine into single PDF
    print("--- Step 2: Combine into single PDF ---")
    output_pdf = folder / output_pdf_name(folder.name)
    if output_pdf.exists():
        print(f"  Overwriting existing: {output_pdf.name}")
    else:
        print(f"  Output: {output_pdf.name}")
    combined_count = combine_folder_into_pdf(folder, output_pdf)

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  .msg processed:     {msg_processed}")
    print(f"  Attachments saved:  {attachments_saved}")
    print(f"  HEIC converted:     {converted}")
    print(f"  HEIC skipped:       {heic_skipped}")
    print(f"  Combined into PDF:  {combined_count} source file(s)")
    if msg_errors:
        print("\n.msg errors:")
        for name, err in msg_errors: print(f"  {name}: {err}")
    if heic_errors:
        print("\nHEIC errors:")
        for name, err in heic_errors: print(f"  {name}: {err}")
    print("\nDone.")

    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass


if __name__ == '__main__':
    main()
