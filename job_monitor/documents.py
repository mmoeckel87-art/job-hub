"""Application documents per person: the CV and the base cover letter,
uploaded once in the hub. Stored under ``profiles/<name>/documents/`` as
the original file plus the extracted text (``<kind>.txt``) and a small
metadata file. The text is what the tailoring step works with; the
original CV bytes are what gets attached to an application mail.

Nothing here leaves the machine. Text extraction uses pypdf / python-docx
(the same libraries document_intake uses); a PDF without a text layer is
refused with a clear message instead of an empty CV."""

import hashlib
import io
import json
import os
import re
from datetime import datetime
from typing import Optional

from . import register

KINDS = {"cv": "Lebenslauf", "cover_letter": "Anschreiben (Basisversion)", "photo": "Bewerbungsfoto"}
REQUIRED = ("cv", "cover_letter")               # the photo is optional
ALLOWED_EXT = (".pdf", ".docx", ".txt", ".md")
PHOTO_EXT = (".jpg", ".jpeg", ".png")
PHOTO_MIN_BYTES = 15 * 1024                     # icons and logos inside a CV PDF are smaller
MAX_BYTES = 10 * 1024 * 1024
MIN_CHARS = {"cv": 300, "cover_letter": 200}


class DocumentError(ValueError):
    pass


def documents_dir() -> str:
    return os.path.join(register.profile_dir(), "documents")


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def safe_filename(filename: str) -> str:
    base = os.path.basename((filename or "").replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ÄÖÜäöüß-]+", "_", base).strip("._") or "datei"
    return base[:80]


