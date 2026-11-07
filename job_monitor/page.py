"""Standalone job hub page (served by job_monitor/server.py).

One card per posting answers, in this order: how well does it fit, what
does it probably pay, how sure is that, what is the next step. Sources,
reasons and forms sit behind "Details & Quellen". Every card has one
primary action; status is readable without colour (symbol + words)."""

import html
from datetime import datetime
from typing import Optional

from . import application, cv_document, documents, register, research, salary, sources

_VIEWS = (("neu", "Neu"), ("offen", "In Arbeit"), ("beworben", "Beworben"), ("archiv", "Archiv"))
_VIEW_HINT = {"neu": "Neue Treffer, noch ohne Entscheidung.",
              "offen": "Entwürfe und Rückfragen, die auf dich warten.",
              "beworben": "Verschickt an die Adresse aus der Anzeige oder Recherche.",
              "archiv": "Aussortiert, archiviert oder verworfene Entwürfe."}

_LABEL = {"NOTIFY": "Meldebereit", "NOTIFIED": "Gemeldet", "REVIEW": "Intern prüfen", "DISCARD": "Verworfen"}
_REMOTE = {"remote": "Remote", "remote_de": "Remote (DE)", "hybrid": "Hybrid", "onsite": "Vor Ort", "unknown": ""}

CSS = """
:root{--bg:#f2f2f7;--card:#fff;--text:#1c1c1e;--muted:#6e6e73;--line:#e5e5ea;--soft:#f7f7f9;--accent:#007aff;--warn:#c76a00;--warn-bg:#ff950026;--ok:#1f7a36;--bad:#c0392b}
@media (prefers-color-scheme: dark){:root{--bg:#000;--card:#1c1c1e;--text:#f2f2f7;--muted:#98989d;--line:#38383a;--soft:#2c2c2e;--accent:#0a84ff;--warn:#ffb340;--warn-bg:#ff9f0a2e;--ok:#5fd27a;--bad:#ff6b61}}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif;-webkit-font-smoothing:antialiased;line-height:1.4}
.wrap{max-width:720px;margin:0 auto;padding:20px 16px 56px}
h1{font-size:1.7rem;letter-spacing:-.01em;margin:4px 0}
h2{font-size:1.25rem;margin:0}
a{color:var(--accent)}
.person{margin-top:28px}
.sub{font-size:.84rem;color:var(--muted);margin-top:3px}
.note{font-size:.84rem;color:var(--muted);background:var(--card);border-radius:12px;padding:12px 14px;margin-top:12px}
.incomplete{background:var(--warn-bg);color:var(--warn);border-radius:12px;padding:12px 14px;margin-top:14px;font-size:.88rem}
.incomplete ul{color:var(--text);margin-top:6px;padding-left:18px}
.section{margin-top:28px}
.title{font-size:.78rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:16px}
.kpi{background:var(--card);border-radius:14px;padding:14px 16px;display:grid;gap:2px}
.kpi b{font-size:1.25rem;font-weight:600}
.kpi span{font-size:.78rem;color:var(--muted)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:10px 16px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--accent);font-size:.95rem;font-weight:500;text-decoration:none;cursor:pointer;font-family:inherit;line-height:1.2}
.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.danger{color:var(--bad)}
.btn.quiet{border:0;background:transparent;min-height:36px;padding:6px 10px;font-size:.88rem}
.btn[disabled]{opacity:.5;cursor:default}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.cta{display:grid;gap:8px;margin-top:14px}
.cta .btn{width:100%}
.cta form{display:contents}
@media (min-width:600px){.cta{grid-auto-flow:column;justify-content:start}.cta .btn{width:auto;min-width:220px}}
.job{background:var(--card);border-radius:16px;padding:18px 18px 14px;margin-bottom:12px}
.kicker{font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.job .t{display:block;font-size:1.15rem;font-weight:600;color:var(--text);text-decoration:none;margin-top:4px;line-height:1.25}
.tag{display:inline-block;font-size:.72rem;padding:3px 8px;border-radius:999px;background:var(--line);color:var(--muted);margin:8px 6px 0 0}
.tag.warn{background:var(--warn-bg);color:var(--warn)}
.fit{display:flex;justify-content:space-between;align-items:baseline;margin-top:14px;font-size:.95rem}
.fit b{font-weight:600}.fit span{color:var(--muted);font-variant-numeric:tabular-nums}
.bar{height:5px;border-radius:3px;background:var(--line);margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
.why{font-size:.86rem;color:var(--muted);margin-top:8px}
.block{margin-top:16px;padding-top:12px;border-top:1px solid var(--line)}
.bt{font-size:.74rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.kv{display:flex;justify-content:space-between;gap:12px;font-size:.95rem;padding:3px 0}
.kv span{color:var(--muted);flex:1 1 auto}.kv b{font-weight:600;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.verdict{margin-top:8px;font-size:.95rem;font-weight:600}
.verdict.v-met{color:var(--ok)}.verdict.v-overlap{color:var(--warn)}.verdict.v-below{color:var(--bad)}.verdict.v-unknown{color:var(--muted)}
.route{font-size:.95rem;margin-top:2px}
.state{font-size:.84rem;color:var(--muted);margin-top:4px}
details.more{margin-top:12px}
details.more>summary{cursor:pointer;font-size:.9rem;color:var(--accent);padding:10px 0;list-style:none}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::after{content:" ›";}
details.more[open]>summary::after{content:" ⌄";}
.more ul{padding-left:18px;font-size:.88rem;margin-top:6px}
.more li{margin:3px 0}
.srcs{font-size:.84rem;color:var(--muted);margin-top:6px}
.srcs li{margin:4px 0}
.facts{font-size:.86rem;margin-top:6px}
.minor{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:8px;font-size:.86rem}
.minor form{display:inline}
details.form{width:100%;margin-top:8px}
details.form>summary{cursor:pointer;font-size:.9rem;color:var(--accent);padding:8px 0}
details.form form{display:grid;gap:10px;margin-top:8px}
details.form label{display:grid;gap:4px;font-size:.8rem;color:var(--muted)}
details.form input,details.form select,details.form textarea,.panel input[type=text]{font:inherit;font-size:16px;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);width:100%}
details.form textarea{min-height:240px;line-height:1.4;font-size:15px}
.tabs{display:flex;gap:4px;margin-top:14px;background:var(--card);padding:4px;border-radius:12px;width:fit-content;max-width:100%;overflow-x:auto}
.tabs a{font-size:.9rem;font-weight:600;color:var(--muted);text-decoration:none;padding:10px 16px;border-radius:9px;white-space:nowrap}
.tabs a.on{background:var(--accent);color:#fff}
.tabs.views{margin-top:20px;width:100%;display:grid;grid-template-columns:repeat(4,1fr)}
.tabs.views a{font-size:.84rem;padding:9px 4px;text-align:center}
.panel{background:var(--card);border-radius:12px;padding:12px 14px;margin-bottom:8px}
.panel form{display:grid;gap:8px;margin-top:8px}
.panel input[type=file]{font-size:.85rem}
.chip{display:inline-block;font-size:.74rem;padding:3px 9px;border-radius:999px;background:var(--line);margin-left:6px;vertical-align:middle}
.chip.ok{background:#34c75933;color:var(--ok)}.chip.wait{background:var(--warn-bg);color:var(--warn)}.chip.bad{background:#ff3b3026;color:var(--bad)}
.letter{white-space:pre-wrap;font-size:.86rem;line-height:1.45;margin-top:8px;max-height:320px;overflow:auto;padding:10px;border:1px solid var(--line);border-radius:8px}
.src{columns:2;font-size:.82rem;padding-left:18px}
@media (max-width:520px){.src{columns:1}}
details.settings{margin-top:34px;border-top:1px solid var(--line);padding-top:8px}
details.settings>summary{cursor:pointer;font-size:1rem;font-weight:600;padding:12px 0;list-style:none}
details.settings>summary::-webkit-details-marker{display:none}
details.settings>summary::after{content:" ›";color:var(--muted)}
details.settings[open]>summary::after{content:" ⌄"}
.settings ul{padding-left:18px;font-size:.88rem}
.empty{background:var(--card);border-radius:16px;padding:22px 18px;color:var(--muted);font-size:.92rem}
.summary{font-size:.95rem;line-height:1.45;margin-top:10px}
.reject{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-left:auto}
.reject .btn{border:1px solid var(--line);min-height:40px;padding:6px 14px}
.reject select{font:inherit;font-size:.88rem;min-height:40px;padding:6px 10px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--muted);max-width:180px}
.undo{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-top:14px;font-size:.92rem}
.undo form{display:inline}
@media (max-width:599px){.minor{flex-direction:column;align-items:stretch}.reject{margin-left:0;justify-content:space-between}.reject select{flex:1 1 auto;max-width:none}}
"""


