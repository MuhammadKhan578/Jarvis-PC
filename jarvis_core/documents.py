"""Documents: Word, Excel, PowerPoint, PDF, reading, summarising and OCR."""
from __future__ import annotations

import json
import os
import re
import time
from xml.sax.saxutils import escape as xml_escape

from . import core


def _doc_path(filename: str, ext: str) -> str:
    name = core.safe_filename(filename or f"document_{core.stamp()}", "document")
    if not os.path.splitext(name)[1]:
        name += ext
    if os.path.isabs(name) or os.path.dirname(name):
        path = core.resolve_path(name)
    else:
        path = os.path.join(core.DOCS_DIR, name)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        base, e = os.path.splitext(path)
        path = f"{base}_{core.stamp()}{e}"
    return path


def _md_blocks(content: str):
    """Yield (kind, text) from simple Markdown."""
    for raw in (content or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            yield ("blank", "")
        elif s.startswith("### "):
            yield ("h3", s[4:].strip())
        elif s.startswith("## "):
            yield ("h2", s[3:].strip())
        elif s.startswith("# "):
            yield ("h1", s[2:].strip())
        elif re.match(r"^[-*+]\s+", s):
            yield ("bullet", re.sub(r"^[-*+]\s+", "", s))
        elif re.match(r"^\d+[.)]\s+", s):
            yield ("number", re.sub(r"^\d+[.)]\s+", "", s))
        elif s.startswith(">"):
            yield ("quote", s.lstrip("> ").strip())
        elif set(s) <= set("-—_") and len(s) >= 3:
            yield ("hr", "")
        else:
            yield ("p", s)


# --------------------------------------------------------------------------
# Word
# --------------------------------------------------------------------------
def create_word_document(filename: str, title: str, content: str) -> str:
    """Create a formatted Word (.docx) document and open it."""
    try:
        from docx import Document
        from docx.shared import Pt
    except Exception as e:
        return f"python-docx is not available: {e}"
    path = _doc_path(filename, ".docx")
    doc = Document()
    try:
        doc.styles["Normal"].font.name = "Calibri"
        doc.styles["Normal"].font.size = Pt(11)
    except Exception:
        pass
    if title:
        doc.add_heading(title, level=0)
    for kind, text in _md_blocks(content):
        if kind == "h1":
            doc.add_heading(text, level=1)
        elif kind == "h2":
            doc.add_heading(text, level=2)
        elif kind == "h3":
            doc.add_heading(text, level=3)
        elif kind == "bullet":
            doc.add_paragraph(text, style="List Bullet")
        elif kind == "number":
            doc.add_paragraph(text, style="List Number")
        elif kind == "quote":
            p = doc.add_paragraph(text)
            p.style = doc.styles["Intense Quote"] if "Intense Quote" in [s.name for s in doc.styles] else p.style
        elif kind == "hr":
            doc.add_paragraph("_" * 60)
        elif kind == "blank":
            doc.add_paragraph("")
        else:
            doc.add_paragraph(text)
    doc.save(path)
    core.open_path(path)
    return f"Word document created and opened: {path}"


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------
def _parse_json_arg(value):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return None
    return core.parse_json_loose(value)


def create_excel_workbook(filename: str, data_json: str) -> str:
    """Create an Excel (.xlsx) workbook from JSON.

    data_json examples:
      {"sheets":[{"name":"Budget","rows":[["Item","Cost"],["Rent",500]]}]}
      [["Name","Age"],["Ali",20]]
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except Exception as e:
        return f"openpyxl is not available: {e}"
    data = _parse_json_arg(data_json)
    if data is None:
        return "Invalid JSON for the workbook."
    if isinstance(data, list):
        sheets = [{"name": "Sheet1", "rows": data}]
    elif isinstance(data, dict) and isinstance(data.get("sheets"), list):
        sheets = data["sheets"]
    elif isinstance(data, dict) and isinstance(data.get("rows"), list):
        sheets = [{"name": data.get("name", "Sheet1"), "rows": data["rows"]}]
    else:
        return "JSON must contain 'sheets' or be a list of rows."
    path = _doc_path(filename, ".xlsx")
    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="0B3A4A")
    header_font = Font(color="00E5FF", bold=True)
    for si, sheet in enumerate(sheets[:20]):
        name = re.sub(r"[\\/*?:\[\]]", "_", str(sheet.get("name") or f"Sheet{si + 1}"))[:31]
        ws = wb.create_sheet(name)
        rows = sheet.get("rows") or []
        for r_i, row in enumerate(rows, 1):
            if not isinstance(row, (list, tuple)):
                row = [row]
            for c_i, val in enumerate(row, 1):
                cell = ws.cell(row=r_i, column=c_i, value=val)
                if r_i == 1:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center")
        for c_i in range(1, max([len(r) for r in rows if isinstance(r, (list, tuple))] or [1]) + 1):
            try:
                width = max(len(str(ws.cell(row=r, column=c_i).value or "")) for r in range(1, min(len(rows), 40) + 1))
                ws.column_dimensions[get_column_letter(c_i)].width = min(50, max(10, width + 3))
            except Exception:
                pass
        ws.freeze_panes = "A2"
    if not wb.sheetnames:
        wb.create_sheet("Sheet1")
    wb.save(path)
    core.open_path(path)
    return f"Excel workbook created and opened: {path}"


# --------------------------------------------------------------------------
# PowerPoint
# --------------------------------------------------------------------------
def create_powerpoint(filename: str, data_json: str) -> str:
    """Create a PowerPoint (.pptx) deck from JSON.

    data_json: {"slides":[{"title":"Intro","bullets":["point 1","point 2"],"notes":"speaker notes"}]}
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except Exception as e:
        return f"python-pptx is not available: {e}"
    data = _parse_json_arg(data_json)
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        return "JSON must contain a 'slides' list."
    path = _doc_path(filename, ".pptx")
    prs = Presentation()
    slides = data["slides"][:30]
    if not slides:
        return "No slides given."
    # title slide
    first = slides[0]
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = str(first.get("title") or "J.A.R.V.I.S.")
    if len(s.placeholders) > 1:
        s.placeholders[1].text = str(first.get("subtitle") or time.strftime("%d %B %Y"))
    for slide in slides[1:]:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = str(slide.get("title") or "")
        body = s.placeholders[1].text_frame
        body.clear()
        bullets = slide.get("bullets") or []
        for i, b in enumerate(bullets[:12]):
            p = body.paragraphs[0] if i == 0 else body.add_paragraph()
            p.text = str(b)
            p.level = 0
            try:
                p.font.size = Pt(20)
            except Exception:
                pass
        notes = slide.get("notes")
        if notes:
            try:
                s.notes_slide.notes_text_frame.text = str(notes)
            except Exception:
                pass
    prs.save(path)
    core.open_path(path)
    return f"PowerPoint created and opened: {path} ({len(slides)} slides)"


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def create_pdf(filename: str, title: str, content: str) -> str:
    """Create a nicely formatted PDF and open it."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, PageBreak,
                                        Table, TableStyle)
    except Exception as e:
        return f"reportlab is not available: {e}"
    path = _doc_path(filename, ".pdf")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="JTitle", parent=styles["Title"], fontSize=26,
                              textColor=colors.HexColor("#0B3A4A"), spaceAfter=14))
    styles.add(ParagraphStyle(name="JH1", parent=styles["Heading1"], textColor=colors.HexColor("#0B6E8A")))
    styles.add(ParagraphStyle(name="JH2", parent=styles["Heading2"], textColor=colors.HexColor("#0B6E8A")))
    styles.add(ParagraphStyle(name="JBody", parent=styles["BodyText"], fontSize=11, leading=17))
    styles.add(ParagraphStyle(name="JBullet", parent=styles["JBody"], leftIndent=16, bulletIndent=4))
    story = []
    if title:
        story.append(Paragraph(xml_escape(title), styles["JTitle"]))
        story.append(Spacer(1, 6 * mm))
    for kind, text in _md_blocks(content):
        if kind == "h1":
            story.append(Paragraph(xml_escape(text), styles["JH1"]))
        elif kind == "h2":
            story.append(Paragraph(xml_escape(text), styles["JH2"]))
        elif kind == "h3":
            story.append(Paragraph(f"<b>{xml_escape(text)}</b>", styles["JBody"]))
        elif kind == "bullet":
            story.append(Paragraph(xml_escape(text), styles["JBullet"], bulletText="•"))
        elif kind == "number":
            story.append(Paragraph(xml_escape(text), styles["JBullet"], bulletText="–"))
        elif kind == "quote":
            story.append(Paragraph(f"<i>{xml_escape(text)}</i>", styles["JBody"]))
        elif kind == "blank":
            story.append(Spacer(1, 3 * mm))
        elif kind == "hr":
            story.append(Spacer(1, 4 * mm))
        else:
            story.append(Paragraph(xml_escape(text), styles["JBody"]))
        story.append(Spacer(1, 2 * mm))

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6B7C8A"))
        canvas.drawString(18 * mm, 12 * mm, "J.A.R.V.I.S. — " + time.strftime("%d %b %Y"))
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm,
                            title=title or "Jarvis Document", author="J.A.R.V.I.S.")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    core.open_path(path)
    return f"PDF created and opened: {path}"


# --------------------------------------------------------------------------
# Reading / summarising / OCR
# --------------------------------------------------------------------------
def read_document(path: str, max_chars: int = 15000) -> str:
    """Read text from Word, Excel, PowerPoint, PDF, CSV, JSON, Markdown or text files."""
    p = core.resolve_path(path)
    if not os.path.exists(p):
        return f"Not found: {p}"
    ext = os.path.splitext(p)[1].lower()
    try:
        if ext == ".docx":
            from docx import Document
            doc = Document(p)
            parts = [para.text for para in doc.paragraphs if para.text.strip()]
            for ti, table in enumerate(doc.tables, 1):
                parts.append(f"[Table {ti}]")
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n".join(parts)[:max_chars]
        if ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            wb = load_workbook(p, read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                out.append(f"## Sheet: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    if any(v is not None for v in row):
                        out.append(" | ".join("" if v is None else str(v) for v in row))
                    if len("\n".join(out)) > max_chars:
                        break
            wb.close()
            return "\n".join(out)[:max_chars]
        if ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(p)
            out = []
            for i, slide in enumerate(prs.slides, 1):
                out.append(f"## Slide {i}")
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        out.append(shape.text.strip())
                if slide.has_notes_slide:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        out.append(f"(notes: {notes})")
            return "\n".join(out)[:max_chars]
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(p)
            out = []
            for page in reader.pages[:40]:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(out)[:max_chars]
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[:max_chars]
    except Exception as e:
        return f"Could not read {p}: {e}"


def summarize_document(path: str) -> str:
    """Read a document and produce a structured summary + saved report."""
    text = read_document(path, 40000)
    if text.startswith(("Not found:", "Could not read")):
        return text
    if len(text.strip()) < 40:
        return "The document has almost no readable text."
    prompt = (
        "Summarize this document for the user. Use Markdown with:\n"
        "## Overview (2-3 sentences)\n## Key Points (5-8 bullets)\n## Important Numbers / Dates\n"
        "## Action Items (if any)\n## One-line conclusion\n\n"
        f"DOCUMENT: {os.path.basename(path)}\n\n{text[:40000]}"
    )
    summary = core.llm_text(prompt, system="You are a precise document analyst.", smart=True, max_tokens=2200)
    md_path, html_path = core.save_report("Summary - " + os.path.basename(path), summary, open_it=True)
    return f"{summary}\n\nSaved: {html_path or md_path}"


def extract_text_from_image(path: str) -> str:
    """OCR / read all text from an image using Gemini vision."""
    p = core.resolve_path(path)
    if not os.path.exists(p):
        return f"Image not found: {p}"
    try:
        t = core.gen_types()
        mime = "image/png"
        ext = os.path.splitext(p)[1].lower()
        if ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".webp":
            mime = "image/webp"
        with open(p, "rb") as f:
            data = f.read()
        part = t.Part.from_bytes(data=data, mime_type=mime)
        prompt = ("Extract ALL text from this image exactly as written, preserving line breaks. "
                  "If there is no text, describe the image briefly. Do not add commentary.")
        return core.llm_text([part, prompt], smart=False, max_tokens=2000)
    except Exception as e:
        return f"Could not read the image: {e}"


def document_operation(action: str = "read", path: str = "", title: str = "",
                       content: str = "", data_json: str = "", destination: str = "") -> str:
    """One tool for documents.

    action:
      create_word       - Word .docx (title, content in Markdown)
      create_excel      - Excel .xlsx (data_json: {"sheets":[{"name":"...","rows":[...]}]})
      create_powerpoint - PowerPoint .pptx (data_json: {"slides":[{"title":"...","bullets":[...]}]})
      create_pdf        - PDF (title, content in Markdown)
      read              - read any supported document
      summarize         - summarize a document and open the report
      ocr               - extract text from an image
      open              - open a document with its default app
    """
    a = (action or "read").lower().strip().replace("-", "_")
    if a in ("create_word", "word", "docx"):
        return create_word_document(path or title or "document", title or "Document", content)
    if a in ("create_excel", "excel", "xlsx", "spreadsheet"):
        return create_excel_workbook(path or title or "workbook", data_json)
    if a in ("create_powerpoint", "powerpoint", "pptx", "slides", "presentation"):
        return create_powerpoint(path or title or "presentation", data_json)
    if a in ("create_pdf", "pdf"):
        return create_pdf(path or title or "document", title or "Document", content)
    if a in ("read", "open_text"):
        return read_document(path or title)
    if a in ("summarize", "summary"):
        return summarize_document(path or title)
    if a in ("ocr", "image_text", "read_image"):
        return extract_text_from_image(path or title)
    if a == "open":
        return core.open_path(core.resolve_path(path or title))
    return f"Unknown document action '{action}'."
