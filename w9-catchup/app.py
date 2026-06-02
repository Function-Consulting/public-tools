"""W-9 Catch-Up — one-off OCR + review tool for historical K:\\W-9s PDFs.

Standalone Flask app.  NOT part of Tallera proper — this exists to
catch up the W-9 compliance tracking on the vendor base by OCR'ing
every PDF already sitting in K:\\W-9s\\<year>\\, fuzzy-matching to
Spectrum vendors, and presenting a side-by-side review UI so Chad
can visually verify each extraction against the source PDF before
exporting a clean CSV for bulk Spectrum import.

Architecture:
  * Single-file Flask app.
  * Cache file (`cache/ocr_results.json`) holds parsed fields per PDF
    keyed by absolute path.  Incremental scans skip already-cached
    entries by (path, mtime, size).
  * Parser logic is a vendored copy of w9_intake's extraction
    functions so this tool has no Tallera dependency.  Update only
    if W-9 form layout changes (Rev. 2018+ is stable through 2026).
  * Spectrum vendor lookup is optional — runs without ODBC for pure
    OCR/review; populates the fuzzy-match column when available.

Routes:
  GET  /                 list view (all cached W-9s, filter by year)
  GET  /review/<id>      single-W-9 review (PDF + editable fields)
  POST /save/<id>        save user edits to cache
  GET  /pdf/<id>         serve the source PDF (security-fenced to W-9 root)
  POST /scan             trigger an incremental scan of W-9 root
  POST /scan/full        force re-OCR every PDF (slow; ignores cache)
  GET  /export.csv       export reviewed entries as CSV for downstream import

Run:
  cd E:\\Tallera\\w9-catchup
  python app.py
  Then open http://127.0.0.1:5099/ in a browser.
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import Optional

from flask import (
    Flask, abort, jsonify, render_template, request,
    send_file, send_from_directory, url_for, redirect,
)


# ─── Paths (dev source vs frozen .exe) ──────────────────────────────────────
# When packaged with PyInstaller (onedir), writable files (cache, settings,
# audit) live NEXT TO the .exe so they persist and are shared when the tool
# is dropped on F:.  Bundled resources (templates) come from _MEIPASS.
_FROZEN = getattr(sys, "frozen", False)
if _FROZEN:
    _APP_DIR = os.path.dirname(sys.executable)
    _RES_DIR = getattr(sys, "_MEIPASS", _APP_DIR)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _RES_DIR = _APP_DIR


# ─── Config ───────────────────────────────────────────────────────────────────

W9_ROOT      = r"K:\W-9s"
CACHE_PATH   = os.path.join(_APP_DIR, "cache", "ocr_results.json")
PORT         = int(os.environ.get("W9_CATCHUP_PORT", "5099"))
HOST         = "127.0.0.1"
# Tesseract OCR binary — defaults to the copy Tallera already ships on F:.
# Editable on the Settings page; only needed when scanning new/image PDFs.
_DEFAULT_TESSERACT = r"F:\Accounting Misc\Software\CM Accounting Utility\tools\tesseract\tesseract.exe"

# Optional Spectrum connection — used only for the vendor master
# fuzzy-match column.  Reads CMC config.json for credentials.  If the
# config file isn't reachable or pyodbc isn't installed, the app runs
# in offline mode and the match column is left blank.
SPECTRUM_CONFIG_PATH = r"F:\Accounting Misc\Software\CM Accounting Utility\config.json"

# ─── Settings (folder roots + Spectrum config path) ──────────────────────────
# Persisted so the tool isn't hardcoded to one folder.  W-9 PDFs live under
# K:\W-9s\<year>\ but also in an assortment of folders on P:\, so scan roots
# are a configurable LIST and each is walked recursively.  Editable on the
# /settings page; survives copying the tool to F:\ for CM after departure.
SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")
_DEFAULT_SCAN_ROOTS = [W9_ROOT]


def _dedupe_paths(paths):
    out, seen = [], set()
    for p in paths:
        p = (p or "").strip()
        k = p.lower()
        if p and k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _load_settings() -> dict:
    s = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                s = json.load(f)
        except Exception as exc:
            logging.getLogger("w9-catchup").warning("settings load failed: %s", exc)
            s = {}
    roots = _dedupe_paths(s.get("scan_roots") or list(_DEFAULT_SCAN_ROOTS))
    if not roots:
        roots = list(_DEFAULT_SCAN_ROOTS)
    return {
        "scan_roots": roots,
        "spectrum_config_path": (s.get("spectrum_config_path") or "").strip()
                                 or SPECTRUM_CONFIG_PATH,
        "tesseract_path": (s.get("tesseract_path") or "").strip()
                           or _DEFAULT_TESSERACT,
        # Optional: only scan PDFs whose filename contains one of these
        # comma-separated substrings (case-insensitive).  Blank = every PDF.
        # Use e.g. "w9, w-9, w 9" when a scan root (like P:) holds non-W-9
        # PDFs you don't want OCR'd.
        "scan_name_filter": (s.get("scan_name_filter") or "").strip(),
    }


def _save_settings(scan_roots, spectrum_config_path, tesseract_path="",
                   scan_name_filter="") -> dict:
    s = {
        "scan_roots": _dedupe_paths(scan_roots) or list(_DEFAULT_SCAN_ROOTS),
        "spectrum_config_path": (spectrum_config_path or "").strip()
                                 or SPECTRUM_CONFIG_PATH,
        "tesseract_path": (tesseract_path or "").strip() or _DEFAULT_TESSERACT,
        "scan_name_filter": (scan_name_filter or "").strip(),
    }
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s


def _scan_roots() -> list:
    return _load_settings()["scan_roots"]


def _spectrum_config_path() -> str:
    return _load_settings()["spectrum_config_path"]


def _tesseract_path() -> str:
    return _load_settings()["tesseract_path"]


# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("w9-catchup")


# ─── W-9 parser (vendored copy of Tallera's w9_intake logic) ──────────────────

W9_FIELD_PATTERNS = {
    "line1_name": re.compile(
        r"1[ \t]+Name[ \t]*\([^)]*?tax[ \t]*return[^)]*?\)[ \t\n]+([^\r\n]+)",
        re.I,
    ),
    "line2_business": re.compile(
        r"2[ \t]+Business[ \t]+name[/]?disregarded[ \t]+entity[ \t]+name[^\r\n]*[\r\n]+([^\r\n]+)",
        re.I,
    ),
    "tin_ssn": re.compile(r"\b(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{4})\b"),
    "tin_ein": re.compile(r"\b(\d{2})[\s\-]?(\d{7})\b"),
    "signature_date": re.compile(
        r"(?:Signature[^\r\n]{0,80}|Date[ \t]+of[ \t]+signature[^\r\n]{0,40})(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        re.I | re.S,
    ),
    "signature_date_fallback": re.compile(
        r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\b"
    ),
    "address": re.compile(
        r"5[ \t]+Address[^\r\n]+[\r\n]+([^\r\n]+)[\r\n]+([^\r\n]+)",
        re.I,
    ),
}

CLASSIFICATION_KEYWORDS = [
    ("Individual/Sole Proprietor", ["individual", "sole prop", "sole-prop"]),
    ("S Corporation",              ["s corp", "s-corp", "s corporation"]),
    ("C Corporation",              ["c corp", "c-corp", "c corporation"]),
    ("Partnership",                ["partnership"]),
    ("Trust/Estate",               ["trust", "estate"]),
    ("LLC",                        ["llc", "limited liability"]),
    ("Other",                      ["other"]),
]


def _strip_ocr_junk(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^[^A-Za-z0-9]+", "", s)
    s = re.sub(r"[:;]+$", ".", s)
    return s.strip()


def _normalize_tin(raw: str) -> dict:
    digits = re.sub(r"\D", "", (raw or ""))
    if len(digits) != 9:
        return {"kind": "", "formatted": "", "digits": digits}
    if re.match(r"^\d{2}-\d{7}$", (raw or "").strip()):
        return {"kind": "EIN",
                "formatted": f"{digits[:2]}-{digits[2:]}",
                "digits": digits}
    if re.match(r"^\d{3}-\d{2}-\d{4}$", (raw or "").strip()):
        return {"kind": "SSN",
                "formatted": f"{digits[:3]}-{digits[3:5]}-{digits[5:]}",
                "digits": digits}
    return {"kind": "EIN",
            "formatted": f"{digits[:2]}-{digits[2:]}",
            "digits": digits}


def _detect_classification(text: str) -> str:
    if not text:
        return ""
    lo = text.lower()
    for label, keywords in CLASSIFICATION_KEYWORDS:
        for kw in keywords:
            if kw in lo:
                return label
    return ""


def extract_w9_fields(page_text: str) -> dict:
    result: dict = {
        "line1_name": "", "line2_business": "", "classification": "",
        "tin_kind": "", "tin_formatted": "", "tin_digits": "",
        "signature_date": "",
        "address_line1": "", "address_line2": "",
        "parse_warnings": [],
    }
    if not page_text:
        result["parse_warnings"].append("empty_text")
        return result

    m = W9_FIELD_PATTERNS["line1_name"].search(page_text)
    if m:
        result["line1_name"] = _strip_ocr_junk(m.group(1))
    else:
        result["parse_warnings"].append("no_line1_name")

    m = W9_FIELD_PATTERNS["line2_business"].search(page_text)
    if m:
        result["line2_business"] = _strip_ocr_junk(m.group(1))

    result["classification"] = _detect_classification(page_text)

    half = page_text[len(page_text) // 2:] if len(page_text) > 400 else page_text
    m_ein = W9_FIELD_PATTERNS["tin_ein"].search(half)
    m_ssn = W9_FIELD_PATTERNS["tin_ssn"].search(half)
    chosen = (m_ssn.group(0) if m_ssn else "") or (m_ein.group(0) if m_ein else "")
    if chosen:
        parsed = _normalize_tin(chosen)
        result.update({
            "tin_kind":      parsed["kind"],
            "tin_formatted": parsed["formatted"],
            "tin_digits":    parsed["digits"],
        })
    else:
        result["parse_warnings"].append("no_tin")

    m = W9_FIELD_PATTERNS["signature_date"].search(page_text)
    if m:
        result["signature_date"] = m.group(1)
    else:
        bottom = page_text[int(len(page_text) * 0.7):]
        m2 = W9_FIELD_PATTERNS["signature_date_fallback"].search(bottom)
        if m2:
            result["signature_date"] = m2.group(1)

    m = W9_FIELD_PATTERNS["address"].search(page_text)
    if m:
        result["address_line1"] = _strip_ocr_junk(m.group(1))
        result["address_line2"] = _strip_ocr_junk(m.group(2))

    return result


# ─── PDF text extraction (text-layer + Tesseract OCR fallback) ────────────────

def _ocr_page_with_layout(img) -> str:
    import pytesseract
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    y_tolerance = 8
    words = []
    for i, t in enumerate(data.get("text", [])):
        t = (t or "").strip()
        if not t:
            continue
        words.append({
            "text": t,
            "left": data["left"][i],
            "center_y": data["top"][i] + data["height"][i] // 2,
        })
    if not words:
        return ""
    words.sort(key=lambda w: (w["center_y"], w["left"]))
    rows = [[words[0]]]
    for w in words[1:]:
        if abs(w["center_y"] - rows[-1][0]["center_y"]) <= y_tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])
    return "\n".join(
        " ".join(w["text"] for w in sorted(row, key=lambda x: x["left"]))
        for row in rows
    )


def _extract_page_texts(pdf_path: str) -> list[str]:
    """Try text-layer first, fall back to OCR per page."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            texts = [(p.extract_text() or "") for p in pdf.pages]
        if any(t.strip() for t in texts):
            return texts
    except Exception as exc:
        logger.debug("text-layer failed on %s: %s", pdf_path, exc)
        texts = []

    try:
        import pytesseract
        import pypdfium2 as pdfium
        # Point pytesseract at the configured Tesseract binary (defaults to
        # the copy Tallera ships on F:).  If it isn't reachable, OCR simply
        # won't run and we fall back to the (already-tried) text layer.
        tp = _tesseract_path()
        if tp and os.path.exists(tp):
            pytesseract.pytesseract.tesseract_cmd = tp
        pdf = pdfium.PdfDocument(pdf_path)
        ocr_texts = []
        try:
            for page in pdf:
                img = page.render(scale=300 / 72).to_pil()
                ocr_texts.append(_ocr_page_with_layout(img))
        finally:
            pdf.close()
        return ocr_texts
    except Exception as exc:
        logger.warning("OCR fallback failed on %s: %s", pdf_path, exc)
        return [""] * max(1, len(texts or []))