def _eur(v):
    if v is None:
        return "–"
    return (f"{v / 1000:.0f}k €" if v % 1000 == 0 else f"{v / 1000:.1f}k €".replace(".", ","))


def _hidden(name: str, j: dict) -> str:
    return (f"<input type='hidden' name='profile' value='{html.escape(name)}'>"
            f"<input type='hidden' name='job' value='{html.escape(j['job_id'])}'>")


def _fit_label(fit: float, profile: dict) -> str:
    th = profile.get("thresholds") or {}
    cp = profile.get("compensation") or {}
    if fit >= cp.get("exceptional_fit_score", 85):
        return "Außergewöhnliche Passung"
    if fit >= th.get("fit_notify", 70):
        return "Sehr gute Passung"
    if fit >= th.get("fit_review", 50):
        return "Mögliche Passung"
    return "Geringe Passung"


def _short_location(p: dict) -> str:
    """'Berlin, hybrid (2 Tage)' -> 'Berlin' – the work model has its own word."""
    loc = (p.get("location") or "").split("(")[0].split(";")[0]
    parts = [x.strip() for x in loc.split(",")]
    parts = [x for x in parts if x and x.lower() not in ("hybrid", "remote", "homeoffice", "home office", "vor ort", "onsite", "remote deutschland", "work from home")]
    return ", ".join(parts)[:40]


def _salary_block(j: dict, profile: dict) -> str:
    """Gehaltsschätzung: fix / with target bonus / realistic, verdict, trust line."""
    ev = j["evaluation"]
    s = ev.get("salary") or {}
    c = ev["comp"]
    if c.get("basis") == "net_monthly":
        if c.get("evidenced"):
            body = (f"<div class='kv'><span>Stundenlohn</span><b>{c['hourly']:.2f} € brutto/Std.</b></div>".replace(f"{c['hourly']:.2f}", f"{c['hourly']:.2f}".replace(".", ","))
                    + f"<div class='kv'><span>≈ pro Monat</span><b>{_eur(c['monthly_gross_at_max_hours'])}</b></div>")
        else:
            body = "<div class='kv'><span>Stundenlohn</span><b>unbekannt</b></div>"
        return f"<div class='block'><div class='bt'>Vergütung</div>{body}</div>"
    if s.get("fix_min") is None:
        body = ("<div class='kv'><span>Fixgehalt</span><b>noch unbekannt</b></div>"
                f"<div class='verdict v-unknown'>{s.get('symbol', '?')} {html.escape(s.get('label') or 'Gehalt noch nicht einschätzbar')}</div>"
                "<div class='state'>Keine Angabe in der Anzeige, noch keine belastbare Schätzung. „Nachrecherche“ oben sucht Vergleichsdaten.</div>")
        return f"<div class='block'><div class='bt'>Gehaltsschätzung</div>{body}</div>"
    rows = f"<div class='kv'><span>Fixgehalt</span><b>{salary.eur_range(s['fix_min'], s['fix_max'])} / Jahr</b></div>"
    if s.get("ote_min") is not None and (s.get("variable_min") or s.get("variable_max")):
        rows += f"<div class='kv'><span>Mit Zielbonus</span><b>{salary.eur_range(s['ote_min'], s['ote_max'])}</b></div>"
        if s.get("realistic_min") is not None and (s["realistic_min"], s["realistic_max"]) != (s["ote_min"], s["ote_max"]):
            rows += f"<div class='kv'><span>Realistisch</span><b>{salary.eur_range(s['realistic_min'], s['realistic_max'])}</b></div>"
    else:
        rows += "<div class='kv'><span>Variable Vergütung</span><b>unbekannt</b></div>"
    v = s.get("verdict", "unknown")
    trust = html.escape(s.get("origin_label") or "")
    if s.get("confidence_label"):
        trust += " · " + html.escape(s["confidence_label"])
    n = len(s.get("sources") or [])
    if n:
        trust += f" · {n} Quelle{'n' if n != 1 else ''}"
    if s.get("required_tier"):
        trust += f" · Schwelle {_eur(s['required_tier'])} OTE"
    return (f"<div class='block'><div class='bt'>{'Vergütung' if s.get('stated') else 'Gehaltsschätzung'}</div>{rows}"
            f"<div class='verdict v-{v}'>{s.get('symbol', '?')} {html.escape(s.get('label') or '')}</div>"
            f"<div class='state'>{html.escape(s.get('detail') or '')}</div>"
            f"<div class='state'>{trust}</div></div>")


