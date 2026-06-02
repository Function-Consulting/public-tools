# Third-Party Notices

This repository's tools depend on the following third-party software. Each
dependency's license, copyright, and any required notice text is reproduced
or referenced below.

The user of these tools is responsible for complying with the upstream
licenses of any dependency they install or distribute.

The tools in this repository are licensed under the [GNU AGPL-3.0](LICENSE).
That license applies to the source code written by Function Consulting only
— **not** to the third-party dependencies listed below, each of which has
its own license.

---

## extract-convert-combine-to-pdf

### pillow-heif
- **License:** BSD 3-Clause (Python wrapper)
- **Project:** https://github.com/bigcat88/pillow_heif
- **Note:** The underlying `libheif` library (a runtime binary dependency)
  is LGPL, and its HEVC/x265 components are GPL-2.0. This repository does
  not redistribute `libheif` or its codec binaries — they install
  separately as part of the `pillow-heif` wheel from PyPI. Decode-only
  usage (as in this tool) generally avoids the most restrictive components,
  but verify your specific environment if you intend to redistribute binaries.

### pypdf
- **License:** BSD 3-Clause
- **Project:** https://github.com/py-pdf/pypdf

### extract-msg
- **License:** GNU General Public License v3.0
- **Project:** https://github.com/TeamMsgExtractor/msg-extractor
- **Full license text:** https://www.gnu.org/licenses/gpl-3.0.txt
- **Implication:** Copyleft license. GPL-3.0 code can be combined with
  AGPL-3.0 code as long as the combined work is distributed under AGPL-3.0.
  The primary license of this repository is AGPL-3.0, satisfying this requirement.

### Pillow (PIL fork)
- **License:** MIT-CMU / HPND (Historical Permission Notice and Disclaimer)
- **Project:** https://github.com/python-pillow/Pillow
- **Copyright notice (required):**
  ```
  The Python Imaging Library (PIL) is
      Copyright © 1997-2011 by Secret Labs AB
      Copyright © 1995-2011 by Fredrik Lundh and Contributors

  Pillow is the friendly PIL fork. It is
      Copyright © 2010 by Jeffrey A. Clark and contributors
  ```

---

## pdf-to-csv

### pymupdf (PyMuPDF)
- **License:** Dual-licensed — GNU AGPL-3.0 **or** Artifex commercial license
- **Project:** https://github.com/pymupdf/PyMuPDF
- **Vendor:** https://www.artifex.com
- **Full license text:** https://www.gnu.org/licenses/agpl-3.0.txt
- **Implication:** AGPL is the strictest copyleft license commonly seen.
  This repository's AGPL-3.0 primary license composes cleanly with pymupdf's
  AGPL terms. If you wish to use pymupdf in a closed-source commercial
  product, you must purchase a commercial license from Artifex.

### pdfplumber
- **License:** MIT
- **Project:** https://github.com/jsvine/pdfplumber

---

## pdf-to-markdown

### pymupdf4llm
- **License:** Dual-licensed — GNU AGPL-3.0 **or** Artifex commercial license
- **Project:** https://github.com/pymupdf/pymupdf4llm
- **Vendor:** https://www.artifex.com
- **Note:** Same dual-license terms as pymupdf above; pulls pymupdf in as
  a transitive dependency.

---

## w9-catchup

### Flask
- **License:** BSD 3-Clause
- **Project:** https://github.com/pallets/flask

### pdfplumber
- **License:** MIT
- **Project:** https://github.com/jsvine/pdfplumber

### pytesseract
- **License:** Apache License 2.0
- **Project:** https://github.com/madmaze/pytesseract
- **NOTICE preservation (required by Apache 2.0):**
  ```
  Copyright (c) Samuel Hoffstaetter
  Apache 2.0 License
  ```