# ─── Vendor matching (Spectrum-aware when available, offline otherwise) ──────

def _normalize_company_name(name: str) -> str:
    if not name:
        return ""
    s = name.upper()
    SUFFIXES = (
        ", L.L.C.", " L.L.C.", ", LLC", " LLC", " LTD", ", LTD",
        " L.T.D.", " INCORPORATED", " INC.", ", INC", " INC",
        " CORPORATION", " CORP.", ", CORP", " CORP", " COMPANY",
        " COMPANIES", " & SONS", " AND SONS", " GROUP", " HOLDINGS",
        " LP", " LLP", " PLLC", " PC",
    )
    changed = True
    while changed:
        changed = False
        for suf in SUFFIXES:
            if s.endswith(suf):
                s = s[: -len(suf)].rstrip(" ,.")
                changed = True
                break
    s = re.sub(r"[^A-Z0-9\s&]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _load_spectrum_vendors() -> list[dict]:
    """Best-effort load of active vendors from CMC's Spectrum.  Returns
    [] if config / pyodbc / network unavailable — the app still works
    offline, the match column just stays blank."""
    try:
        import pyodbc
    except ImportError:
        logger.info("pyodbc not installed — running offline (no vendor match).")
        return []
    scp = _spectrum_config_path()
    if not os.path.exists(scp):
        logger.info("Spectrum config not found at %s — offline mode.", scp)
        return []
    try:
        with open(scp) as f:
            cfg = json.load(f)
        o = cfg.get("odbc", {})
        conn_str = f"DSN={o.get('dsn','')}"
        if o.get("username"):
            conn_str += f";UID={o['username']};PWD={o['password']}"
        conn = pyodbc.connect(conn_str, timeout=10)
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT RTRIM(LTRIM(Vendor_Code)),
                       RTRIM(LTRIM(Vendor_Name)),
                       RTRIM(LTRIM(Fed_Id_Number))
                  FROM VN_VENDOR_MASTER_MC
                 WHERE Company_Code='CMC' AND Status='A'
              ORDER BY Vendor_Name
            """)
            return [
                {"code": r[0], "name": r[1], "fed_id": r[2] or ""}
                for r in cur.fetchall() if r[0] and r[1]
            ]
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Spectrum vendor load failed: %s — offline mode.", exc)
        return []


# ─── Spectrum writeback (W-9 received) ────────────────────────────────────────
# Vendored copy of Tallera w9_intake's writeback so this one-time tool has
# NO Tallera dependency.  Marks a vendor's W-9 document-tracking item
# received/closed in Spectrum:
#   1. UPDATE VN_VEND_SUB_DOC_TRACK_MC  Complete_Flag='Y' on the vendor-level
#      (Vendor_Code, Subcontract_Number='', Tracking_Item_Code='W-9') row.
#   2. INSERT VN_VENDOR_SUB_COMPLIANCE_MC event row (Source='V',
#      Entry_Date=W-9 signature date, Entry_Closed='Y').
# Transactional, idempotent, SELECT-after verify.  No DELETE/UPDATE of
# anything else.  Schema verified against live 2026-05-29.

_TABLE_ASSIGN     = "VN_VEND_SUB_DOC_TRACK_MC"
_TABLE_EVENT      = "VN_VENDOR_SUB_COMPLIANCE_MC"
_TRACKING_CODE    = "W-9"
_DEFAULT_OPERATOR = "TLR"
_AUDIT_PATH       = os.path.join(_APP_DIR, "cache", "w9_catchup_audit.jsonl")

# Master switch — flip to False to hard-disable all live posting (dry-run
# previews still work).  This is a deliberate catch-up tool, so it ships on.
WRITEBACK_ENABLED = True

# Spectrum operator code stamped on every W-9 catch-up post (Operator_ID on
# the assignment row, Entry_Closed_Opr on the event row).  This tool is run
# by Chad, so posts are attributed to CHA rather than the shared config's
# operator (KJM).
CATCHUP_OPERATOR = "CHA"


def _spectrum_cfg() -> dict:
    """Load the CMC config.json (ODBC creds + operator) from the configured
    path (defaults to the F: share; editable on /settings)."""
    try:
        with open(_spectrum_config_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_conn():
    """Open a pyodbc connection from the F: config, or raise."""
    import pyodbc
    cfg = _spectrum_cfg()
    o = cfg.get("odbc", {}) or {}
    conn_str = f"DSN={o.get('dsn','')}"
    if o.get("username"):
        conn_str += f";UID={o['username']};PWD={o['password']}"
    return pyodbc.connect(conn_str, timeout=30)


def _company_code() -> str:
    cfg = _spectrum_cfg()
    return (cfg.get("odbc", {}).get("company_codes") or ["CMC"])[0]


def _operator_code() -> str:
    """3-char Spectrum operator code stamped on catch-up posts.  Fixed to
    CATCHUP_OPERATOR (CHA) for this tool rather than the shared config
    operator, since the catch-up is run by Chad."""
    op = (CATCHUP_OPERATOR or _DEFAULT_OPERATOR).strip().upper()
    return (op or _DEFAULT_OPERATOR)[:3]


def _parse_sig_date(s: str) -> Optional[datetime]:
    """Parse a W-9 signature date string (several formats) -> datetime, or
    None if blank/unparseable (caller falls back to today)."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m.%d.%Y", "%m/%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.year < 1990:  # 2-digit / no-year fallbacks land in 1900
                dt = dt.replace(year=datetime.now().year)
            return dt
        except ValueError:
            continue
    return None


def _w9_status(vendor_code: str) -> dict:
    """Read current W-9 tracking state for a vendor (read-only).  Returns
    {ok, vendor_name, has_assignment, complete_flag, last_received,
     fed_id_on_file} or {ok: False, error}."""
    vendor_code = (vendor_code or "").strip()
    if not vendor_code:
        return {"ok": False, "error": "no vendor_code"}
    try:
        cc = _company_code()
        conn = _get_conn()
    except Exception as exc:
        return {"ok": False, "error": f"odbc: {exc}"}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT RTRIM(LTRIM(Vendor_Name)),
                   RTRIM(LTRIM(ISNULL(Fed_Id_Number,''))),
                   RTRIM(LTRIM(ISNULL(Send_1099_Flag,''))),
                   RTRIM(LTRIM(ISNULL(Fed_1099_Indicator,'')))
              FROM VN_VENDOR_MASTER_MC
             WHERE Company_Code = ? AND RTRIM(LTRIM(Vendor_Code)) = ?
        """, cc, vendor_code)
        vrow = cur.fetchone()
        vendor_name = (vrow[0] if vrow else "") or ""
        fed_id = (vrow[1] if vrow else "") or ""
        send_1099 = (vrow[2] if vrow else "") or ""
        fed_1099_box = (vrow[3] if vrow else "") or ""

        cur.execute(f"""
            SELECT RTRIM(LTRIM(ISNULL(Complete_Flag,''))), Setup_Date
              FROM {_TABLE_ASSIGN}
             WHERE Company_Code = ?
               AND RTRIM(LTRIM(Vendor_Code)) = ?
               AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
               AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
        """, cc, vendor_code, _TRACKING_CODE)
        arow = cur.fetchone()
        has_assignment = arow is not None
        complete_flag = (arow[0] if arow else "") or ""

        cur.execute(f"""
            SELECT TOP 1 Entry_Date, RTRIM(LTRIM(ISNULL(Entry_Closed,'')))
              FROM {_TABLE_EVENT}
             WHERE Company_Code = ?
               AND RTRIM(LTRIM(Vendor_Code)) = ?
               AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
               AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
          ORDER BY Entry_Date DESC
        """, cc, vendor_code, _TRACKING_CODE)
        erow = cur.fetchone()
        last_received = (erow[0].strftime("%Y-%m-%d")
                         if erow and erow[1] == "Y" and erow[0] else "")
        return {
            "ok": True,
            "vendor_code": vendor_code,
            "vendor_name": vendor_name,
            "fed_id_on_file": fed_id,
            "send_1099_flag": send_1099.upper(),
            "fed_1099_box": fed_1099_box,
            "has_assignment": has_assignment,
            "complete_flag": complete_flag,
            "already_received": complete_flag.upper() == "Y",
            "last_received": last_received,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def _append_catchup_audit(record: dict) -> None:
    """Append one JSON line to the local audit trail.  Never logs TINs."""
    try:
        os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.warning("audit append failed: %s", exc)


def _writeback_w9_receipt(vendor_code: str, signature_date: str = "",
                          dry_run: bool = False) -> dict:
    """Mark a vendor's W-9 received in Spectrum (UPDATE assignment row +
    INSERT event row), transactional and idempotent.  When ``dry_run`` is
    True, performs the read checks and reports the intended action without
    writing (rolls back).  Mirrors Tallera w9_intake.writeback_w9_receipt.

    Returns {ok, action, vendor_code, before, after, log_id, error}.
    actions: 'wrote_update_and_event' | 'wrote_event' | 'no_change'
             | 'would_write' | 'error'
    """
    result = {"ok": False, "action": "error", "vendor_code": vendor_code,
              "before": None, "after": None, "log_id": None, "error": None,
              "dry_run": dry_run}
    vendor_code = (vendor_code or "").strip()
    if not vendor_code:
        result["error"] = "vendor_code is required"
        return result
    if not WRITEBACK_ENABLED and not dry_run:
        result["error"] = "Live posting is disabled (WRITEBACK_ENABLED=False)."
        return result

    cc = _company_code()
    op = _operator_code()
    now = datetime.now()
    entry_date = _parse_sig_date(signature_date) or now

    try:
        conn = _get_conn()
    except Exception as exc:
        result["error"] = f"ODBC connect failed: {exc}"
        return result

    conn.autocommit = False
    try:
        cur = conn.cursor()
        # 1. Assignment row must exist (added by the 2026-05-28 bulk INSERT).
        cur.execute(f"""
            SELECT RTRIM(LTRIM(ISNULL(Complete_Flag,''))), Setup_Date, Vendor_Code
              FROM {_TABLE_ASSIGN}
             WHERE Company_Code = ?
               AND RTRIM(LTRIM(Vendor_Code)) = ?
               AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
               AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
        """, cc, vendor_code, _TRACKING_CODE)
        before = cur.fetchone()
        if not before:
            result["error"] = (
                f"No W-9 assignment row exists for vendor {vendor_code} in "
                f"{_TABLE_ASSIGN}. Add one first; refusing to post.")
            conn.rollback()
            return result
        result["before"] = {"complete_flag": before[0] or "",
                            "setup_date": before[1].isoformat() if before[1] else ""}
        # Exact space-padded Vendor_Code as stored on the assignment row.  The Job
        # Compliance view (JC_COMPLIANCE_V_MC) joins the closing event to the
        # occurrence on the PADDED vendor code (char(10), right-justified); an
        # RTRIM'd code never matches, so the job-level W-9 stays Open forever.
        # (Root cause found + fixed 2026-06-01.)
        vc_padded = before[2]

        # Idempotency: already Complete + a closed event => no-op.
        already = (before[0] or "").strip().upper() == "Y"
        if already:
            cur.execute(f"""
                SELECT COUNT(*) FROM {_TABLE_EVENT}
                 WHERE Company_Code = ?
                   AND RTRIM(LTRIM(Vendor_Code)) = ?
                   AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
                   AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
                   AND RTRIM(LTRIM(ISNULL(Entry_Closed,''))) = 'Y'
            """, cc, vendor_code, _TRACKING_CODE)
            if (cur.fetchone()[0] or 0) > 0:
                result.update(ok=True, action="no_change", after=result["before"])
                conn.rollback()
                return result

        if dry_run:
            result.update(ok=True, action="would_write",
                          after={"complete_flag": "Y (pending)",
                                 "entry_date": entry_date.strftime("%Y-%m-%d")})
            conn.rollback()
            return result

        # 2. UPDATE assignment row.
        cur.execute(f"""
            UPDATE {_TABLE_ASSIGN}
               SET Complete_Flag = 'Y', Setup_Date = ?, Operator_ID = ?
             WHERE Company_Code = ?
               AND RTRIM(LTRIM(Vendor_Code)) = ?
               AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
               AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
        """, now, op, cc, vendor_code, _TRACKING_CODE)

        # 3. INSERT event row.
        #    Log_ID MUST be the occurrence number the Job Compliance view tracks,
        #    NOT a company high-water value.  W-9 is a single, non-recurring item,
        #    so its only occurrence is '1'.  A high-water Log_ID (e.g. 20260902) is
        #    an orphan the view never joins to, so the job-level W-9 never closes.
        #    Condition='Y' marks the occurrence satisfied; Vendor_Code is the exact
        #    space-padded value (vc_padded) the view joins on.  (Fixed 2026-06-01.)
        log_id = "1"
        cur.execute(f"""
            SELECT COUNT(*) FROM {_TABLE_EVENT}
             WHERE Company_Code = ?
               AND RTRIM(LTRIM(Vendor_Code)) = ?
               AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
               AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
               AND RTRIM(LTRIM(Log_ID)) = '1'
        """, cc, vendor_code, _TRACKING_CODE)
        occ1_exists = (cur.fetchone()[0] or 0) > 0
        if not occ1_exists:
            cur.execute(f"""
                INSERT INTO {_TABLE_EVENT} (
                    Company_Code, Vendor_Code, Subcontract_Number,
                    Tracking_Item_Code, Log_ID, Source,
                    Entry_Date, Condition, Expire_Date,
                    Entry_Closed, Entry_Closed_Opr, Entry_Closed_Date,
                    Due_Date, Comment
                ) VALUES (?, ?, '          ', 'W-9       ', ?, 'V',
                          ?, 'Y', NULL, 'Y', ?, ?, NULL, ?)
            """, cc, vc_padded, log_id, entry_date, op, now, " " * 250)

        # 4. SELECT-after verify.
        cur.execute(f"""
            SELECT RTRIM(LTRIM(ISNULL(Complete_Flag,''))), Setup_Date
              FROM {_TABLE_ASSIGN}
             WHERE Company_Code = ?
               AND RTRIM(LTRIM(Vendor_Code)) = ?
               AND (Subcontract_Number IS NULL OR RTRIM(LTRIM(Subcontract_Number))='')
               AND RTRIM(LTRIM(Tracking_Item_Code)) = ?
        """, cc, vendor_code, _TRACKING_CODE)
        after = cur.fetchone()
        if not after or (after[0] or "").strip().upper() != "Y":
            result["error"] = "Verification did not show Complete_Flag='Y'"
            conn.rollback()
            return result

        conn.commit()
        result.update(
            ok=True, log_id=log_id,
            action="wrote_event" if already else "wrote_update_and_event",
            after={"complete_flag": after[0] or "",
                   "setup_date": after[1].isoformat() if after[1] else "",
                   "log_id": log_id})
        _append_catchup_audit({
            "ts": now.isoformat(timespec="seconds"), "event": "W9_RECEIVED",
            "vendor_code": vendor_code, "operator": op, "log_id": log_id,
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "action": result["action"]})
        logger.info("posted W-9 received: vendor=%s log_id=%s op=%s",
                    vendor_code, log_id, op)
        return result
    except Exception as exc:
        logger.exception("writeback failed")
        try:
            conn.rollback()
        except Exception:
            pass
        result["error"] = f"Writeback failed: {exc}"
        return result
    finally:
        conn.close()


def _format_tin(tin_raw: str, tin_kind: str = "") -> str:
    """Normalize a typed TIN to Spectrum's stored format (digits + dashes),
    capped at Fed_Id_Number's 12 chars.  Returns '' if not 9 digits."""
    digits = re.sub(r"\D", "", tin_raw or "")
    if len(digits) != 9:
        return ""
    kind = (tin_kind or "").strip().upper()
    if kind == "SSN":
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    # default EIN format (also covers blank kind; EIN is the common vendor case)
    return f"{digits[:2]}-{digits[2:]}"


