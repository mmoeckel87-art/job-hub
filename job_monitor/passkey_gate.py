"""Passkey-Schranke für kleine BaseHTTPRequestHandler-Hubs (nur Python-Standardbibliothek).

Gleicher Aufbau wie der Sicherheitshub (another hub): zwei Schranken vor der App.
  1. Tailscale-Identität: `tailscale serve` setzt Tailscale-User-Login; nur Konten aus
     allowed_logins kommen weiter, sonst 403.
  2. Passkey (WebAuthn, Face ID/Gerätecode erforderlich) → Sitzungs-Cookie (12 h,
     Secure, HttpOnly, SameSite=Strict). Jeder POST muss exakt vom eigenen Ursprung kommen.
Die Signaturprüfung macht das System-OpenSSL; hier steht nur CBOR-Parsing und die
WebAuthn-Formatprüfung. Jede App hat ihren eigenen Passkey (eigene user.id), damit ein
neuer Passkey nie den eines anderen Hubs auf demselben Hostnamen ersetzt.

Diese Datei liegt bewusst als identische Kopie in jedem Hub (kein gemeinsames Paket über
Repository-Grenzen hinweg). Einrichtung: `<python> -m <app>.auth enroll` am Mac mini.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
from http.cookies import SimpleCookie

SESSION_TTL = 12 * 3600
ENROLL_TTL = 15 * 60
PREFIX = "/__passkey/"
SPKI_P256_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")


class WebAuthnError(Exception):
    pass


class PasskeyGate:
    def __init__(self, app_name, data_dir, host, https_port, allowed_logins, cookie,
                 local_hosts=(), local_get_ok=False, open_paths=()):
        self.app = app_name
        self.data = data_dir
        self.rp_id = host
        self.origin = "https://%s:%d" % (host, https_port)
        self.tailnet_host = "%s:%d" % (host, https_port)
        self.allowed = list(allowed_logins)
        self.cookie = cookie
        self.local_hosts = set(local_hosts)     # Host-Kopfzeilen für direkten Loopback-Zugriff
        self.local_get_ok = local_get_ok       # nur lesende App: lokal ohne Passkey ansehen
        self.open_paths = set(open_paths)      # z. B. /health, nur GET
        self._sessions = {}
        self._challenges = {}
        self._fails = []
        self._lock = threading.RLock()

    # ---------- Einstieg für den Handler ----------

    def check(self, h):
        """True: Anfrage darf zur App. False: die Schranke hat schon geantwortet."""
        path = h.path.split("?")[0]
        host = h.headers.get("Host", "")
        login = h.headers.get("Tailscale-User-Login")
        if h.command == "GET" and path in self.open_paths:
            return True
        if login is None and host in self.local_hosts:
            if self.local_get_ok and h.command == "GET" and not path.startswith(PREFIX):
                return True
            self._plain(h, 403, "Nur über die Tailnet-Adresse %s erreichbar." % self.origin)
            return False
        if host != self.tailnet_host:
            self._plain(h, 421, "Unbekannter Host.")
            return False
        if login not in self.allowed:
            self._log("access_denied", login or "")
            self._plain(h, 403, "Kein Zugriff.")
            return False
        if h.command not in ("GET", "HEAD") and h.headers.get("Origin") != self.origin:
            self._log("origin_rejected", str(h.headers.get("Origin"))[:120])
            self._plain(h, 403, "Ungültiger Ursprung.")
            return False
        if path.startswith(PREFIX):
            self._own_route(h, path[len(PREFIX):])
            return False
        if self.session(h):
            return True
        if h.command == "GET" and path in ("/", "/index.html"):
            self._html(h, 200, self._login_page())
        elif h.command == "GET":
            h.send_response(303)
            h.send_header("Location", "/")
            h.send_header("Content-Length", "0")
            h.end_headers()
        else:
            self._plain(h, 403, "Sitzung abgelaufen – bitte neu anmelden.")
        return False

    def session(self, h):
        tok = SimpleCookie(h.headers.get("Cookie", "")).get(self.cookie)
        with self._lock:
            s = self._sessions.get(tok.value) if tok else None
            return s if s and s["exp"] > time.time() else None

    # ---------- eigene Routen ----------

    def _own_route(self, h, name):
        if h.command == "GET" and name == "app.js":
            return self._send(h, 200, "text/javascript; charset=utf-8", _JS.replace("__APP__", json.dumps(self.app)))
        if h.command == "GET" and name == "einrichten":
            return self._html(h, 200, self._enroll_page())
        if h.command == "POST" and name == "abmelden":
            tok = SimpleCookie(h.headers.get("Cookie", "")).get(self.cookie)
            with self._lock:
                if tok:
                    self._sessions.pop(tok.value, None)
            h.send_response(303)
            h.send_header("Location", "/")
            h.send_header("Set-Cookie", "%s=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict" % self.cookie)
            h.send_header("Content-Length", "0")
            h.end_headers()
            return None
        if h.command == "POST" and name.startswith("api/"):
            n = min(int(h.headers.get("Content-Length") or 0), 16 * 1024)
            try:
                body = json.loads(h.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("JSON-Objekt erwartet")
            except ValueError:
                return self._json(h, 400, {"error": "Ungültige Anfrage."})
            return self._api(h, name[4:], body)
        return self._plain(h, 404, "Nicht gefunden.")

    def _api(self, h, name, body):
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._challenges.items() if v["exp"] < now]:
                self._challenges.pop(k, None)
            self._fails[:] = [t for t in self._fails if now - t < 600]
            if len(self._fails) > 20:
                return self._json(h, 429, {"error": "Zu viele Versuche, bitte später erneut."})
            creds = self._load("passkeys.json", [])
            if name == "login/begin":
                if not creds:
                    return self._json(h, 400, {"error": "Noch kein Passkey eingerichtet."})
                ch = b64u_enc(secrets.token_bytes(32))
                self._challenges[ch] = {"purpose": "login", "exp": now + 120}
                return self._json(h, 200, {"challenge": ch, "rpId": self.rp_id, "allow": [c["id"] for c in creds]})
            if name == "login/finish":
                chal = self._challenges.pop(str(body.get("challenge", "")), None)
                cred = next((c for c in creds if c["id"] == body.get("id")), None)
                try:
                    if not chal or chal["purpose"] != "login" or not cred:
                        raise WebAuthnError("unbekannte Anmeldung")
                    count = verify_assertion(cred, body["authenticatorData"], body["clientDataJSON"], body["signature"],
                                             b64u_dec(body["challenge"]), self.rp_id, self.origin)
                except (WebAuthnError, KeyError, ValueError, TypeError) as e:
                    self._fails.append(now)
                    self._log("login_failed", str(e)[:200])
                    return self._json(h, 403, {"error": "Anmeldung fehlgeschlagen."})
                cred["sign_count"] = count
                cred["last_used"] = now
                self._save("passkeys.json", creds)
                tok = secrets.token_urlsafe(32)
                self._sessions[tok] = {"exp": now + SESSION_TTL}
                self._log("login_ok", cred.get("label", ""))
                return self._json(h, 200, {"ok": True}, {
                    "Set-Cookie": "%s=%s; Max-Age=%d; Path=/; Secure; HttpOnly; SameSite=Strict" % (self.cookie, tok, SESSION_TTL)})
            if name == "register/begin":
                code = "".join(c for c in str(body.get("code", "")).upper() if c.isalnum())
                digest = hashlib.sha256(code.encode()).hexdigest()
                ent = self._load("enroll.json", {}).get(digest)
                if not ent or ent["exp"] < now:
                    self._fails.append(now)
                    return self._json(h, 403, {"error": "Code ungültig oder abgelaufen."})
                ch = b64u_enc(secrets.token_bytes(32))
                self._challenges[ch] = {"purpose": "register", "exp": now + 300, "code": digest}
                login = self.allowed[0]
                return self._json(h, 200, {"challenge": ch, "rpId": self.rp_id, "userId": self._user_handle(login),
                                           "userName": "%s (%s)" % (self.app, login),
                                           "exclude": [c["id"] for c in creds]})
            if name == "register/finish":
                chal = self._challenges.pop(str(body.get("challenge", "")), None)
                enroll = self._load("enroll.json", {})
                try:
                    if not chal or chal["purpose"] != "register" or chal["code"] not in enroll:
                        raise WebAuthnError("Einrichtung abgelaufen")
                    cred = verify_registration(body["attestationObject"], body["clientDataJSON"],
                                               b64u_dec(body["challenge"]), self.rp_id, self.origin)
                except (WebAuthnError, KeyError, ValueError, TypeError) as e:
                    self._fails.append(now)
                    return self._json(h, 400, {"error": "Passkey konnte nicht geprüft werden: %s" % e})
                enroll.pop(chal["code"], None)
                self._save("enroll.json", enroll)
                cred.update(label=str(body.get("label", ""))[:60], created=now)
                creds.append(cred)
                self._save("passkeys.json", creds)
                self._log("passkey_added", cred["label"])
                return self._json(h, 200, {"ok": True})
        return self._json(h, 404, {"error": "unbekannt"})

    def _user_handle(self, login):
        # pro App eigene Kennung: derselbe Hostname, aber kein Überschreiben fremder Passkeys
        return b64u_enc(hashlib.sha256(("%s:%s" % (self.app, login)).encode()).digest()[:16])

    # ---------- Verwaltung am Mac (CLI) ----------

    def new_enroll_code(self):
        raw = secrets.token_hex(4).upper()
        code = raw[:4] + "-" + raw[4:]
        now = time.time()
        with self._lock:
            enroll = {k: v for k, v in self._load("enroll.json", {}).items() if v["exp"] > now}
            enroll[hashlib.sha256(raw.encode()).hexdigest()] = {"exp": now + ENROLL_TTL}
            self._save("enroll.json", enroll)
        self._log("enroll_code", "")
        return code

    def list_passkeys(self):
        return self._load("passkeys.json", [])

    def revoke(self, prefix):
        with self._lock:
            creds = self._load("passkeys.json", [])
            keep = [c for c in creds if not c["id"].startswith(prefix)]
            if len(creds) - len(keep) != 1:
                return False
            self._save("passkeys.json", keep)
            self._sessions.clear()
        self._log("passkey_revoked", prefix)
        return True

    # ---------- Seiten ----------

    def _page(self, title, body):
        return ("<!doctype html><html lang='de'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<meta name='color-scheme' content='light dark'><title>%s</title><style>%s</style>"
                "<script src='/__passkey/app.js' defer></script></head><body><main>%s</main></body></html>"
                % (_esc(title), _CSS, body))

    def _login_page(self):
        return self._page(self.app, (
            "<h1>%s</h1><p class='muted'>Privat · nur über Tailscale erreichbar</p>"
            "<button id='pk-login'>Mit Passkey anmelden</button><p id='pk-msg' class='muted'></p>"
            "<p class='muted small'>Noch kein Passkey? Am Mac mini den Einrichtungsbefehl ausführen "
            "und dann <a href='/__passkey/einrichten'>hier</a> den Einmalcode eingeben.</p>") % _esc(self.app))

    def _enroll_page(self):
        return self._page("Passkey einrichten", (
            "<h1>Passkey einrichten</h1><p>%s · Einmalcode vom Mac mini eingeben:</p>"
            "<input id='pk-code' autocomplete='one-time-code' autocapitalize='characters' placeholder='XXXX-XXXX'>"
            "<input id='pk-label' placeholder='Gerätename, z. B. iPhone Demo User'>"
            "<button id='pk-enroll'>Passkey erstellen</button><p id='pk-msg' class='muted'></p>") % _esc(self.app))

    # ---------- Hilfen ----------

    def _send(self, h, code, ctype, body, headers=None):
        b = body.encode() if isinstance(body, str) else body
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(b)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Content-Type-Options", "nosniff")
        h.send_header("Referrer-Policy", "same-origin")
        h.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                      "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(b)

    def _html(self, h, code, body):
        self._send(h, code, "text/html; charset=utf-8", body)

    def _plain(self, h, code, text):
        self._send(h, code, "text/plain; charset=utf-8", text)

    def _json(self, h, code, obj, headers=None):
        self._send(h, code, "application/json", json.dumps(obj), headers)

    def _load(self, name, default):
        try:
            with open(os.path.join(self.data, name)) as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    def _save(self, name, obj):
        os.makedirs(self.data, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.data, prefix="." + name + ".")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, os.path.join(self.data, name))

    def _log(self, kind, detail):
        try:
            os.makedirs(self.data, mode=0o700, exist_ok=True)
            p = os.path.join(self.data, "access.jsonl")
            with open(p, "a") as f:
                f.write(json.dumps({"ts": time.time(), "kind": kind, "detail": detail}, ensure_ascii=False) + "\n")
            os.chmod(p, 0o600)
        except OSError:
            pass


def cli(gate, argv):
    """enroll | list | revoke <ID-Anfang>"""
    cmd = argv[0] if argv else ""
    if cmd == "enroll":
        print("Einmalcode (15 Minuten gültig): %s" % gate.new_enroll_code())
        print("Auf dem iPhone öffnen (Tailscale aktiv): %s/__passkey/einrichten" % gate.origin)
        print("Der laufende Hub muss dafür nicht neu gestartet werden.")
        return 0
    if cmd == "list":
        for c in gate.list_passkeys():
            print("%s  %-28s  eingerichtet %s  zuletzt %s" % (
                c["id"][:12], c.get("label") or "ohne Namen", _day(c.get("created")), _day(c.get("last_used"))))
        return 0
    if cmd == "revoke" and len(argv) == 2:
        if gate.revoke(argv[1]):
            print("Passkey entfernt. Laufende Sitzungen enden erst mit einem Neustart des Hubs.")
            return 0
        print("Kein eindeutiger Passkey mit diesem ID-Anfang.")
        return 1
    print("Befehle: enroll | list | revoke <ID-Anfang>")
    return 2


def _day(ts):
    return time.strftime("%d.%m.%Y", time.localtime(ts)) if ts else "–"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;")


# ---------- WebAuthn (ES256), identisch zu another hub/webauthn.py ----------

def b64u_enc(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s):
    s = str(s)
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def cbor_decode(data, i=0):
    ib = data[i]
    i += 1
    major, info = ib >> 5, ib & 0x1F
    if info < 24:
        val = info
    elif info in (24, 25, 26, 27):
        n = 1 << (info - 24)
        val = int.from_bytes(data[i:i + n], "big")
        i += n
    else:
        raise WebAuthnError("CBOR: nicht unterstützte Länge")
    if major == 0:
        return val, i
    if major == 1:
        return -1 - val, i
    if major == 2:
        return bytes(data[i:i + val]), i + val
    if major == 3:
        return data[i:i + val].decode(), i + val
    if major == 4:
        out = []
        for _ in range(val):
            v, i = cbor_decode(data, i)
            out.append(v)
        return out, i
    if major == 5:
        out = {}
        for _ in range(val):
            k, i = cbor_decode(data, i)
            v, i = cbor_decode(data, i)
            out[k] = v
        return out, i
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], i
    raise WebAuthnError("CBOR: nicht unterstützter Typ")


def _client_data(cdj, typ, challenge, origin):
    c = json.loads(cdj)
    if c.get("type") != typ:
        raise WebAuthnError("falscher Typ")
    if not hmac.compare_digest(b64u_dec(c.get("challenge", "")), challenge):
        raise WebAuthnError("Challenge stimmt nicht")
    if c.get("origin") != origin:
        raise WebAuthnError("Origin stimmt nicht: %s" % c.get("origin"))
    if c.get("crossOrigin"):
        raise WebAuthnError("crossOrigin nicht erlaubt")


def _auth_data(ad, rp_id):
    if len(ad) < 37:
        raise WebAuthnError("authData zu kurz")
    if not hmac.compare_digest(ad[:32], hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError("RP-ID-Hash stimmt nicht")
    flags = ad[32]
    if not flags & 0x01:
        raise WebAuthnError("Nutzerpräsenz fehlt")
    if not flags & 0x04:
        raise WebAuthnError("Nutzerverifikation (Face ID/Code) fehlt")
    return flags, int.from_bytes(ad[33:37], "big")


def verify_registration(attestation_b64, cdj_b64, challenge, rp_id, origin):
    cdj = b64u_dec(cdj_b64)
    _client_data(cdj, "webauthn.create", challenge, origin)
    att, _ = cbor_decode(b64u_dec(attestation_b64))
    ad = att["authData"]
    flags, count = _auth_data(ad, rp_id)
    if not flags & 0x40:
        raise WebAuthnError("keine Credential-Daten")
    n = int.from_bytes(ad[53:55], "big")
    cred_id = ad[55:55 + n]
    cose, _ = cbor_decode(ad, 55 + n)
    if cose.get(1) != 2 or cose.get(3) != -7 or cose.get(-1) != 1:
        raise WebAuthnError("nur ES256/P-256 unterstützt")
    x, y = cose[-2], cose[-3]
    if len(x) != 32 or len(y) != 32:
        raise WebAuthnError("ungültiger Schlüssel")
    spki = SPKI_P256_PREFIX + b"\x04" + x + y
    return {"id": b64u_enc(cred_id), "spki": spki.hex(), "sign_count": count}


def verify_assertion(cred, auth_data_b64, cdj_b64, sig_b64, challenge, rp_id, origin):
    cdj = b64u_dec(cdj_b64)
    _client_data(cdj, "webauthn.get", challenge, origin)
    ad = b64u_dec(auth_data_b64)
    _, count = _auth_data(ad, rp_id)
    if not es256_verify(bytes.fromhex(cred["spki"]), b64u_dec(sig_b64), ad + hashlib.sha256(cdj).digest()):
        raise WebAuthnError("Signatur ungültig")
    if count and cred.get("sign_count") and count <= cred["sign_count"]:
        raise WebAuthnError("Signaturzähler zurückgesetzt – möglicher Klon")
    return count


def es256_verify(spki_der, sig_der, data):
    pem = "-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----\n" % base64.b64encode(spki_der).decode()
    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for name, content in (("k.pem", pem.encode()), ("s.bin", sig_der), ("d.bin", data)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "wb") as f:
                f.write(content)
        p = subprocess.run(["/usr/bin/openssl", "dgst", "-sha256", "-verify", paths["k.pem"],
                            "-signature", paths["s.bin"], paths["d.bin"]],
                           capture_output=True, text=True, timeout=10)
        return p.returncode == 0 and "Verified OK" in p.stdout


_CSS = """
body{font:16px -apple-system,system-ui,sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}
main{max-width:420px;margin:12vh auto;padding:0 16px}
h1{font-size:26px;margin:0 0 4px}
.muted{color:#6e6e73}.small{font-size:13px}
button,input{display:block;width:100%;box-sizing:border-box;font:inherit;padding:12px;margin:12px 0;border-radius:10px}
input{border:1px solid #c7c7cc;background:#fff;color:inherit}
button{border:0;background:#0071e3;color:#fff;font-weight:600}
a{color:#0071e3}
@media (prefers-color-scheme:dark){body{background:#000;color:#f5f5f7}.muted{color:#a1a1a6}
input{background:#1c1c1e;border-color:#3a3a3c}a{color:#2997ff}}
"""

_JS = r"""
(function () {
  var APP = __APP__;
  function enc(buf) {
    var s = String.fromCharCode.apply(null, new Uint8Array(buf));
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function dec(str) {
    str = str.replace(/-/g, '+').replace(/_/g, '/');
    while (str.length % 4) str += '=';
    var b = atob(str), a = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) a[i] = b.charCodeAt(i);
    return a.buffer;
  }
  function post(url, body) {
    return fetch('/__passkey/api/' + url, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body), credentials: 'same-origin'})
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); });
  }
  function msg(t) { var m = document.getElementById('pk-msg'); if (m) m.textContent = t; }

  var login = document.getElementById('pk-login');
  if (login) login.addEventListener('click', function () {
    msg('');
    post('login/begin', {}).then(function (o) {
      return navigator.credentials.get({publicKey: {
        challenge: dec(o.challenge), rpId: o.rpId, userVerification: 'required', timeout: 60000,
        allowCredentials: o.allow.map(function (id) { return {type: 'public-key', id: dec(id)}; })
      }}).then(function (a) {
        return post('login/finish', {challenge: o.challenge, id: enc(a.rawId),
          authenticatorData: enc(a.response.authenticatorData),
          clientDataJSON: enc(a.response.clientDataJSON), signature: enc(a.response.signature)});
      });
    }).then(function () { location.reload(); })
      .catch(function (e) { msg('Anmeldung nicht möglich: ' + e.message); });
  });

  var enroll = document.getElementById('pk-enroll');
  if (enroll) enroll.addEventListener('click', function () {
    msg('');
    post('register/begin', {code: document.getElementById('pk-code').value}).then(function (o) {
      return navigator.credentials.create({publicKey: {
        challenge: dec(o.challenge), rp: {id: o.rpId, name: APP},
        user: {id: dec(o.userId), name: o.userName, displayName: o.userName},
        pubKeyCredParams: [{type: 'public-key', alg: -7}],
        authenticatorSelection: {residentKey: 'preferred', userVerification: 'required'},
        attestation: 'none', timeout: 120000,
        excludeCredentials: o.exclude.map(function (id) { return {type: 'public-key', id: dec(id)}; })
      }}).then(function (c) {
        return post('register/finish', {challenge: o.challenge, label: document.getElementById('pk-label').value,
          attestationObject: enc(c.response.attestationObject), clientDataJSON: enc(c.response.clientDataJSON)});
      });
    }).then(function () { msg('Passkey eingerichtet. Weiter zur Anmeldung …'); setTimeout(function () { location.href = '/'; }, 1200); })
      .catch(function (e) { msg('Einrichtung nicht möglich: ' + e.message); });
  });
})();
"""
