"""Standalone Job Hub server. Listens on loopback only; Tailscale Serve
publishes it to the tailnet on its own HTTPS port (like the other hubs).
Every request except GET /health passes the passkey gate (auth.py): allowed
Tailscale login, passkey session, and same-origin POSTs only.

  python -m job_monitor.server            # 127.0.0.1:8792
"""

import http.server
import os
import re
import socketserver
import sys
import threading
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as _email_policy
from urllib.parse import parse_qs, urlparse

from . import application, documents, page, register, research
from .auth import GATE

MAX_FORM_BYTES = 64 * 1024                      # text forms (letter bodies included)
MAX_UPLOAD_BYTES = documents.MAX_BYTES + 4096   # one document plus multipart framing

PORT = int(os.environ.get("JOB_HUB_PORT", "8792"))


def parse_amount(text: str):
    """'120000', '120.000 €', '120k', '120,5k' -> int euros; '' -> None."""
    t = (text or "").strip().lower().replace("€", "").replace("eur", "").replace(" ", "")
    if not t:
        return None
    k = t.endswith("k")
    t = t.rstrip("k")
    if k:
        value = float(t.replace(",", "."))
        return int(round(value * 1000))
    t = re.sub(r"[.,](\d{3})(?!\d)", r"\1", t)   # thousands separators
    value = float(t.replace(",", "."))
    return int(round(value * 1000)) if value < 1000 else int(round(value))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", location=None):
        self.send_response(code)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _local(self):
        if self.client_address[0] != "127.0.0.1":
            self._send(403, b"forbidden", "text/plain")
            return False
        return True

    def do_GET(self):
        if not self._local() or not GATE.check(self):
            return
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            q = parse_qs(u.query)
            selected = (q.get("p") or [None])[0]
            view = (q.get("v") or [None])[0]
            undo = (q.get("undo") or [None])[0]
            try:
                self._send(200, page.render_page(selected, view, undo).encode("utf-8"))
            except Exception as e:
                print(f"[JOB_HUB] render error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                self._send(500, "<p>Job Hub konnte gerade nicht geladen werden.</p>".encode("utf-8"))
        elif self.path == "/health":
            self._send(200, b"ok", "text/plain")
        elif u.path in ("/application/cv", "/application/letter"):
            q = parse_qs(u.query)
            name, app_id = (q.get("p") or [""])[0], (q.get("app") or [""])[0]
            if name not in register.list_profiles():
                return self._send(404, b"not found", "text/plain")
            with register.profile_context(name):
                a = application.get(app_id)
                if a is None:
                    return self._send(404, b"not found", "text/plain")
                if u.path == "/application/letter":
                    try:
                        path, fname = application.letter_attachment(a)
                    except Exception as e:
                        print(f"[JOB_HUB] letter render error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                        path, fname = None, None
                else:
                    path = os.path.join(register.profile_dir(), a["cv_tailored_file"]) if a.get("cv_tailored_file") else None
                    fname = a.get("cv_tailored_name") or "Lebenslauf.pdf"
                if not path or not os.path.exists(path):
                    return self._send(404, b"not found", "text/plain")
                with open(path, "rb") as f:
                    body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'inline; filename="{fname}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(404, b"not found", "text/plain")

    def _read_form(self):
        """url-encoded or multipart body -> {field: [values]}, files -> {field: (filename, bytes)}."""
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0) or 0)
        limit = MAX_UPLOAD_BYTES if ctype.startswith("multipart/form-data") else MAX_FORM_BYTES
        if length > limit:
            self.rfile.read(min(length, limit))
            return None, None
        raw = self.rfile.read(length)
        if not ctype.startswith("multipart/form-data"):
            return parse_qs(raw.decode("utf-8", "replace")), {}
        msg = BytesParser(policy=_email_policy).parsebytes(
            b"Content-Type: " + ctype.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
        form, files = {}, {}
        if msg.is_multipart():
            for part in msg.iter_parts():
                field = part.get_param("name", header="content-disposition")
                if not field:
                    continue
                payload = part.get_payload(decode=True) or b""
                if part.get_filename():
                    files[field] = (part.get_filename(), payload)
                else:
                    form.setdefault(field, []).append(payload.decode("utf-8", "replace"))
        return form, files

    def do_POST(self):
        if not self._local() or not GATE.check(self):
            return
        form, files = self._read_form()
        if form is None:
            return self._send(413, "Datei zu groß".encode("utf-8"), "text/plain; charset=utf-8")
        name = (form.get("profile") or [""])[0]
        if name not in register.list_profiles():
            return self._send(400, "Profil fehlt oder unbekannt".encode("utf-8"), "text/plain; charset=utf-8")
        with register.profile_context(name):
            try:
                self._handle_post(name, form, files)
            except (register.ProfileError, documents.DocumentError) as e:
                self._send(400, str(e).encode("utf-8"), "text/plain; charset=utf-8")

    def _handle_post(self, name, form, files):
        f = lambda k: (form.get(k) or [""])[0]
        if self.path == "/upload":
            kind = f("kind")
            if kind not in documents.KINDS or "file" not in files:
                return self._send(400, "Dokumenttyp oder Datei fehlt".encode("utf-8"), "text/plain; charset=utf-8")
            filename, content = files["file"]
            documents.save_upload(kind, filename, content)
        elif self.path == "/document/delete":
            documents.delete(f("kind"))
        elif self.path == "/auto-send":
            profile = register.load_profile()
            ap = profile.setdefault("application", {})
            ap["auto_send"] = not ap.get("auto_send")
            profile.setdefault("changes", []).append({
                "date": datetime.now().date().isoformat(),
                "change": "Autobewerbung: automatischer Versand " + ("eingeschaltet" if ap["auto_send"] else "ausgeschaltet") + " (Hub)"})
            register.save_profile(profile)
        elif self.path == "/apply":
            jid = f("job")
            j = register.state().get(jid)
            if j is None:
                return self._send(404, b"not found", "text/plain")
            why = application.readiness(j)
            if why:
                return self._send(400, ("Autobewerbung nicht möglich: " + ", ".join(why)).encode("utf-8"), "text/plain; charset=utf-8")
            existing = application.for_job(jid)
            if existing and existing["status"] in ("drafting", "pending_approval", "needs_review"):
                return self._send(303, b"", location=f"/?p={name}#{jid}")
            a = application.draft(jid)                     # record exists before the slow part starts
            _background(name, application.tailor_and_maybe_send, a["app_id"])
        elif self.path in ("/application/update", "/application/send", "/application/retailor", "/application/discard"):
            a = application.get(f("app"))
            if a is None:
                return self._send(404, b"not found", "text/plain")
            if self.path == "/application/update":
                application.update(a["app_id"], f("subject"), f("body"),
                                   cv_profile=f("cv_profile") if "cv_profile" in form else None,
                                   mail_text=f("mail_text") if "mail_text" in form else None)
            elif self.path == "/application/send":
                res = application.send(a["app_id"], dry_run=False)
                if res.get("error"):
                    return self._send(400, res["error"].encode("utf-8"), "text/plain; charset=utf-8")
            elif self.path == "/application/retailor":
                _background(name, application.tailor, a["app_id"])
            else:
                application.discard(a["app_id"])
        elif self.path == "/research":
            res = research.start(name, mode=f("mode") if f("mode") in research.MODES else "search")
            if res.get("error"):
                return self._send(409 if res.get("running") else 400,
                                  res["error"].encode("utf-8"), "text/plain; charset=utf-8")
        elif self.path == "/pause":
            profile = register.load_profile()
            profile["paused"] = not profile.get("paused")
            profile.setdefault("changes", []).append({
                "date": datetime.now().date().isoformat(),
                "change": "Monitor pausiert (Hub)" if profile["paused"] else "Monitor fortgesetzt (Hub)"})
            register.save_profile(profile)
        elif self.path == "/inquiry-sent":
            register.mark_inquiry_sent((form.get("job") or [""])[0])
        elif self.path == "/contact-inquiry-sent":
            register.mark_contact_inquiry_sent(f("job"))
        elif self.path == "/reject":
            jid = f("job")
            if jid not in register.state():
                return self._send(404, b"not found", "text/plain")
            view = f("view") if f("view") in dict(page._VIEWS) else "neu"
            if f("value") == "0":
                register.set_rejected(jid, False)
                return self._send(303, b"", location=f"/?p={name}&v={view}#{jid}")
            register.set_rejected(jid, True, f("reason") or None)
            return self._send(303, b"", location=f"/?p={name}&v={view}&undo={jid}")
        elif self.path == "/archive":
            if f("job") not in register.state():
                return self._send(404, b"not found", "text/plain")
            register.set_archived(f("job"), f("value") != "0")
            return self._send(303, b"", location=f"/?p={name}&v={'archiv' if f('value') != '0' else 'neu'}")
        elif self.path == "/contact":
            jid = (form.get("job") or [""])[0]
            email = (form.get("email") or [""])[0].strip()
            name = (form.get("name") or [""])[0].strip()[:100]
            if jid not in register.state():
                return self._send(404, b"not found", "text/plain")
            if not re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[a-zA-Z]{2,}", email):
                return self._send(400, "E-Mail-Adresse nicht gültig".encode("utf-8"), "text/plain; charset=utf-8")
            register.set_manual_contact(jid, name, email)
        elif self.path == "/comp":
            jid = f("job")
            if jid not in register.state():
                return self._send(404, b"not found", "text/plain")
            if f("hourly"):
                try:
                    hourly = float(f("hourly").replace("€", "").replace(",", ".").strip())
                except ValueError:
                    return self._send(400, "Stundenlohn nicht lesbar".encode("utf-8"), "text/plain; charset=utf-8")
                source = f("source") if f("source") in ("employer", "recruiter") else "employer"
                note = f("note")[:300]
                register.set_manual_comp(jid, {"hourly_gross": hourly, "source": source,
                                               "source_note": "Antwort per Mail, im Hub eingetragen" + (f": {note}" if note else "")})
                return self._send(303, b"", location=f"/?p={name}")
            try:
                fix, variable, ote = parse_amount(f("fix")), parse_amount(f("variable")), parse_amount(f("ote"))
            except ValueError:
                return self._send(400, "Betrag nicht lesbar".encode("utf-8"), "text/plain; charset=utf-8")
            if fix is None:
                return self._send(400, "Fixgehalt fehlt".encode("utf-8"), "text/plain; charset=utf-8")
            source = f("source") if f("source") in ("employer", "recruiter") else "employer"
            realism = f("realism") if f("realism") in ("realistic", "uncertain", "unrealistic") else "uncertain"
            note = f("note")[:300]
            comp = {"fix_min": fix, "fix_max": fix, "variable_target": variable,
                    "ote": ote if ote is not None else (fix + (variable or 0)),
                    "source": source, "bonus_realism": realism,
                    "source_note": ("Antwort per Mail, im Hub eingetragen" + (f": {note}" if note else ""))}
            register.set_manual_comp(jid, comp)
        else:
            return self._send(404, b"not found", "text/plain")
        self._send(303, b"", location=f"/?p={name}")


def _background(name: str, fn, *args) -> None:
    """Tailoring takes a minute on the local model; the hub answers at once."""
    def run():
        with register.profile_context(name):
            try:
                fn(*args)
            except Exception as e:
                print(f"[JOB_HUB] background {fn.__name__} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    threading.Thread(target=run, daemon=True).start()


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    with Server(("127.0.0.1", PORT), Handler) as srv:
        print(f"Job Hub on http://127.0.0.1:{PORT}", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
