"""The cover letter as a PDF attachment.

The letter text itself (salutation … closing, as tailored and edited in
the hub) is laid out as a plain business letter: sender block from the
CV header, recipient block from the posting, date, subject line, body.
The mail body carries only a short cover note (application.cover_note).
Same font helper as the CV so both attachments look alike.
"""

import os
import re
from datetime import datetime
from typing import List, Optional

from . import cv_document

_PRIVATE = re.compile(r"^(birthday|geburtstag|geboren|date of birth|geb\.)", re.I)   # not in a letter head
MAX_PAGES = 1
_SCALES = (1.0, 0.95, 0.9, 0.85, 0.8)

_MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
              "September", "Oktober", "November", "Dezember"]


def file_name(owner: str, language: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "_", owner.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("_")
    return ("Cover_Letter_" if language == "en" else "Anschreiben_") + (base or "Bewerbung") + ".pdf"


def date_line(now: Optional[datetime], city: str, language: str) -> str:
    now = now or datetime.now()
    if language == "en":
        d = now.strftime("%d %B %Y").lstrip("0")
    else:
        d = f"{now.day}. {_MONTHS_DE[now.month - 1]} {now.year}"
    return f"{city}, {d}" if city else d


def sender_lines(cv_text: str, owner: str) -> List[str]:
    """Name + address/contact lines from the CV header (nothing invented)."""
    try:
        hf = cv_document.header_fields(cv_document.split(cv_text)["header"]) if cv_text else {}
    except Exception:
        hf = {}
    name = (hf.get("name") or owner or "").strip()
    contact = [c.strip().rstrip(",") for c in (hf.get("contact") or [])
               if c.strip() and not _PRIVATE.match(c.strip())]
    return ([name] if name else []) + contact


def city_of(lines: List[str]) -> str:
    """'10785 Berlin / Germany' -> 'Berlin' (for the date line)."""
    for ln in lines:
        m = re.match(r"^\d{5}\s+([A-Za-zÄÖÜäöüß.\- ]+?)(?:\s*/.*)?$", ln.strip())
        if m:
            return m.group(1).strip()
    return ""


def recipient_lines(posting: dict) -> List[str]:
    out = []
    if posting.get("company"):
        out.append(posting["company"].strip())
    if posting.get("contact_name"):
        out.append(posting["contact_name"].strip())
    loc = (posting.get("location") or "").strip()
    if loc and loc.lower() not in ("remote", "deutschland", "germany"):
        out.append(loc)
    return out


def render(path: str, body: str, sender: List[str], recipient: List[str], subject: str,
           date_text: str) -> str:
    """Writes the PDF and returns its path. Raises when fpdf2 is missing.
    A letter is one page: when the text overflows, body font and spacing
    tighten in steps (like the CV) before a second page is accepted."""
    for scale in _SCALES:
        pages = _render_once(path, body, sender, recipient, subject, date_text, scale)
        if pages <= MAX_PAGES:
            break
    return path


def _render_once(path: str, body: str, sender: List[str], recipient: List[str], subject: str,
                 date_text: str, scale: float) -> int:
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(24, 20, 24)
    font, enc = cv_document._font(pdf)
    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.add_page()
    # sender, small and grey, top right
    pdf.set_font(font, "", 8.5)
    pdf.set_text_color(*cv_document.GREY)
    pdf.set_xy(pdf.l_margin, 18)
    for ln in sender:
        pdf.cell(width, 4.2, enc(ln), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*cv_document.BLUE)
    pdf.set_line_width(0.5)
    y = pdf.get_y() + 2
    pdf.line(pdf.l_margin, y, pdf.l_margin + width, y)
    # recipient
    pdf.set_xy(pdf.l_margin, 46)
    pdf.set_font(font, "", 10.5)
    pdf.set_text_color(0, 0, 0)
    for ln in recipient:
        pdf.cell(width, 5.4, enc(ln), new_x="LMARGIN", new_y="NEXT")
    # date
    pdf.set_xy(pdf.l_margin, 74)
    pdf.cell(width, 5.4, enc(date_text), align="R", new_x="LMARGIN", new_y="NEXT")
    # subject
    pdf.set_xy(pdf.l_margin, 88)
    pdf.set_font(font, "B", 11.5)
    pdf.set_text_color(*cv_document.BLUE)
    pdf.multi_cell(width, 6, enc(subject), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    # body (left-aligned: justified text makes ragged gaps in a short letter)
    fs, lh, gap = 10.5 * scale, 5.6 * scale, 3.5 * scale
    pdf.set_font(font, "", fs)
    pdf.set_text_color(0, 0, 0)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    for i, para in enumerate(paragraphs):
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        # the closing block ("Mit freundlichen Grüßen" + name) keeps its line breaks
        if len(lines) > 1 and len(lines[-1]) < 60 and len(lines) <= 3:
            for ln in lines:
                pdf.multi_cell(width, lh, enc(ln), align="L", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.multi_cell(width, lh, enc(" ".join(lines)), align="L", new_x="LMARGIN", new_y="NEXT")
        if i < len(paragraphs) - 1:
            pdf.ln(gap)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pdf.output(path)
    return pdf.pages_count if hasattr(pdf, "pages_count") else pdf.page