def _salary_details(j: dict) -> str:
    s = (j["evaluation"].get("salary") or {})
    out = ""
    if s.get("rationale"):
        out += f"<div class='facts'><b>Begründung:</b> {html.escape(s['rationale'])}</div>"
    facts = s.get("company_facts") or {}
    bits = []
    if facts.get("employees"):
        bits.append(f"{facts['employees']} Mitarbeitende")
    if facts.get("revenue_eur"):
        bits.append(f"Umsatz {_eur(facts['revenue_eur'])}")
    if facts.get("profitability"):
        bits.append(html.escape(str(facts["profitability"])))
    if facts.get("funding_stage"):
        bits.append(html.escape(str(facts["funding_stage"])))
    if s.get("fix_min") is not None:
        out += "<div class='facts'><b>Arbeitgeber:</b> " + (" · ".join(bits) if bits else "Mitarbeiterzahl, Umsatz und Finanzierung unbekannt") + \
               (f" <span class='sub'>({html.escape(str(facts['note']))})</span>" if facts.get("note") else "") + "</div>"
    if s.get("equity_note"):
        out += f"<div class='facts'><b>Beteiligung (nicht eingerechnet):</b> {html.escape(s['equity_note'])}</div>"
    srcs = s.get("sources") or []
    if srcs:
        items = ""
        for x in srcs:
            label = html.escape(x.get("title") or x.get("url") or "Quelle")
            link = f"<a href='{html.escape(x['url'])}' target='_blank' rel='noopener'>{label}</a>" if x.get("url") else label
            meta = " · ".join(filter(None, [html.escape(str(x.get("date"))) if x.get("date") else "", html.escape(x.get("note") or "")]))
            items += f"<li>{link}{' – ' + meta if meta else ''}</li>"
        out += f"<div class='facts'><b>Quellen:</b><ul class='srcs'>{items}</ul></div>"
    if s.get("researched_at"):
        out += f"<div class='sub'>Schätzung vom {html.escape(str(s['researched_at'])[:10])}</div>"
    return out


def _route_block(j: dict, profile: dict, name: str) -> tuple:
    """Bewerbungsweg block + the primary action + minor actions."""
    p = j["posting"]
    route = register.application_route(j)
    a = application.for_job(j["job_id"])
    st = a["status"] if a else None
    hid_job = _hidden(name, j)
    primary, minor, state = "", "", ""
    if route["mode"] == "email":
        who = html.escape(route.get("name") or route["email"])
        line = f"{html.escape(route['label'])}: {who}"
    elif route["mode"] == "portal":
        line = "Bewerbung läuft über das Portal des Arbeitgebers"
    elif route["mode"] == "general_only":
        line = f"Nur allgemeine Adresse bekannt: {html.escape(route['email'])}"
    else:
        line = "Noch keine Bewerbungsadresse gefunden"
    if j.get("applied_at") and (a is None or st == "sent"):
        state = f"Beworben am {j['applied_at'][:10]}"
    elif st in ("pending_approval", "needs_review"):
        state = "Entwurf wartet auf deine Freigabe" if st == "pending_approval" else "Entwurf braucht deine Durchsicht"
        hid_app = (f"<input type='hidden' name='profile' value='{html.escape(name)}'>"
                   f"<input type='hidden' name='app' value='{html.escape(a['app_id'])}'>")
        primary = ("<form method='POST' action='/application/send'>" + hid_app +
                   "<button class='btn primary' type='submit'>Jetzt senden</button></form>")
        if not application.is_armed():
            state += " · Versand nicht freigeschaltet, „Jetzt senden“ ist ein Testlauf"
    elif st == "drafting":
        state = "Entwurf wird gerade erstellt – Seite in einer Minute neu laden"
        primary = "<button class='btn' disabled>Entwurf wird erstellt…</button>"
    elif st == "failed":
        state = "Entwurf fehlgeschlagen" + (": " + html.escape(a.get("error") or "") if a.get("error") else "")
        primary = ("<form method='POST' action='/apply'>" + hid_job +
                   "<button class='btn primary' type='submit'>Erneut versuchen</button></form>")
    elif p.get("is_open") is False:
        state = "Anzeige geschlossen"
    else:
        why = application.readiness(j)
        docs_missing = [w for w in why if w in ("Lebenslauf fehlt", "Anschreiben fehlt")]
        if not why:
            state = "Noch keine Bewerbung versendet"
            primary = ("<form method='POST' action='/apply'>" + hid_job +
                       "<button class='btn primary' type='submit'>Bewerbung vorbereiten</button></form>")
        elif docs_missing:
            state = ", ".join(docs_missing)
            primary = "<a class='btn primary' href='#unterlagen'>Unterlagen hochladen</a>"
        elif route["mode"] == "general_only":
            if j.get("contact_inquiry_sent_at"):
                state = f"Nach dem Recruiting-Kontakt gefragt am {j['contact_inquiry_sent_at'][:10]} – Antwort unten eintragen"
            else:
                state = "Allgemeine Adresse – nicht für Lebenslauf und Unterlagen gedacht"
                mailto = register.contact_inquiry_mailto(j, profile)
                lang = " (auf Englisch)" if register.posting_language(p) == "en" else ""
                primary = f"<a class='btn primary' href='{html.escape(mailto)}'>Recruiting-Kontakt erfragen{lang}</a>"
                minor += ("<form method='POST' action='/contact-inquiry-sent'>" + hid_job +
                          "<button class='btn quiet' type='submit'>Anfrage als gesendet markieren</button></form>")
        elif route["mode"] == "portal":
            state = "Unterlagen dort hochladen; der Hub verschickt hier keine Mail"
            primary = f"<a class='btn primary' href='{html.escape(route['portal_url'] or p.get('url') or '#')}' target='_blank' rel='noopener'>Im Portal bewerben</a>"
        else:
            state = "Adresse fehlt – im Portal nachsehen oder unten eintragen"
            primary = f"<a class='btn primary' href='{html.escape(p.get('url') or '#')}' target='_blank' rel='noopener'>Anzeige öffnen</a>"
    if route.get("source") and route["mode"] in ("email", "general_only"):
        src = route["source"]
        src_html = (f"<a href='{html.escape(src)}' target='_blank' rel='noopener'>Fundstelle</a>" if str(src).startswith("http") else html.escape(str(src)))
        line += f" <span class='sub'>({src_html})</span>"
    block = f"<div class='block'><div class='bt'>Bewerbungsweg</div><div class='route'>{line}</div><div class='state'>{state}</div></div>"
    return block, primary, minor