def _update_vendor_tin(vendor_code: str, tin_raw: str, tin_kind: str = "",
                       dry_run: bool = False) -> dict:
    """Targeted UPDATE of VN_VENDOR_MASTER_MC.Fed_Id_Number for one vendor.
    Transactional, idempotent (no-op if the 9 digits already match),
    SELECT-after verify, row-count guarded.  Audit logs last-4 only, never
    the full TIN.  Returns {ok, action, before, after, error}.
    actions: 'updated' | 'no_change' | 'would_update' | 'error'."""
    result = {"ok": False, "action": "error", "vendor_code": vendor_code,
              "before": None, "after": None, "error": None, "dry_run": dry_run}
    vendor_code = (vendor_code or "").strip()
    if not vendor_code:
        result["error"] = "vendor_code required"
        return result
    tin_fmt = _format_tin(tin_raw, tin_kind)
    if not tin_fmt:
        result["error"] = "TIN must be 9 digits (SSN nnn-nn-nnnn or EIN nn-nnnnnnn)"
        return result
    if not WRITEBACK_ENABLED and not dry_run:
        result["error"] = "Live posting is disabled (WRITEBACK_ENABLED=False)."
        return result
    cc = _company_code()
    try:
        conn = _get_conn()
    except Exception as exc:
        result["error"] = f"ODBC connect failed: {exc}"
        return result
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute("""SELECT RTRIM(LTRIM(ISNULL(Fed_Id_Number,'')))
                         FROM VN_VENDOR_MASTER_MC
                        WHERE Company_Code=? AND RTRIM(LTRIM(Vendor_Code))=?""",
                    cc, vendor_code)
        row = cur.fetchone()
        if not row:
            result["error"] = f"vendor {vendor_code} not found"
            conn.rollback()
            return result
        before = row[0] or ""
        result["before"] = before
        if re.sub(r"\D", "", before) == re.sub(r"\D", "", tin_fmt):
            result.update(ok=True, action="no_change", after=before)
            conn.rollback()
            return result
        if dry_run:
            result.update(ok=True, action="would_update", after=tin_fmt)
            conn.rollback()
            return result
        cur.execute("""UPDATE VN_VENDOR_MASTER_MC SET Fed_Id_Number=?
                        WHERE Company_Code=? AND RTRIM(LTRIM(Vendor_Code))=?""",
                    tin_fmt, cc, vendor_code)
        n = cur.rowcount
        cur.execute("""SELECT RTRIM(LTRIM(ISNULL(Fed_Id_Number,'')))
                         FROM VN_VENDOR_MASTER_MC
                        WHERE Company_Code=? AND RTRIM(LTRIM(Vendor_Code))=?""",
                    cc, vendor_code)
        after = (cur.fetchone()[0] or "")
        if n != 1 or re.sub(r"\D", "", after) != re.sub(r"\D", "", tin_fmt):
            result["error"] = f"verification failed (rowcount={n})"
            conn.rollback()
            return result
        conn.commit()
        result.update(ok=True, action="updated", after=after)
        _append_catchup_audit({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": "TIN_UPDATED", "vendor_code": vendor_code,
            "operator": _operator_code(),
            "tin_last4": re.sub(r"\D", "", after)[-4:],
            "had_prior_tin": bool(before)})
        logger.info("updated Fed_Id_Number for vendor %s (had_prior=%s)",
                    vendor_code, bool(before))
        return result
    except Exception as exc:
        logger.exception("TIN update failed")
        try:
            conn.rollback()
        except Exception:
            pass
        result["error"] = f"Update failed: {exc}"
        return result
    finally:
        conn.close()