def extract_text(ext: str, content: bytes) -> str:
    if ext == ".pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise DocumentError("PDF ist verschlüsselt – bitte eine ungeschützte Datei hochladen.")
            parts = [(p.extract_text() or "") for p in reader.pages]
        except DocumentError:
            raise
        except Exception as e:   # pypdf raises many different error types
            raise DocumentError(f"PDF konnte nicht gelesen werden ({type(e).__name__}).")
        text = "\n".join(parts)
    elif ext == ".docx":
        import docx
        try:
            d = docx.Document(io.BytesIO(content))
        except Exception as e:
            raise DocumentError(f"DOCX konnte nicht gelesen werden ({type(e).__name__}).")
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(parts)
    else:
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise DocumentError("Textdatei hat eine unbekannte Kodierung.")
    text = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_photo(pdf_bytes: bytes) -> Optional[bytes]:
    """The applicant photo out of a CV PDF: the largest embedded image on
    the first two pages, JPEG bytes. None when there is no usable image."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        best = None
        for page in reader.pages[:2]:
            for im in page.images:
                if len(im.data) >= PHOTO_MIN_BYTES and (best is None or len(im.data) > len(best.data)):
                    best = im
        if best is None:
            return None
        from PIL import Image
        with Image.open(io.BytesIO(best.data)) as img:
            if img.width < 150 or img.height < 150:
                return None
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=88)
            return buf.getvalue()
    except Exception:
        return None


def save_photo(content: bytes, filename: str = "foto.jpg", now: Optional[datetime] = None, source: str = "upload") -> dict:
    from PIL import Image
    try:
        with Image.open(io.BytesIO(content)) as img:
            w, h = img.width, img.height
            if w < 150 or h < 150:
                raise DocumentError("Das Foto ist zu klein (mindestens 150 Pixel).")
            img = img.convert("RGB")
            if w > h * 0.85:                       # landscape or square: portrait crop around the centre, 3:4
                cw = int(h * 0.75)
                left = max(0, (w - cw) // 2)
                img = img.crop((left, 0, left + cw, h))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            data = buf.getvalue()
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("Das ist keine lesbare Bilddatei (JPG oder PNG).")
    d = documents_dir()
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):
        if old.startswith("photo."):
            os.remove(os.path.join(d, old))
    with open(os.path.join(d, "photo.jpg"), "wb") as f:
        f.write(data)
    meta = {"kind": "photo", "filename": safe_filename(filename), "stored": "photo.jpg", "ext": ".jpg", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "width": w, "height": h, "source": source,
            "uploaded_at": (now or datetime.now()).isoformat(timespec="seconds")}
    with open(os.path.join(d, "photo.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


def photo_path() -> Optional[str]:
    p = os.path.join(documents_dir(), "photo.jpg")
    return p if os.path.exists(p) else None


def save_upload(kind: str, filename: str, content: bytes, now: Optional[datetime] = None) -> dict:
    if kind not in KINDS:
        raise DocumentError("Unbekannter Dokumenttyp.")
    ext = _ext(filename)
    if kind == "photo":
        if ext not in PHOTO_EXT:
            raise DocumentError("Erlaubt sind JPG oder PNG.")
        if not content:
            raise DocumentError("Die Datei ist leer.")
        if len(content) > MAX_BYTES:
            raise DocumentError("Die Datei ist größer als 10 MB.")
        return save_photo(content, filename, now)
    if ext not in ALLOWED_EXT:
        raise DocumentError("Erlaubt sind PDF, DOCX, TXT oder MD.")
    if not content:
        raise DocumentError("Die Datei ist leer.")
    if len(content) > MAX_BYTES:
        raise DocumentError("Die Datei ist größer als 10 MB.")
    if ext == ".pdf" and not content.startswith(b"%PDF"):
        raise DocumentError("Das ist keine PDF-Datei.")
    if ext == ".docx" and not content.startswith(b"PK"):
        raise DocumentError("Das ist keine DOCX-Datei.")
    text = extract_text(ext, content)
    if len(text) < MIN_CHARS[kind]:
        raise DocumentError(f"Zu wenig lesbarer Text ({len(text)} Zeichen). Ein gescanntes PDF ohne Textebene "
                            "kann nicht verwendet werden – bitte die Originaldatei aus Word/Pages exportieren.")
    d = documents_dir()
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):               # one file per kind
        if old.startswith(kind + "."):
            os.remove(os.path.join(d, old))
    stored = f"{kind}{ext}"
    with open(os.path.join(d, stored), "wb") as f:
        f.write(content)
    with open(os.path.join(d, f"{kind}.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    meta = {"kind": kind, "filename": safe_filename(filename), "stored": stored, "ext": ext,
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "chars": len(text),
            "uploaded_at": (now or datetime.now()).isoformat(timespec="seconds")}
    with open(os.path.join(d, f"{kind}.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    if kind == "cv" and ext == ".pdf" and not load("photo"):
        photo = extract_photo(content)             # the photo inside the CV, unless one was uploaded on its own
        if photo:
            save_photo(photo, "aus " + safe_filename(filename), now, source="cv")
    return meta


def load(kind: str) -> Optional[dict]:
    """Metadata plus extracted text, or None when nothing is uploaded."""
    d = documents_dir()
    try:
        with open(os.path.join(d, f"{kind}.json"), encoding="utf-8") as f:
            meta = json.load(f)
        if kind == "photo":
            meta["text"] = ""
            return meta if os.path.exists(os.path.join(d, meta.get("stored", "photo.jpg"))) else None
        with open(os.path.join(d, f"{kind}.txt"), encoding="utf-8") as f:
            meta["text"] = f.read().strip()
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return meta


def original_path(kind: str) -> Optional[str]:
    meta = load(kind)
    if not meta:
        return None
    p = os.path.join(documents_dir(), meta["stored"])
    return p if os.path.exists(p) else None


def delete(kind: str) -> bool:
    d = documents_dir()
    removed = False
    if os.path.isdir(d):
        for old in os.listdir(d):
            if old.startswith(kind + "."):
                os.remove(os.path.join(d, old))
                removed = True
    return removed


def status() -> dict:
    return {k: ({kk: vv for kk, vv in m.items() if kk != "text"} if (m := load(k)) else None) for k in KINDS}


def complete() -> bool:
    return all(load(k) for k in REQUIRED)