def _job(j: dict, profile: dict, name: str, view: str = "neu") -> str:
    p, ev = j["posting"], j["evaluation"]
    fit = ev["fit"]
    tags = ""
    if p.get("synthetic"):
        tags += "<span class='tag warn'>synthetisch</span>"
    if j.get("reposted"):
        tags += "<span class='tag'>neu veröffentlicht</span>"
    if p.get("is_open") is False:
        tags += "<span class='tag warn'>geschlossen</span>"
    hours = p.get("hours_per_week")
    if hours is not None:
        tags += f"<span class='tag'>{hours:g} Std./Woche</span>"
    for f in p.get("risk_flags") or []:
        tags += f"<span class='tag warn'>{html.escape({'scaleup_risk': 'Scale-up-Risiko', 'high_travel': 'viel Reisen', 'long_commute': 'langer Arbeitsweg', 'relocation': 'Umzug', 'probation_risk': 'Probezeit-Risiko'}.get(f, f))}</span>"
    kicker = " · ".join(filter(None, [html.escape(p.get("company") or ""), html.escape(_short_location(p)),
                                       _REMOTE.get(p.get("remote") or "unknown", "")]))
    why = " · ".join(html.escape(w) for w in (p.get("why_relevant") or [])[:3])
    route_block, primary, minor = _route_block(j, profile, name)
    reasons = "".join(f"<li>{html.escape(r)}</li>" for r in ev["reasons"] + ev.get("notes", []))
    details = (f"<div class='facts'><b>Bewertung:</b> {html.escape(_LABEL.get(j['status'], j['status']))}</div><ul>{reasons}</ul>"
               + _salary_details(j) + _contact_details(j) + _forms(j, profile, name)
               + f"<div class='sub' style='margin-top:10px'>Geprüft {html.escape((p.get('verified_at') or '–')[:10])}"
               + (f" · zuerst gesehen {j['first_seen'][:10]}" if j.get("first_seen") else "") + "</div>")
    if view == "archiv":
        if j.get("rejected_at"):
            why_r = dict(register.REJECT_REASONS).get(j.get("rejected_reason") or "", "")
            archive = (f"<span class='sub'>Nicht passend seit {j['rejected_at'][:10]}{' · ' + why_r if why_r else ''}</span>"
                       "<form method='POST' action='/reject'>" + _hidden(name, j) + "<input type='hidden' name='value' value='0'>"
                       "<button class='btn quiet' type='submit'>Wiederherstellen</button></form>")
        elif j.get("archived_at"):
            archive = ("<form method='POST' action='/archive'>" + _hidden(name, j) + "<input type='hidden' name='value' value='0'>"
                       "<button class='btn quiet' type='submit'>Wiederherstellen</button></form>")
        else:
            archive = ""
    elif not j.get("applied_at"):
        opts = "".join(f"<option value='{k}'>{v}</option>" for k, v in register.REJECT_REASONS)
        archive = ("<form class='reject' method='POST' action='/reject'>" + _hidden(name, j) +
                   f"<input type='hidden' name='view' value='{html.escape(view)}'>"
                   f"<select name='reason' aria-label='Grund (optional)'><option value=''>Grund (optional)</option>{opts}</select>"
                   "<button class='btn quiet' type='submit'>Nicht passend</button></form>")
    else:
        archive = ""
    return (
        f"<div class='job' id='{html.escape(j['job_id'])}'>"
        f"<div class='kicker'>{kicker}</div>"
        f"<a class='t' href='{html.escape(p.get('url') or '#')}' target='_blank' rel='noopener'>{html.escape(p.get('title') or '')}</a>"
        f"{tags}"
        f"<div class='fit'><b>{_fit_label(fit, profile)}</b><span>{fit:.0f} / 100</span></div>"
        f"<div class='bar'><i style='width:{max(0, min(100, fit)):.0f}%'></i></div>"
        + (f"<div class='summary'>{html.escape(_summary_of(j))}</div>" if _summary_of(j) else "")
        + (f"<div class='why'>{why}</div>" if why else "")
        + _salary_block(j, profile) + route_block
        + (f"<div class='cta'>{primary}</div>" if primary and view != "archiv" else "")
        + f"<details class='more'{' open' if (application.for_job(j['job_id']) or {}).get('status') == 'needs_review' else ''}>"
          f"<summary>Details &amp; Quellen anzeigen</summary>{details}</details>"
        + f"<div class='minor'>{minor}{archive}</div>"
        + "</div>"
    )


def _summary_of(j: dict) -> str:
    """The 2–3 sentence summary from the ad (research run or Nachrecherche)."""
    return " ".join(((j["posting"].get("summary") or j.get("summary") or "")).split())


def _contact_details(j: dict) -> str:
    cr = j.get("contact_research")
    if not cr:
        return ""
    items = ""
    for c in cr.get("contacts") or []:
        label = html.escape(c.get("name") or "")
        addr = html.escape(c.get("email") or c.get("url") or "")
        kind = html.escape({"recruiting": "Recruiting", "hr": "HR", "agency": "Vermittler", "general": "allgemein", "portal": "Portal"}.get(c.get("kind"), c.get("kind") or ""))
        suit = "für Bewerbungen geeignet" if c.get("suitable_for_application") else "nicht für Unterlagen"
        src = c.get("source_url")
        src_html = f" · <a href='{html.escape(src)}' target='_blank' rel='noopener'>Fundstelle</a>" if src and str(src).startswith("http") else (f" · {html.escape(str(src))}" if src else "")
        found = f" · {html.escape(str(c['found_at'])[:10])}" if c.get("found_at") else ""
        items += f"<li>{label + ' ' if label else ''}{addr} <span class='sub'>({kind}, {suit}{src_html}{found})</span></li>"
    if cr.get("portal_url"):
        items += f"<li><a href='{html.escape(cr['portal_url'])}' target='_blank' rel='noopener'>Bewerbungsportal</a>" + (" <span class='sub'>(Bewerbung nur dort)</span>" if cr.get("portal_only") else "") + "</li>"
    out = "<div class='facts'><b>Kontaktrecherche:</b>"
    if cr.get("confidential"):
        out += " <span class='sub'>vertrauliche Stelle – Arbeitgeber nicht gesichert, Vermittler nutzen</span>"
    out += (f"<ul class='srcs'>{items}</ul>" if items else " <span class='sub'>keine Adresse gefunden</span>")
    if cr.get("note"):
        out += f"<div class='sub'>{html.escape(cr['note'])}</div>"
    if cr.get("researched_at"):
        out += f"<div class='sub'>Recherche vom {html.escape(str(cr['researched_at'])[:10])}</div>"
    return out + "</div>"