def _update_vendor_1099(vendor_code: str, send_flag: str,
                        dry_run: bool = False) -> dict:
    """Targeted UPDATE of VN_VENDOR_MASTER_MC.Send_1099_Flag ('Y' or 'N')
    for one vendor.  This is the 'do we issue a 1099?' decision the W-9
    classification answers.  Does NOT touch Fed_1099_Indicator (the box
    code), which is a payment-type decision, not a W-9 one.  Transactional,
    idempotent, SELECT-after verify, row-count guarded, audited.
    actions: 'updated' | 'no_change' | 'would_update' | 'error'."""
    result = {"ok": False, "action": "error", "vendor_code": vendor_code,
              "before": None, "after": None, "error": None, "dry_run": dry_run}
    vendor_code = (vendor_code or "").strip()
    flag = (send_flag or "").strip().upper()
    if not vendor_code:
        result["error"] = "vendor_code required"
        return result
    if flag not in ("Y", "N"):
        result["error"] = "send_flag must be 'Y' or 'N'"
        return result
    if not WRITEBACK_ENABLED and not dry_run:
        result["error"] = "Live posting is disabled (WRITEBACK_ENABLED=False)."
        return result
    cc = _company_code()
    try:
        conn = _get_conn()
    except Exception as exc:
        result["error"] = f"ODBC connect failed: {exc}"
        return result
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute("""SELECT RTRIM(LTRIM(ISNULL(Send_1099_Flag,'')))
                         FROM VN_VENDOR_MASTER_MC
                        WHERE Company_Code=? AND RTRIM(LTRIM(Vendor_Code))=?""",
                    cc, vendor_code)
        row = cur.fetchone()
        if not row:
            result["error"] = f"vendor {vendor_code} not found"
            conn.rollback()
            return result
        before = (row[0] or "").upper()
        result["before"] = before
        if before == flag:
            result.update(ok=True, action="no_change", after=before)
            conn.rollback()
            return result
        if dry_run:
            result.update(ok=True, action="would_update", after=flag)
            conn.rollback()
            return result
        cur.execute("""UPDATE VN_VENDOR_MASTER_MC SET Send_1099_Flag=?
                        WHERE Company_Code=? AND RTRIM(LTRIM(Vendor_Code))=?""",
                    flag, cc, vendor_code)
        n = cur.rowcount
        cur.execute("""SELECT RTRIM(LTRIM(ISNULL(Send_1099_Flag,'')))
                         FROM VN_VENDOR_MASTER_MC
                        WHERE Company_Code=? AND RTRIM(LTRIM(Vendor_Code))=?""",
                    cc, vendor_code)
        after = (cur.fetchone()[0] or "").upper()
        if n != 1 or after != flag:
            result["error"] = f"verification failed (rowcount={n})"
            conn.rollback()
            return result
        conn.commit()
        result.update(ok=True, action="updated", after=after)
        _append_catchup_audit({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": "SEND_1099_UPDATED", "vendor_code": vendor_code,
            "operator": _operator_code(), "before": before, "after": after})
        logger.info("updated Send_1099_Flag for vendor %s: %s -> %s",
                    vendor_code, before or "(blank)", after)
        return result
    except Exception as exc:
        logger.exception("1099 update failed")
        try:
            conn.rollback()
        except Exception:
            pass
        result["error"] = f"Update failed: {exc}"
        return result
    finally:
        conn.close()