### pypdfium2
- **License:** BSD 3-Clause (Python binding); Apache 2.0 (bundled PDFium build)
- **Project:** https://github.com/pypdfium2-team/pypdfium2
- **Note:** PDFium itself (Google's PDF rendering engine) is BSD 3-Clause.
  pypdfium2 bundles a prebuilt PDFium binary distributed under Apache 2.0
  terms for the wheel build process. Both notices are preserved upstream
  inside the installed package.

### pyodbc
- **License:** MIT License
- **Project:** https://github.com/mkleehammer/pyodbc

### Tesseract OCR (external binary, not redistributed)
- **License:** Apache License 2.0
- **Project:** https://github.com/tesseract-ocr/tesseract
- **Note:** Tesseract is an external binary that the user installs
  separately. This repository does not redistribute it. When you install
  Tesseract, you accept its Apache 2.0 license directly.

---

## Full license text — referenced licenses

The complete text of each referenced license is available at the
following canonical URLs:

| License | Canonical text |
|---|---|
| GNU AGPL v3.0 (primary) | https://www.gnu.org/licenses/agpl-3.0.txt |
| GNU GPL v3.0 | https://www.gnu.org/licenses/gpl-3.0.txt |
| GNU LGPL v3.0 | https://www.gnu.org/licenses/lgpl-3.0.txt |
| MIT License | https://opensource.org/license/mit |
| BSD 3-Clause | https://opensource.org/license/bsd-3-clause |
| Apache License 2.0 | https://www.apache.org/licenses/LICENSE-2.0.txt |
| HPND (Pillow) | https://github.com/python-pillow/Pillow/blob/main/LICENSE |

---

## Summary table

| Tool | Dependency | License | Copyleft? |
|---|---|---|---|
| all | Python standard library | PSF | No |
| extract-convert-combine-to-pdf | pillow-heif | BSD-3 (libheif: LGPL) | No (wrapper); partial (binary) |
| extract-convert-combine-to-pdf | pypdf | BSD-3 | No |
| extract-convert-combine-to-pdf | **extract-msg** | **GPL-3.0** | **Yes** |
| extract-convert-combine-to-pdf | Pillow | HPND | No |
| pdf-to-csv | **pymupdf** | **AGPL-3.0 / commercial** | **Yes** |
| pdf-to-csv | pdfplumber | MIT | No |
| pdf-to-markdown | **pymupdf4llm** | **AGPL-3.0 / commercial** | **Yes** |
| pdf-to-markdown | **pymupdf** (transitive) | **AGPL-3.0 / commercial** | **Yes** |
| w9-catchup | Flask | BSD-3 | No |
| w9-catchup | pdfplumber | MIT | No |
| w9-catchup | pytesseract | Apache-2.0 | No |
| w9-catchup | pypdfium2 | BSD-3 / Apache-2.0 | No |
| w9-catchup | pyodbc | MIT | No |
| w9-catchup | Tesseract (binary) | Apache-2.0 | No |

The repository's AGPL-3.0 primary license is the cleanest match given the
GPL-family dependencies. Anyone wishing to incorporate this code into a
closed-source commercial product would need either a commercial-license
agreement covering each AGPL/GPL dependency (Artifex sells one for pymupdf
and pymupdf4llm; no commercial alternative exists for `extract-msg`) or
they'd need to remove the features that depend on those libraries.

---

## If you build a standalone binary (e.g., PyInstaller)

Bundling the dependencies into a single distributable .exe **does**
implicate redistribution. In that case:

- Include the full text of each dependency's license inside the binary's
  distribution (typically as a `licenses/` folder or `LICENSE-THIRD-PARTY.txt`)
- For GPL-3 / AGPL-3 dependencies, additionally offer the corresponding
  source code to recipients (link to the upstream repo satisfies this —
  see GPL-3 / AGPL-3 §6(d))
- For Apache-2.0 dependencies, preserve the NOTICE files where present

The `w9-catchup/W9-Catchup.spec` PyInstaller config does not include a
license-bundling step. If you build a redistributable .exe, add that
step before sharing.

---

## Changes / updates to this notice

If dependencies are upgraded to versions with different licenses, or new
dependencies are added, this file must be updated.

Last verified: 2026-06-02.