def _forms(j: dict, profile: dict, name: str) -> str:
    """Manual corrections (salary from a reply, a contact found elsewhere),
    the salary inquiry, and the application draft – all behind Details."""
    p, ev = j["posting"], j["evaluation"]
    c = ev["comp"]
    out = ""
    mailto = register.inquiry_mailto(j, profile)
    if j.get("inquiry_sent_at"):
        out += f"<div class='sub' style='margin-top:8px'>Gehaltsanfrage gesendet am {j['inquiry_sent_at'][:10]}</div>"
    elif mailto:
        who = html.escape(p.get("contact_name") or p.get("contact_email") or "")
        lang = " (auf Englisch)" if register.posting_language(p) == "en" else ""
        out += (f"<div class='minor' style='margin-top:10px'><a class='btn quiet' href='{html.escape(mailto)}'>Gehalt anfragen bei {who}{lang}</a>"
                "<form method='POST' action='/inquiry-sent'>" + _hidden(name, j) +
                "<button class='btn quiet' type='submit'>Als gesendet markieren</button></form></div>")
    if p.get("is_open") is not False and c.get("basis") == "net_monthly":
        out += (
            "<details class='form'><summary>"
            + ("Stundenlohn korrigieren" if c.get("evidenced") else "Stundenlohn aus Antwort eintragen") +
            "</summary><form method='POST' action='/comp'>" + _hidden(name, j) +
            "<label>Brutto-Stundenlohn<input name='hourly' inputmode='decimal' placeholder='z. B. 22,50' "
            f"value='{'' if not c.get('evidenced') else c['hourly']}' required></label>"
            "<label>Quelle<select name='source'><option value='employer'>Arbeitgeber / HR</option>"
            "<option value='recruiter'>Recruiter</option></select></label>"
            "<label>Notiz (optional)<input name='note' maxlength='300' placeholder='z. B. 30 Tage Urlaub, Jobticket'></label>"
            "<button class='btn' type='submit'>Speichern und neu bewerten</button></form></details>")
    elif p.get("is_open") is not False:
        cur = c if c.get("evidenced") else {}
        val = lambda v: "" if v is None else str(v)
        sel = lambda opt, cur_v: " selected" if opt == cur_v else ""
        realism_cur = cur.get("realism") or "uncertain"
        source_cur = cur.get("source") or "employer"
        out += (
            "<details class='form'><summary>"
            + ("Gehalt korrigieren" if c.get("evidenced") else "Gehalt aus Antwort eintragen (hat Vorrang vor der Schätzung)") +
            "</summary><form method='POST' action='/comp'>" + _hidden(name, j) +
            "<label>Fixgehalt / Jahr<input name='fix' inputmode='decimal' placeholder='z. B. 125000 oder 125k' "
            f"value='{val(cur.get('fix'))}' required></label>"
            "<label>Variable Zielvergütung<input name='variable' inputmode='decimal' placeholder='z. B. 25k' "
            f"value='{val(cur.get('variable'))}'></label>"
            "<label>OTE (leer = Fix + Variabel)<input name='ote' inputmode='decimal' placeholder='optional'></label>"
            "<label>Bonus erreichbar?<select name='realism'>"
            f"<option value='realistic'{sel('realistic', realism_cur)}>realistisch</option>"
            f"<option value='uncertain'{sel('uncertain', realism_cur)}>unsicher</option>"
            f"<option value='unrealistic'{sel('unrealistic', realism_cur)}>unrealistisch</option></select></label>"
            "<label>Quelle<select name='source'>"
            f"<option value='employer'{sel('employer', source_cur)}>Arbeitgeber / HR</option>"
            f"<option value='recruiter'{sel('recruiter', source_cur)}>Recruiter</option></select></label>"
            "<label>Notiz (optional)<input name='note' maxlength='300' placeholder='z. B. Firmenwagen, 30 Tage Urlaub'></label>"
            "<button class='btn' type='submit'>Speichern und neu bewerten</button></form></details>")
    if j.get("manual_comp"):
        out += f"<div class='sub'>Gehalt im Hub eingetragen am {j['manual_comp']['entered_at'][:10]} – gilt vor jeder Schätzung</div>"
    if p.get("is_open") is not False and not j.get("applied_at"):
        route = register.application_route(j)
        cur_mail = route["email"] if route["mode"] in ("email", "general_only") else ""
        out += ("<details class='form'><summary>"
                + ("Bewerbungsadresse ändern" if route["mode"] == "email" else "Bewerbungsadresse eintragen (hat Vorrang vor der Recherche)") +
                "</summary><form method='POST' action='/contact'>" + _hidden(name, j) +
                "<label>Name (optional)<input name='name' maxlength='100' placeholder='z. B. Anna Beispiel'></label>"
                f"<label>E-Mail<input name='email' type='email' required value='{html.escape(cur_mail or '')}' placeholder='name@firma.de'></label>"
                "<div class='sub'>Eine hier eingetragene Adresse gilt als geeignet für Lebenslauf und Unterlagen.</div>"
                "<button class='btn' type='submit'>Adresse speichern</button></form></details>")
    if j.get("manual_contact"):
        out += "<div class='sub'>Adresse im Hub eingetragen – gilt vor jeder Recherche</div>"
    out += _application_block(j, name)
    return out


def _application_block(j: dict, name: str) -> str:
    """The draft (edit / re-tailor / discard) – the send button is the card's
    primary action, so it is not repeated here."""
    a = application.for_job(j["job_id"])
    if a is None or j.get("applied_at") and a["status"] == "sent":
        return ""
    st = a["status"]
    chip = {"pending_approval": "ok", "sent": "ok", "needs_review": "wait", "drafting": "wait"}.get(st, "bad")
    out = f"<div class='row' style='margin-top:12px'><b style='font-size:.9rem'>Bewerbung</b><span class='chip {chip}'>{html.escape(application.status_label(a))}</span></div>"
    if st == "drafting":
        return out + "<span class='sub'>Das lokale Modell passt Anschreiben und Lebenslauf gerade an.</span>"
    if a.get("error"):
        out += f"<div class='sub'>{html.escape(a['error'])}</div>"
    if a.get("guard"):
        out += "<ul>" + "".join(f"<li>{html.escape(g)}</li>" for g in a["guard"]) + "</ul>"
    if st in ("pending_approval", "needs_review"):
        hid = (f"<input type='hidden' name='profile' value='{html.escape(name)}'>"
               f"<input type='hidden' name='app' value='{html.escape(a['app_id'])}'>")
        out += (f"<details class='form'{' open' if st == 'needs_review' else ''}><summary>Entwurf ansehen und bearbeiten"
                f"{' (angepasst)' if a.get('tailored') else ' (Basisanschreiben, nicht angepasst)'}</summary>"
                "<form method='POST' action='/application/update'>" + hid +
                f"<label>Betreff<input name='subject' maxlength='200' value='{html.escape(a['subject'])}'></label>"
                f"<label>Begleittext der E-Mail<textarea name='mail_text' rows='8'>{html.escape(application.mail_text(a))}</textarea></label>"
                f"<label>Anschreiben (geht als PDF-Anhang mit"
                f"{' – <a href=' + chr(39) + '/application/letter?p=' + html.escape(name) + '&app=' + html.escape(a['app_id']) + chr(39) + ' target=' + chr(39) + '_blank' + chr(39) + '>Vorschau</a>' if cv_document.renderer_available() else ''}"
                f")<textarea name='body'>{html.escape(a['body'])}</textarea></label>"
                + _cv_fields(a, name) +
                f"<div class='sub'>an {html.escape(a['to'])}</div>"
                "<button class='btn' type='submit'>Änderungen speichern</button></form></details>")
        out += ("<div class='minor'>"
                "<form method='POST' action='/application/retailor'>" + hid +
                "<button class='btn quiet' type='submit'>Neu anpassen</button></form>"
                "<form method='POST' action='/application/discard'>" + hid +
                "<button class='btn quiet danger' type='submit'>Entwurf verwerfen</button></form></div>")
    return out


def _cv_fields(a: dict, name: str) -> str:
    """The tailored CV inside the draft form: its profile section is
    editable, the rest of the CV is the upload, verbatim."""
    if a.get("cv_profile"):
        out = (f"<label>Profilabschnitt im Lebenslauf (für diese Stelle)<textarea name='cv_profile' style='min-height:180px'>"
               f"{html.escape(a['cv_profile'])}</textarea></label>")
    else:
        out = ""
    if a.get("cv_tailored_file"):
        link = f"/application/cv?p={html.escape(name)}&amp;app={html.escape(a['app_id'])}"
        out += (f"<div class='sub'>Anhang: {html.escape(a.get('cv_tailored_name') or 'Lebenslauf')} (angepasst, übrige Abschnitte wie hochgeladen) · "
                f"<a href='{link}' target='_blank'>PDF ansehen</a></div>")
    else:
        why = a.get("cv_error") or "Lebenslauf nicht angepasst"
        out += f"<div class='sub'>Anhang: {html.escape(a.get('cv_name') or 'Lebenslauf')} (Original) – {html.escape(why)}</div>"
    return out