def _fuzzy_vendor_match(name: str, active_vendors: list[dict],
                        threshold: float = 0.70,
                        top_n: int = 5) -> dict:
    """Match a parsed name against the vendor master.

    Returns BOTH the single best match (backwards-compatible with
    earlier cache entries) AND the top-N candidates so the review UI
    can show alternatives — empirically the 0.85 single-best-match
    threshold misses most CMC vendors because W-9 legal names diverge
    from how Carol entered them (DBA vs legal entity, abbreviations,
    truncations, ampersand vs "and", etc.).

    Threshold dropped from 0.85 to 0.70 so single-best surfaces more
    candidates as "weak match" rather than no match.  Candidates list
    is always populated (top 5 by ratio) regardless of threshold.
    """
    target = _normalize_company_name(name)
    if not target or not active_vendors:
        return {"vendor_code": "", "vendor_name": "", "ratio": 0.0,
                "candidates": []}

    scored: list[tuple[float, dict]] = []
    for v in active_vendors:
        cand = _normalize_company_name(v.get("name", ""))
        if not cand:
            continue
        r = difflib.SequenceMatcher(None, target, cand).ratio()
        scored.append((r, v))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]
    candidates = [
        {"vendor_code": v["code"], "vendor_name": v["name"], "ratio": r}
        for r, v in top
    ]
    if not candidates:
        return {"vendor_code": "", "vendor_name": "", "ratio": 0.0,
                "candidates": []}
    best = candidates[0]
    out_vendor_code = best["vendor_code"] if best["ratio"] >= threshold else ""
    return {
        "vendor_code": out_vendor_code,
        "vendor_name": best["vendor_name"],
        "ratio":       best["ratio"],
        "candidates":  candidates,
    }