def _documents_panel(name: str, profile: dict) -> str:
    st = documents.status()
    rows = ""
    for kind, label in documents.KINDS.items():
        m = st.get(kind)
        hid = f"<input type='hidden' name='profile' value='{html.escape(name)}'><input type='hidden' name='kind' value='{kind}'>"
        accept = ".jpg,.jpeg,.png" if kind == "photo" else ".pdf,.docx,.txt,.md"
        if m and kind == "photo":
            info = (f"<span class='chip ok'>vorhanden</span> <span class='sub'>{html.escape(m['filename'])} · "
                    f"{m.get('width', '?')}×{m.get('height', '?')} px · "
                    f"{'aus dem Lebenslauf übernommen' if m.get('source') == 'cv' else 'hochgeladen ' + m['uploaded_at'][:10]}</span>")
        elif m:
            info = (f"<span class='chip ok'>vorhanden</span> <span class='sub'>{html.escape(m['filename'])} · "
                    f"{m['chars']:,} Zeichen · hochgeladen {m['uploaded_at'][:10]}</span>".replace(",", "."))
            rm = ("<form method='POST' action='/document/delete' style='display:inline'>" + hid +
                  "<button class='btn danger' type='submit'>Entfernen</button></form>")
        else:
            info, rm = ("<span class='chip'>optional</span> <span class='sub'>wird sonst aus dem Lebenslauf-PDF übernommen</span>"
                        if kind == "photo" else "<span class='chip wait'>fehlt</span>"), ""
        rows += (f"<div class='panel'><b style='font-size:.9rem'>{label}</b> {info}"
                 "<form method='POST' action='/upload' enctype='multipart/form-data'>" + hid +
                 f"<input type='file' name='file' accept='{accept}' required>"
                 f"<div class='row'><button class='btn' type='submit'>{'Ersetzen' if m else 'Hochladen'}</button>{rm}</div></form></div>")
    ap = profile.get("application") or {}
    auto = bool(ap.get("auto_send"))
    armed = application.is_armed()
    toggle = ("<form method='POST' action='/auto-send'>"
              f"<input type='hidden' name='profile' value='{html.escape(name)}'>"
              f"<button class='btn' type='submit'>Automatischen Versand {'ausschalten' if auto else 'einschalten'}</button></form>")
    mode = ("Nach „Autobewerbung“ wird der Entwurf sofort verschickt, wenn die Prüfung nichts beanstandet."
            if auto else "Nach „Autobewerbung“ wartet der Entwurf hier auf „Jetzt senden“.")
    gate = ("" if armed else " Versand ist derzeit nicht freigeschaltet (JOB_MONITOR_APPLY_ARMED fehlt im Hub-Prozess) – es wird nur ein Testlauf protokolliert.")
    reply = ap.get("reply_to")
    snd = application.sender_status()
    if snd["configured"]:
        sender = f" Absender: {html.escape(snd['address'])}" + (" (eigenes Postfach)." if snd["source"] == "profile" else " (Job Hub-Postfach).")
    else:
        sender = f" Kein Absender eingerichtet – {application.SMTP_FILE} im Profilordner anlegen (MAIL_SMTP_HOST/PORT/USER/PASSWORD)."
    touch = " Eine kleine, bewusst menschliche Unschärfe pro Brief ist eingeschaltet." if application.human_touch_enabled(profile) else ""
    return ("<div class='section'><div class='title'>Bewerbungsunterlagen</div>" + rows +
            f"<div class='panel'><b style='font-size:.9rem'>Autobewerbung</b> <span class='chip {'ok' if auto and armed else 'wait'}'>"
            f"{'automatisch' if auto else 'mit Freigabe'}</span><div class='sub'>{mode}{gate}"
            f"{sender}{' Antworten gehen an ' + html.escape(reply) + '.' if reply else ''}{touch}</div>"
            + toggle + "</div></div>")


def _sources_panel(profile: dict) -> str:
    s = sources.all_sources(profile)
    boards = "".join(f"<li><a href='{html.escape(b['url'])}' target='_blank' rel='noopener'>{html.escape(b['name'])}</a></li>" for b in s["boards"])
    hosts = ", ".join(html.escape(h["name"]) for h in s["career_pages"])
    extra = "".join(f"<li>{html.escape(e['name'])}</li>" for e in s["extra"])
    return ("<div class='section'><details><summary class='title'>Durchsuchte Quellen anzeigen</summary>"
            f"<ol class='src'>{boards}</ol><div class='sub'>Karriereseiten direkt: {hosts}.</div>"
            + (f"<div class='sub'>Zusätzlich für dieses Profil:</div><ul class='src'>{extra}</ul>" if extra else "") +
            "</details></div>")


_FIELD_LABELS = {
    "positioning": "Positionierung", "confirmed.roles": "Bisherige Rollen", "confirmed.leadership": "Führungserfahrung",
    "confirmed.results": "Ergebnisse", "confirmed.target_path": "Zielpfad", "must_criteria.role_families": "Rollenfamilien",
    "must_criteria.growth_mandate_required": "Growth-Mandat Pflicht?", "must_criteria.career_step": "Karriereschritt",
    "must_criteria.locations": "Orte", "preferences.remote": "Remote-Wunsch", "preferences.travel": "Reisebereitschaft",
    "preferences.domains": "Domänen", "compensation.current_fix": "Heutiges Fixgehalt",
    "compensation.current_variable_target": "Heutige variable Zielvergütung", "compensation.current_ote": "Heutiges OTE",
    "compensation.current_variable_typical_paid": "Typisch ausgezahlter Bonus",
    "compensation.current_conservative": "Konservative Vergütung heute", "compensation.fix_floor": "Fix-Untergrenze",
    "compensation.tiers.exceptional_fit": "OTE-Stufe bei außergewöhnlicher Passung",
    "compensation.tiers.standard": "OTE-Stufe Standard", "compensation.tiers.high_risk": "OTE-Stufe bei Risiko",
    "notice_period.months": "Kündigungsfrist (Monate)", "notice_period.end_rule": "Kündigung zum (Monats-/Quartalsende)",
    "contact_signature": "Signatur für Rückfragen",
    "must_criteria.hours_per_week_max": "Maximale Wochenstunden", "compensation.net_monthly_min": "Netto-Ziel pro Monat",
    "compensation.gross_hourly_min": "Mindest-Brutto-Stundensatz (aus Steuerklasse)",
}


def _thresholds(profile: dict) -> str:
    cp, np_, mc = profile["compensation"], profile["notice_period"], profile["must_criteria"]
    common = ("<li>Gehalt aus Anzeige, Recruiter oder vergleichbaren Anzeigen derselben Firma; sonst eine recherchierte "
              "Schätzung mit Quellen – nur bei mittlerer oder hoher Sicherheit für die Vorprüfung genutzt, nie als Zusage. "
              "Die Obergrenze einer Spanne allein erfüllt keine Schwelle.</li>"
              f"<li>Kündigung: vertraglich {np_['months']} Monate"
              + (f", verhandelbar {np_['negotiable_months']} Monate zum Monatsende" if np_.get("negotiable_months") else "") + "</li>")
    if cp.get("basis") == "net_monthly":
        hourly = f"{float(cp['gross_hourly_min']):.2f} €".replace(".", ",")
        return (f"<li>Teilzeit, höchstens {mc['hours_per_week_max']:g} Std./Woche; Stellen ohne Stundenangabe werden geprüft, nicht gemeldet</li>"
                f"<li>Mindestens {_eur(cp['net_monthly_min'])} netto/Monat → Mindestsatz {hourly} brutto/Std.</li>"
                + common +
                f"<li>Passung mindestens {profile['thresholds']['fit_notify']}/100; gleiche Ebene genügt, kein Growth-Mandat nötig</li>")
    return (f"<li>OTE ab {_eur(cp['tiers']['standard'])}; ab {_eur(cp['tiers']['exceptional_fit'])} bei außergewöhnlicher Passung; "
            f"{_eur(cp['tiers']['high_risk'])} bei Risiko (Scale-up, viel Reisen, Umzug, Pendeln)</li>"
            f"<li>Fixgehalt mindestens {_eur(cp['fix_floor'])}</li>"
            f"<li>Heute: {_eur(cp['current_ote'])} OTE, konservativ ~{_eur(cp['current_conservative'])} (Bonus typisch {_eur(cp['current_variable_typical_paid'])} ausgezahlt)</li>"
            + common +
            f"<li>Passung mindestens {profile['thresholds']['fit_notify']}/100; Growth-Mandat und echter Karriereschritt sind Pflicht</li>")


def _view_tabs(name: str, view: str, counts: dict) -> str:
    return "<div class='tabs views'>" + "".join(
        f"<a class='{'on' if k == view else ''}' href='/?p={html.escape(name)}&v={k}'>{label} ({counts.get(k, 0)})</a>"
        for k, label in _VIEWS) + "</div>"


def _in_progress(j: dict) -> bool:
    """A decision is open: a draft waits, or a question went out."""
    a = application.for_job(j["job_id"])
    if a and a["status"] in ("drafting", "pending_approval", "needs_review", "failed"):
        return True
    return bool(j.get("inquiry_sent_at") or j.get("contact_inquiry_sent_at"))


def _undo_banner(name: str, jid: Optional[str], view: str) -> str:
    """Right after "Nicht passend": the job's title and an undo button, no dialog."""
    if not jid:
        return ""
    j = register.state().get(jid)
    if not j or not j.get("rejected_at"):
        return ""
    why = dict(register.REJECT_REASONS).get(j.get("rejected_reason") or "", "")
    return (f"<div class='undo' role='status'><span>„{html.escape(j['posting'].get('title') or '')}“ als nicht passend ins Archiv verschoben"
            f"{' (' + why + ')' if why else ''}.</span>"
            "<form method='POST' action='/reject'>" + _hidden(name, j) + "<input type='hidden' name='value' value='0'>"
            f"<input type='hidden' name='view' value='{html.escape(view)}'>"
            "<button class='btn' type='submit'>Rückgängig</button></form></div>")


def _section(name: str, view: str = "neu", undo: Optional[str] = None) -> str:
    """One person's complete hub block, rendered inside profile_context(name).
    ``view``: neu (new hits), offen (open decisions), beworben (sent),
    archiv (evaluator discards, hand-archived, discarded drafts)."""
    profile = register.load_profile()
    owner = html.escape(profile.get("owner") or name.capitalize())
    paused = profile.get("paused")
    missing = register.missing_fields(profile)
    pause_form = ("<div class='section'><form method='POST' action='/pause'>"
                  f"<input type='hidden' name='profile' value='{html.escape(name)}'>"
                  f"<button class='btn' type='submit'>Monitor {'fortsetzen' if paused else 'pausieren'}</button></form></div>")
    if missing:
        items = "".join(f"<li>{html.escape(_FIELD_LABELS.get(m, m))}</li>" for m in missing)
        return (f"<div class='person' id='{html.escape(name)}'><h2>{owner}</h2>"
                "<div class='sub'>Noch keine Suche möglich.</div>"
                f"<div class='incomplete'><b>Profil unvollständig</b> – {len(missing)} Angaben fehlen:<ul>{items}</ul>"
                "<div class='sub' style='margin-top:8px'>Die Antworten auf die Fragenblöcke (Rollen, Führung, Ergebnisse, "
                "Mission, Zielpfad, Arbeitsbedingungen, Vergütung, Kündigungsfrist) gehören in "
                f"<code>profiles/{html.escape(name)}/profile.json</code>.</div></div>"
                + _documents_panel(name, profile) + _sources_panel(profile) +
                f"{pause_form}</div>")

    jobs = sorted(register.state().values(), key=lambda j: -j["evaluation"]["fit"])
    applied = sorted([j for j in jobs if j.get("applied_at")], key=lambda j: j["applied_at"], reverse=True)
    dropped = [j for j in jobs if not j.get("applied_at") and j["status"] != "DISCARD" and not j.get("archived_at")
               and _last_application_discarded(j["job_id"]) and not _in_progress(j)]
    rejected = sorted([j for j in jobs if j.get("rejected_at") and not j.get("applied_at")], key=lambda j: j["rejected_at"], reverse=True)
    rej_ids = {j["job_id"] for j in rejected}
    dropped = [j for j in dropped if j["job_id"] not in rej_ids]
    archived = [j for j in jobs if j.get("archived_at") and not j.get("applied_at") and j["job_id"] not in rej_ids]
    discarded = [j for j in jobs if j["status"] == "DISCARD" and not j.get("applied_at") and not j.get("archived_at") and j["job_id"] not in rej_ids]
    gone = {j["job_id"] for j in dropped + archived + discarded + applied + rejected}
    open_jobs = [j for j in jobs if j["job_id"] not in gone]
    in_progress = [j for j in open_jobs if _in_progress(j)]
    new = [j for j in open_jobs if not _in_progress(j)]
    counts = {"neu": len(new), "offen": len(in_progress), "beworben": len(applied),
              "archiv": len(discarded) + len(dropped) + len(archived) + len(rejected)}
    view = view if view in dict(_VIEWS) else "neu"
    runs = register.runs(1)
    last = runs[-1] if runs else None
    if last:
        ts = datetime.fromisoformat(last["at"]).strftime("%d.%m. %H:%M")
        run_txt = {"ok": "erfolgreich", "partial": "teilweise", "error": "fehlgeschlagen"}.get(last["status"], last["status"])
        last_html = f"<b>{ts}</b><span>letzter Lauf · {run_txt}</span>"
    else:
        last_html = "<b>–</b><span>noch kein Lauf</span>"
    research_html = _research_panel(name, paused)
    meldebereit = [j for j in new if j["status"] in ("NOTIFY", "NOTIFIED")]

    def _list(title, items, empty="Keine Einträge."):
        body = "".join(_job(j, profile, name, view) for j in items) or f"<div class='empty'>{empty}</div>"
        return f"<div class='section'><div class='title'>{title} ({len(items)})</div>{body}</div>"

    if view == "beworben":
        lists = _list("Beworben", applied, "Noch keine Bewerbung verschickt.")
    elif view == "archiv":
        lists = (_list("Nicht passend", rejected) if rejected else "") + \
                (_list("Archiviert", archived) if archived else "") + \
                (_list("Verworfene Entwürfe", dropped) if dropped else "") + \
                _list("Vom Monitor aussortiert", discarded)
    elif view == "offen":
        lists = _list("In Arbeit", in_progress, "Nichts wartet gerade auf dich.")
    else:
        rest = [j for j in new if j not in meldebereit]
        lists = ((_list("Meldebereit", meldebereit) if meldebereit else "")
                 + _list("Zur Durchsicht" if meldebereit else "Neue Treffer", rest, "Keine neuen Treffer. „Aktuelle Stellen suchen“ startet eine Recherche."))

    open_points = "".join(f"<li>{html.escape(o)}</li>" for o in profile.get("open_points", []))
    settings = ("<details class='settings' id='unterlagen'><summary>Einstellungen &amp; Unterlagen</summary>"
                "<div class='section'><div class='title'>Meldeschwellen</div><ul>" + _thresholds(profile) + "</ul></div>"
                f"<div class='section'><div class='title'>Offene Punkte im Profil</div><ul>{open_points}</ul></div>"
                + _documents_panel(name, profile) + _sources_panel(profile) + pause_form + "</details>")
    return (
        f"<div class='person' id='{html.escape(name)}'><h2>{owner}</h2>"
        "<div class='grid'>"
        f"<div class='kpi'><b>{'Pausiert' if paused else 'Aktiv'}</b><span>Monitor · Mo + Do morgens</span></div>"
        f"<div class='kpi'>{last_html}</div>"
        f"<div class='kpi'><b>{len(new)}</b><span>neue Treffer</span></div>"
        f"<div class='kpi'><b>{len(in_progress)}</b><span>in Arbeit</span></div>"
        "</div>"
        + research_html + _view_tabs(name, view, counts)
        + f"<div class='sub' style='margin-top:8px'>{_VIEW_HINT[view]}</div>" + _undo_banner(name, undo, view) + lists + settings + "</div>"
    )