def _match_with_both_lines(extracted: dict,
                           active_vendors: list[dict]) -> dict:
    """Try matching against Line 2 (Business) AND Line 1 (Name) and
    return whichever produces a higher top-ratio.  Often W-9 Line 1
    is the legal entity and Line 2 is the DBA — Carol may have
    entered EITHER in Spectrum, so try both.
    """
    name1 = (extracted.get("line1_name") or "").strip()
    name2 = (extracted.get("line2_business") or "").strip()
    m1 = _fuzzy_vendor_match(name1, active_vendors) if name1 else None
    m2 = _fuzzy_vendor_match(name2, active_vendors) if name2 else None
    # Pick whichever had the higher top candidate ratio.
    def _top(m):
        if not m or not m.get("candidates"):
            return 0.0
        return m["candidates"][0]["ratio"]
    if _top(m2) >= _top(m1):
        result = m2 or {"vendor_code": "", "vendor_name": "",
                        "ratio": 0.0, "candidates": []}
        result["matched_against"] = "line2_business"
    else:
        result = m1 or {"vendor_code": "", "vendor_name": "",
                        "ratio": 0.0, "candidates": []}
        result["matched_against"] = "line1_name"
    return result


# ─── Cache management ─────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {"entries": {}, "scanned_at": ""}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Cache load failed: %s — starting fresh", exc)
        return {"entries": {}, "scanned_at": ""}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, default=str)


def _pdf_id(pdf_path: str) -> str:
    """Stable short id for routing; derived from sha1 of the abs path."""
    return hashlib.sha1(pdf_path.encode("utf-8")).hexdigest()[:16]


def _list_pdfs() -> list[str]:
    """Return abs paths of every PDF under each configured scan root, walked
    RECURSIVELY (K:\\W-9s uses year subfolders; P:\\ has W-9s scattered in an
    assortment of nested folders).  Deduplicated across roots."""
    # Optional filename filter (for roots like P: that hold non-W-9 PDFs).
    patterns = [p.strip().lower()
                for p in (_load_settings().get("scan_name_filter", "") or "").split(",")
                if p.strip()]
    out, seen = [], set()
    for root in _scan_roots():
        if not root or not os.path.isdir(root):
            logging.getLogger("w9-catchup").info(
                "scan root not reachable, skipping: %s", root)
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in sorted(filenames):
                if not fn.lower().endswith(".pdf"):
                    continue
                if patterns and not any(pat in fn.lower() for pat in patterns):
                    continue  # filename doesn't match any W-9 pattern
                p = os.path.abspath(os.path.join(dirpath, fn))
                if p.lower() not in seen:
                    seen.add(p.lower())
                    out.append(p)
    return sorted(out)


def _scan(force: bool = False) -> dict:
    """Walk W9_ROOT, OCR each PDF that's not in cache (or all if force),
    update cache, return summary."""
    cache = _load_cache()
    entries = cache.setdefault("entries", {})
    vendors = _load_spectrum_vendors()
    pdfs = _list_pdfs()
    # Paths the user deleted as duplicates — skip so they don't reappear.
    ignored = {p.lower() for p in cache.get("ignored_paths", [])}
    new_count = re_count = skip_count = 0

    for path in pdfs:
        if path.lower() in ignored:
            continue
        pid = _pdf_id(path)
        try:
            stat = os.stat(path)
            sig = f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            continue

        existing = entries.get(pid)
        if existing and not force and existing.get("file_sig") == sig:
            skip_count += 1
            continue

        # OCR
        page_texts = _extract_page_texts(path)
        per_page = []
        for i, text in enumerate(page_texts):
            ex = extract_w9_fields(text)
            # Try both Line 1 (legal name) and Line 2 (DBA / business).
            # Carol may have entered either in Spectrum, depending on the
            # vendor's setup — Line 1 wins for sole props, Line 2 for
            # most LLC/Inc operators.
            match = _match_with_both_lines(ex, vendors)
            per_page.append({
                "page": i + 1,
                "extracted": ex,
                "match": match,
            })

        # Use first page as primary (W-9s are typically one page; if user
        # has a multi-page scan they can review each).
        primary = per_page[0] if per_page else {"extracted": {}, "match": {}}
        year_folder = os.path.basename(os.path.dirname(path))

        entries[pid] = {
            "id":            pid,
            "path":          path,
            "filename":      os.path.basename(path),
            "year_folder":   year_folder,
            "file_sig":      sig,
            "page_count":    len(page_texts),
            "pages":         per_page,
            "primary":       primary,
            "reviewed":      existing.get("reviewed") if existing else False,
            "user_edits":    existing.get("user_edits") if existing else {},
            "scanned_at":    datetime.now().isoformat(timespec="seconds"),
        }
        if existing:
            re_count += 1
        else:
            new_count += 1
        logger.info("[%s] %s — line1=%r tin=%s match=%s(%.2f)",
                    year_folder, os.path.basename(path),
                    primary["extracted"].get("line1_name", "")[:40],
                    primary["extracted"].get("tin_formatted", ""),
                    primary["match"].get("vendor_code", ""),
                    primary["match"].get("ratio", 0.0))

    cache["scanned_at"] = datetime.now().isoformat(timespec="seconds")
    _save_cache(cache)
    return {"new": new_count, "rescanned": re_count, "skipped": skip_count,
            "total_pdfs": len(pdfs), "vendors_loaded": len(vendors)}


# ─── Flask app ───────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder=os.path.join(_RES_DIR, "templates"))
app.config["JSON_AS_ASCII"] = False


@app.route("/")
def index():
    cache = _load_cache()
    entries = list(cache.get("entries", {}).values())
    year_filter = request.args.get("year", "").strip()
    rev_filter  = request.args.get("rev", "").strip()  # 'yes' | 'no' | ''
    match_filter = request.args.get("match", "").strip()  # 'yes' | 'no' | ''
    # Posted filter defaults to 'unposted' so already-posted W-9s drop off the
    # main screen automatically (less scrolling).  'all' / 'posted' to see them.
    posted_filter = request.args.get("posted", "unposted").strip()

    if year_filter:
        entries = [e for e in entries if e["year_folder"] == year_filter]
    if rev_filter == "yes":
        entries = [e for e in entries if e.get("reviewed")]
    elif rev_filter == "no":
        entries = [e for e in entries if not e.get("reviewed")]
    if match_filter == "yes":
        entries = [e for e in entries if e["primary"]["match"].get("vendor_code")]
    elif match_filter == "no":
        entries = [e for e in entries if not e["primary"]["match"].get("vendor_code")]
    if posted_filter == "unposted":
        entries = [e for e in entries if not e.get("posted")]
    elif posted_filter == "posted":
        entries = [e for e in entries if e.get("posted")]
    # 'all' -> no posted filter

    entries.sort(key=lambda e: (e["year_folder"], e["filename"]))

    # Year facets for the dropdown
    all_years = sorted({e["year_folder"]
                        for e in cache.get("entries", {}).values()})
    total = len(cache.get("entries", {}))
    reviewed = sum(1 for e in cache.get("entries", {}).values()
                   if e.get("reviewed"))
    matched = sum(1 for e in cache.get("entries", {}).values()
                  if e["primary"]["match"].get("vendor_code"))
    posted = sum(1 for e in cache.get("entries", {}).values()
                 if e.get("posted"))

    return render_template("index.html",
                           entries=entries,
                           years=all_years,
                           total=total, reviewed=reviewed, matched=matched,
                           posted=posted,
                           scanned_at=cache.get("scanned_at", ""),
                           year_filter=year_filter,
                           rev_filter=rev_filter,
                           match_filter=match_filter,
                           posted_filter=posted_filter)


@app.route("/review/<pid>")
def review(pid: str):
    cache = _load_cache()
    entry = cache.get("entries", {}).get(pid)
    if not entry:
        abort(404)

    # Build prev / next links within the same filter state for keyboard nav
    all_entries = sorted(cache.get("entries", {}).values(),
                         key=lambda e: (e["year_folder"], e["filename"]))
    ids = [e["id"] for e in all_entries]
    try:
        idx = ids.index(pid)
        prev_id = ids[idx - 1] if idx > 0 else None
        next_id = ids[idx + 1] if idx < len(ids) - 1 else None
    except ValueError:
        prev_id = next_id = None

    return render_template("review.html",
                           entry=entry,
                           prev_id=prev_id, next_id=next_id,
                           idx=idx + 1 if prev_id is not None or next_id is not None else 1,
                           total=len(ids))


@app.route("/save/<pid>", methods=["POST"])
def save(pid: str):
    cache = _load_cache()
    entry = cache.get("entries", {}).get(pid)
    if not entry:
        return jsonify({"ok": False, "error": "not_found"}), 404

    body = request.get_json(silent=True) or {}
    entry["user_edits"] = {
        "vendor_code":       (body.get("vendor_code") or "").strip(),
        "vendor_name":       (body.get("vendor_name") or "").strip(),
        "tin":               (body.get("tin") or "").strip(),
        "tin_kind":          (body.get("tin_kind") or "").strip(),
        "signature_date":    (body.get("signature_date") or "").strip(),
        "classification":    (body.get("classification") or "").strip(),
        "notes":             (body.get("notes") or "").strip(),
    }
    entry["reviewed"] = bool(body.get("reviewed", True))
    entry["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    _save_cache(cache)
    return jsonify({"ok": True, "entry_id": pid,
                    "reviewed": entry["reviewed"]})


@app.route("/delete/<pid>", methods=["POST"])
def delete_entry(pid: str):
    """Remove a cached entry (e.g., a duplicate) from the review list.  Does
    NOT delete the source PDF or touch Spectrum.  The PDF's path is added to
    an ignore list so a future scan won't re-add it."""
    cache = _load_cache()
    entries = cache.get("entries", {})
    entry = entries.get(pid)
    if not entry:
        return jsonify({"ok": False, "error": "not_found"}), 404
    path = entry.get("path", "")
    entries.pop(pid, None)
    ignored = cache.setdefault("ignored_paths", [])
    if path and path not in ignored:
        ignored.append(path)
    _save_cache(cache)
    logger.info("deleted cache entry %s (%s); added to ignore list",
                pid, os.path.basename(path))
    return jsonify({"ok": True, "deleted": pid})


@app.route("/vendors/w9-status")
def vendor_w9_status():
    """Read-only current W-9 document-tracking state for a vendor, so the
    review UI can show 'already received / first receipt / no assignment'
    before posting."""
    code = (request.args.get("code") or "").strip()
    return jsonify(_w9_status(code))


@app.route("/vendors/update-tin", methods=["POST"])
def vendor_update_tin():
    """Reconcile the W-9 TIN against Spectrum's Fed_Id_Number.  Body:
    {vendor_code, tin, tin_kind?, dry_run?}.  Writes only when the user
    chooses to ('use mine'); idempotent if the digits already match."""
    body = request.get_json(silent=True) or {}
    return jsonify(_update_vendor_tin(
        (body.get("vendor_code") or "").strip(),
        (body.get("tin") or "").strip(),
        (body.get("tin_kind") or "").strip(),
        dry_run=bool(body.get("dry_run", False)),
    ))


@app.route("/vendors/update-1099", methods=["POST"])
def vendor_update_1099():
    """Reconcile the 'issue a 1099?' decision against Spectrum's
    Send_1099_Flag.  Body: {vendor_code, send_1099_flag ('Y'/'N'), dry_run?}.
    Writes only when the user chooses; idempotent if already set."""
    body = request.get_json(silent=True) or {}
    return jsonify(_update_vendor_1099(
        (body.get("vendor_code") or "").strip(),
        (body.get("send_1099_flag") or "").strip(),
        dry_run=bool(body.get("dry_run", False)),
    ))


@app.route("/post/<pid>", methods=["POST"])
def post_w9(pid: str):
    """Approve + post a W-9 received to Spectrum document tracking for the
    confirmed vendor on this entry.  Body: {vendor_code?, signature_date?,
    dry_run?}.  Falls back to the entry's saved vendor / signature date."""
    cache = _load_cache()
    entry = cache.get("entries", {}).get(pid)
    if not entry:
        return jsonify({"ok": False, "error": "not_found"}), 404

    body = request.get_json(silent=True) or {}
    ed = entry.get("user_edits") or {}
    m = (entry.get("primary") or {}).get("match") or {}
    ex = (entry.get("primary") or {}).get("extracted") or {}

    vendor_code = (body.get("vendor_code") or ed.get("vendor_code")
                   or m.get("vendor_code") or "").strip()
    signature_date = (body.get("signature_date") or ed.get("signature_date")
                      or ex.get("signature_date") or "").strip()
    dry_run = bool(body.get("dry_run", False))

    if not vendor_code:
        return jsonify({"ok": False, "error": "no vendor selected — pick a "
                        "Spectrum vendor first"}), 400

    result = _writeback_w9_receipt(vendor_code, signature_date, dry_run=dry_run)

    # Persist posted state on a real, successful write (or confirmed no-op).
    if (result.get("ok") and not dry_run
            and result.get("action") in ("wrote_update_and_event",
                                          "wrote_event", "no_change")):
        entry["posted"] = {
            "vendor_code": vendor_code,
            "log_id": result.get("log_id"),
            "action": result.get("action"),
            "posted_at": datetime.now().isoformat(timespec="seconds"),
        }
        entry.setdefault("user_edits", {})["vendor_code"] = vendor_code
        _save_cache(cache)
    result["pid"] = pid
    return jsonify(result)


@app.route("/pdf/<pid>")
def pdf(pid: str):
    """Serve the source PDF.  Path-fenced to the configured scan roots — a
    PDF is served only if it lives under one of them."""
    cache = _load_cache()
    entry = cache.get("entries", {}).get(pid)
    if not entry:
        abort(404)
    path = os.path.abspath(entry["path"])
    roots = [os.path.abspath(r).lower() for r in _scan_roots()]
    if not any(path.lower().startswith(r) for r in roots):
        abort(403)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="application/pdf")


@app.route("/settings")
def settings():
    s = _load_settings()
    checks = [{"path": r, "exists": os.path.isdir(r)} for r in s["scan_roots"]]
    return render_template(
        "settings.html",
        scan_roots=s["scan_roots"], checks=checks,
        spectrum_config_path=s["spectrum_config_path"],
        spectrum_config_exists=os.path.exists(s["spectrum_config_path"]),
        tesseract_path=s["tesseract_path"],
        tesseract_exists=os.path.exists(s["tesseract_path"]),
        scan_name_filter=s["scan_name_filter"],
        default_roots=_DEFAULT_SCAN_ROOTS,
    )


@app.route("/settings", methods=["POST"])
def save_settings_route():
    body = request.get_json(silent=True) or {}
    roots = body.get("scan_roots") or []
    scp = body.get("spectrum_config_path") or ""
    tess = body.get("tesseract_path") or ""
    namefilter = body.get("scan_name_filter") or ""
    saved = _save_settings(roots, scp, tess, namefilter)
    # Reset the in-memory vendor cache so a changed config path takes effect.
    global _VENDORS_CACHE
    _VENDORS_CACHE = []
    checks = [{"path": r, "exists": os.path.isdir(r)} for r in saved["scan_roots"]]
    return jsonify({
        "ok": True,
        "scan_roots": saved["scan_roots"],
        "checks": checks,
        "spectrum_config_path": saved["spectrum_config_path"],
        "spectrum_config_exists": os.path.exists(saved["spectrum_config_path"]),
        "tesseract_path": saved["tesseract_path"],
        "tesseract_exists": os.path.exists(saved["tesseract_path"]),
    })