def _research_panel(name: str, paused: bool) -> str:
    """Two buttons: find new postings, or research salary + application
    route for the known ones; the scheduled Monday/Thursday run is unaffected."""
    st = research.status()
    hid = f"<input type='hidden' name='profile' value='{html.escape(name)}'>"
    if st.get("running"):
        since = datetime.fromisoformat(st["started_at"]).strftime("%H:%M")
        what = research.MODE_LABEL.get(st.get("mode", "search"), "Suche")
        return (f"<div class='note'><b>{html.escape(what)} läuft</b> seit {since} Uhr – dauert meist 10–30 Minuten. "
                "Seite später neu laden.</div>")
    if not st.get("cli"):
        return ("<div class='note'><b>Suche auf Knopfdruck noch nicht eingerichtet.</b> Dafür muss das Claude-Code-"
                "Kommandozeilenprogramm auf dem Mac mini installiert und angemeldet sein "
                "(<code>curl -fsSL https://claude.ai/install.sh | bash</code>, dann <code>claude</code> einmal starten "
                "und anmelden). Bis dahin läuft nur der geplante Lauf Mo + Do morgens.</div>")
    hint = " Monitor ist pausiert – zuerst fortsetzen." if paused else ""
    dis = " disabled" if paused else ""
    return ("<div class='cta' style='margin-top:14px'>"
            "<form method='POST' action='/research'>" + hid + "<input type='hidden' name='mode' value='search'>"
            f"<button class='btn' type='submit'{dis}>Aktuelle Stellen suchen</button></form>"
            "<form method='POST' action='/research'>" + hid + "<input type='hidden' name='mode' value='enrich'>"
            f"<button class='btn' type='submit'{dis}>Gehalt &amp; Kontakte nachrecherchieren</button></form></div>"
            f"<div class='sub'>Beides startet eine Recherche jetzt, unabhängig vom geplanten Lauf.{hint}</div>")


def _last_application_discarded(jid: str) -> bool:
    apps = [a for a in application.state().values() if a.get("job_id") == jid]
    return bool(apps) and sorted(apps, key=lambda a: a["at"])[-1].get("status") == "discarded"


def render_page(selected: Optional[str] = None, view: Optional[str] = None, undo: Optional[str] = None) -> str:
    """One person per page; the tabs switch (``/?p=<name>``), ``view``
    picks Neu / Beworben / Archiv inside the person."""
    names = register.list_profiles()
    if selected not in names:
        selected = names[0] if names else None
    body = ""
    if selected:
        with register.profile_context(selected):
            try:
                body = _section(selected, view or "neu", undo)
            except Exception as e:   # a broken profile must not take the hub down
                body = (f"<div class='person' id='{html.escape(selected)}'><h2>{html.escape(selected.capitalize())}</h2>"
                        f"<div class='incomplete'>Profil konnte nicht geladen werden: {html.escape(type(e).__name__)}</div></div>")
    tabs = ""
    if len(names) > 1:
        tabs = "<div class='tabs'>" + "".join(
            f"<a class='{'on' if n == selected else ''}' href='/?p={html.escape(n)}'>{html.escape(_owner_of(n))}</a>" for n in names) + "</div>"
    note = register.migration_note()
    note_html = ""
    if note and selected == register.LEGACY_PROFILE:
        note_html = (f"<div class='note'>Daten von {html.escape(register.LEGACY_PROFILE.capitalize())} wurden am "
                     f"{html.escape(note.get('at', '')[:10])} nach <code>profiles/{html.escape(register.LEGACY_PROFILE)}/</code> verschoben"
                     + (" (einige Dateien blieben am alten Ort: " + html.escape(", ".join(note["left_in_place"])) + ")"
                        if note.get("left_in_place") else "") + ".</div>")
    return (
        "<!DOCTYPE html><html lang='de'><head><meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='light dark'>"
        f"<title>Job Hub</title><style>{CSS}</style></head><body><div class='wrap'>"
        "<h1>Job Hub</h1>"
        "<div class='sub'>Passung, voraussichtliches Gehalt, Sicherheit der Schätzung und nächster Schritt – pro Stelle auf einen Blick.</div>"
        + tabs + note_html
        + (body or "<div class='note'>Noch kein Profil angelegt.</div>")
        + "</div></body></html>"
    )


def _owner_of(name: str) -> str:
    try:
        with register.profile_context(name):
            return (register.load_profile().get("owner") or name.capitalize()).split()[0]
    except Exception:
        return name.capitalize()