# Lazy vendor cache for the search endpoint — loaded on first hit and
# kept in memory for the life of the process so the typeahead doesn't
# round-trip to Spectrum per keystroke.
_VENDORS_CACHE: list[dict] = []


def _vendors_search_corpus() -> list[dict]:
    global _VENDORS_CACHE
    if not _VENDORS_CACHE:
        _VENDORS_CACHE = _load_spectrum_vendors()
    return _VENDORS_CACHE


@app.route("/vendors/search")
def vendor_search():
    """Substring + fuzzy search over the active vendor master.  Used by
    the review UI's vendor picker when fuzzy auto-match misses.

    Query params:
        q       search string (case-insensitive)
        limit   max results (default 20)
    """
    q = (request.args.get("q") or "").strip()
    limit = max(1, min(int(request.args.get("limit", "20")), 100))
    vendors = _vendors_search_corpus()
    if not q:
        return jsonify({"results": vendors[:limit]})

    qn = _normalize_company_name(q)
    qlo = q.lower()
    # Two-pass ranking:
    #   1. Substring on raw name (case-insensitive)
    #   2. Substring on vendor code
    #   3. Fuzzy ratio fallback for the rest
    out = []
    seen = set()
    for v in vendors:
        if v["code"] in seen:
            continue
        name = v.get("name", "")
        code = v.get("code", "")
        if qlo in name.lower() or qlo == code.lower() or qlo in code.lower():
            out.append({**v, "match_kind": "substring", "ratio": 1.0})
            seen.add(v["code"])
            if len(out) >= limit:
                return jsonify({"results": out})
    # Fuzzy fallback to fill remaining slots
    if qn:
        scored = []
        for v in vendors:
            if v["code"] in seen:
                continue
            cn = _normalize_company_name(v.get("name", ""))
            if not cn:
                continue
            r = difflib.SequenceMatcher(None, qn, cn).ratio()
            if r >= 0.5:
                scored.append((r, v))
        scored.sort(key=lambda x: x[0], reverse=True)
        for r, v in scored[: max(0, limit - len(out))]:
            out.append({**v, "match_kind": "fuzzy", "ratio": r})
    return jsonify({"results": out})


@app.route("/rematch", methods=["POST"])
def trigger_rematch():
    """Re-run vendor matching against ALREADY-CACHED OCR text.

    Skips re-OCR (the slow part) and just recomputes ``primary.match``
    on every cached entry using the current matcher logic.  Lets us
    backfill the top-N candidate list onto entries that were scanned
    under the old single-best matcher without paying the OCR cost
    again.

    Force-reloads the vendor cache from Spectrum (so a vendor added
    since the last scan gets considered).  Returns counts of
    entries-updated vs entries-skipped (no extracted name).
    """
    global _VENDORS_CACHE
    _VENDORS_CACHE = []  # force reload
    vendors = _vendors_search_corpus()
    cache = _load_cache()
    entries = cache.get("entries", {})
    if not entries:
        return jsonify({"ok": True, "updated": 0, "skipped": 0,
                        "total": 0, "vendors_loaded": len(vendors),
                        "message": "no cached entries to rematch"})

    updated = 0
    skipped = 0
    for pid, entry in entries.items():
        primary = entry.get("primary") or {}
        ex = primary.get("extracted") or {}
        if not (ex.get("line1_name") or ex.get("line2_business")):
            skipped += 1
            continue
        match = _match_with_both_lines(ex, vendors)
        primary["match"] = match
        entry["primary"] = primary
        # Also refresh any per-page matches if multi-page entry
        for page in (entry.get("pages") or []):
            pex = page.get("extracted") or {}
            if pex.get("line1_name") or pex.get("line2_business"):
                page["match"] = _match_with_both_lines(pex, vendors)
        updated += 1

    cache["rematched_at"] = datetime.now().isoformat(timespec="seconds")
    _save_cache(cache)
    logger.info("rematch: updated %d, skipped %d (no name), %d vendors loaded",
                updated, skipped, len(vendors))
    return jsonify({
        "ok": True,
        "updated": updated,
        "skipped": skipped,
        "total": updated + skipped,
        "vendors_loaded": len(vendors),
    })


@app.route("/scan", methods=["POST"])
def trigger_scan():
    summary = _scan(force=False)
    return jsonify({"ok": True, **summary})


@app.route("/scan/full", methods=["POST"])
def trigger_full_scan():
    summary = _scan(force=True)
    return jsonify({"ok": True, **summary})


@app.route("/export.csv")
def export_csv():
    """Export the reviewed entries as CSV, ready for a downstream
    bulk-INSERT into VN_VENDOR_SUB_COMPLIANCE_MC.  Filter to reviewed
    only by default; pass ?all=1 to include unreviewed."""
    include_all = request.args.get("all", "").strip() == "1"
    cache = _load_cache()
    entries = list(cache.get("entries", {}).values())
    if not include_all:
        entries = [e for e in entries if e.get("reviewed")]
    entries.sort(key=lambda e: (e["year_folder"], e["filename"]))

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "vendor_code", "vendor_name", "tin", "tin_kind", "classification",
        "signature_date", "posted_to_spectrum", "year_folder", "filename",
        "ocr_line1", "ocr_line2", "ocr_tin",
        "match_ratio", "reviewed_at", "notes",
    ])
    for e in entries:
        ed = e.get("user_edits", {})
        pr = e.get("primary", {})
        ex = pr.get("extracted", {})
        mt = pr.get("match", {})
        posted = e.get("posted") or {}
        writer.writerow([
            ed.get("vendor_code", mt.get("vendor_code", "")),
            ed.get("vendor_name", mt.get("vendor_name", "")),
            ed.get("tin", ex.get("tin_formatted", "")),
            ed.get("tin_kind", ex.get("tin_kind", "")),
            ed.get("classification", ex.get("classification", "")),
            ed.get("signature_date", ex.get("signature_date", "")),
            "Y" if posted else "",
            e.get("year_folder", ""),
            e.get("filename", ""),
            ex.get("line1_name", ""),
            ex.get("line2_business", ""),
            ex.get("tin_formatted", ""),
            f'{mt.get("ratio", 0):.2f}',
            e.get("reviewed_at", ""),
            ed.get("notes", ""),
        ])

    data = out.getvalue().encode("utf-8")
    fname = f"w9_catchup_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=fname, mimetype="text/csv")


if __name__ == "__main__":
    import threading
    import webbrowser

    print(f"W-9 Catch-Up — http://{HOST}:{PORT}/")
    print(f"SCAN ROOTS  = {_scan_roots()}")
    print(f"CACHE_PATH  = {CACHE_PATH}")
    print(f"SETTINGS    = {SETTINGS_PATH}  (edit folders at /settings)")

    # Auto-open the browser after a brief delay so the Flask server has
    # time to bind before the browser tries to connect.  The
    # WERKZEUG_RUN_MAIN guard would matter under debug=True (reloader
    # fires the main script twice); harmless here but defensive in case
    # someone flips debug on later.
    def _open_browser():
        webbrowser.open(f"http://{HOST}:{PORT}/")
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.0, _open_browser).start()

    app.run(host=HOST, port=PORT, debug=False)
