"""Job register: append-only JSONL events, replayed into the current state
per job. One job_id per (company, title, city) so a re-posted ad with a new
URL lands on the same entry instead of a duplicate.

Since the second person (Second User) joined, every person has their own
directory under ``data/profiles/<name>/`` (profile.json, register.jsonl,
runs.jsonl, inbox/, alerts/). The active person comes from
``JOB_MONITOR_PROFILE`` (default ``demo``), the CLI's ``--profile``
option or a ``profile_context()`` block (used by the hub, which renders
all persons on one page and must stay thread-safe)."""

import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from . import contacts, evaluation, salary

# Base directory (env override is used by the tests with a temp dir).
DATA_DIR = os.environ.get("JOB_MONITOR_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")
DEFAULT_PROFILE = "demo"
LEGACY_PROFILE = "demo"          # whose files lived directly in data/ before profiles existed
MIGRATION_NOTE = ".migrated.json"
_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_PER_PROFILE_FILES = ("profile.json", "register.jsonl", "runs.jsonl", "inbox", "alerts")

_default_profile = os.environ.get("JOB_MONITOR_PROFILE") or DEFAULT_PROFILE
_ctx = threading.local()
_migration_lock = threading.Lock()


class ProfileError(ValueError):
    """Unknown profile name or a profile that is not filled in yet."""


def valid_name(name: str) -> bool:
    return bool(name) and _NAME_RE.fullmatch(name) is not None


def set_default_profile(name: str, must_exist: bool = True) -> None:
    """Process-wide default (CLI --profile). Validated against existing dirs
    unless the caller is about to create the profile (``init``)."""
    global _default_profile
    if not valid_name(name):
        raise ProfileError(f"Ungültiger Profilname: {name!r}")
    if must_exist and name not in list_profiles():
        raise ProfileError(f"Unbekanntes Profil: {name!r} (vorhanden: {', '.join(list_profiles()) or 'keins'})")
    _default_profile = name


def current_profile() -> str:
    return getattr(_ctx, "name", None) or _default_profile


class profile_context:
    """``with profile_context("second"): ...`` — thread-local, nestable."""

    def __init__(self, name: str):
        if not valid_name(name):
            raise ProfileError(f"Ungültiger Profilname: {name!r}")
        self.name, self._prev = name, None

    def __enter__(self):
        self._prev = getattr(_ctx, "name", None)
        _ctx.name = self.name
        return self.name

    def __exit__(self, *exc):
        _ctx.name = self._prev


def profile_dir(name: Optional[str] = None) -> str:
    name = name or current_profile()
    if not valid_name(name):
        raise ProfileError(f"Ungültiger Profilname: {name!r}")
    migrate_legacy()
    return os.path.join(PROFILES_DIR, name)


def list_profiles() -> list:
    """Names of all persons that have a profile directory; default first."""
    migrate_legacy()
    try:
        names = [n for n in os.listdir(PROFILES_DIR)
                 if valid_name(n) and os.path.isfile(os.path.join(PROFILES_DIR, n, "profile.json"))]
    except FileNotFoundError:
        return []
    return sorted(names, key=lambda n: (n != DEFAULT_PROFILE, n))


def migrate_legacy() -> Optional[dict]:
    """One-off, idempotent: move the pre-profile files from data/ into
    data/profiles/demo/. Returns the migration note if it has ever run
    (so the hub can show it), None if there was nothing to migrate."""
    with _migration_lock:
        target = os.path.join(PROFILES_DIR, LEGACY_PROFILE)
        note_path = os.path.join(target, MIGRATION_NOTE)
        legacy = [f for f in _PER_PROFILE_FILES if os.path.exists(os.path.join(DATA_DIR, f))]
        if not legacy:
            return migration_note()
        os.makedirs(target, exist_ok=True)
        moved, skipped = [], []
        for f in legacy:
            src_, dst = os.path.join(DATA_DIR, f), os.path.join(target, f)
            if os.path.exists(dst):
                skipped.append(f)      # never overwrite; leave the legacy copy for a human
                continue
            shutil.move(src_, dst)
            moved.append(f)
        note = {"at": datetime.now().isoformat(timespec="seconds"), "from": DATA_DIR, "to": target,
                "moved": moved, "left_in_place": skipped}
        if os.path.exists(note_path):
            try:
                with open(note_path, encoding="utf-8") as fh:
                    note = {**json.load(fh), "repeated_at": note["at"], "moved_later": moved, "left_in_place": skipped}
            except (OSError, ValueError):
                pass
        with open(note_path, "w", encoding="utf-8") as fh:
            json.dump(note, fh, ensure_ascii=False, indent=1)
        return note


def migration_note(name: str = LEGACY_PROFILE) -> Optional[dict]:
    try:
        with open(os.path.join(PROFILES_DIR, name, MIGRATION_NOTE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _p(name: str) -> str:
    return os.path.join(profile_dir(), name)


def load_profile() -> dict:
    with open(_p("profile.json"), encoding="utf-8") as f:
        return json.load(f)


def save_profile(profile: dict) -> None:
    os.makedirs(profile_dir(), exist_ok=True)
    tmp = _p("profile.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _p("profile.json"))


# ── Profile template + completeness ───────────────────────────────────
# Same schema as Demo User' profile.json. Personal values are null (or an
# empty list) until the person answers the question blocks; the non-
# personal mechanics (realisation factors, accepted sources, thresholds)
# are shared defaults.
_PERSONAL_NULL = None


def profile_template(owner: str) -> dict:
    return {
        "version": 1,
        "owner": owner,
        "updated_at": datetime.now().date().isoformat(),
        "positioning": _PERSONAL_NULL,
        "confirmed": {"education": None, "roles": [], "results": [], "leadership": None, "languages": None,
                      "north_star_professional": None, "family_north_star": None, "target_path": None},
        "must_criteria": {"role_families": [], "growth_mandate_required": None, "career_step": None, "levers": [],
                          "full_time": None, "languages": [], "locations": None},
        "preferences": {"remote": None, "travel": None, "company_stage": None, "domains": None, "defence": None},
        "compensation": {
            "current_fix": None, "current_variable_target": None, "current_ote": None,
            "current_variable_typical_paid": None, "current_conservative": None, "previous_year_2025": None,
            "fix_floor": None, "tiers": {"exceptional_fit": None, "standard": None, "high_risk": None},
            "exceptional_fit_score": 85,
            "bonus_realisation_factors": {"realistic": 0.7, "uncertain": 0.35, "unrealistic": 0.0, "unknown": 0.35},
            "accepted_sources": ["employer", "recruiter", "company_extrapolated"],
            "high_risk_flags": ["scaleup_risk", "high_travel", "long_commute", "relocation", "probation_risk"],
            "missing_salary_penalty": 10,
        },
        "notice_period": {"months": None, "end_rule": None, "negotiable_months": None,
                          "negotiable_end_rule": None, "note": None},
        "thresholds": {"fit_notify": 70, "fit_review": 50, "reverify_hours": 48},
        "open_points": ["Profil noch nicht ausgefüllt – Antworten auf die Fragenblöcke fehlen"],
        "changes": [{"date": datetime.now().date().isoformat(), "change": "Profil-Vorlage angelegt (leer)"}],
        "notification": {"channels": ["desktop", "phone_push"], "email": False},
        "application": {"auto_send": False, "reply_to": None, "human_touch": False},
        "extra_sources": [],
        "paused": True,
        "contact_signature": None,
    }


# Fields the evaluation and the hub need before a profile can be used at all.
REQUIRED_FIELDS = (
    "positioning", "confirmed.roles", "confirmed.leadership", "confirmed.results", "confirmed.target_path",
    "must_criteria.role_families", "must_criteria.growth_mandate_required", "must_criteria.career_step",
    "must_criteria.locations", "preferences.remote", "preferences.travel", "preferences.domains",
    "compensation.current_fix", "compensation.current_variable_target", "compensation.current_ote",
    "compensation.current_variable_typical_paid", "compensation.current_conservative", "compensation.fix_floor",
    "compensation.tiers.exceptional_fit", "compensation.tiers.standard", "compensation.tiers.high_risk",
    "notice_period.months", "notice_period.end_rule", "contact_signature",
)


# Part-time search paid per hour (compensation.basis == "net_monthly"):
# the annual-OTE numbers are irrelevant, the hourly floor is essential.
REQUIRED_FIELDS_NET_MONTHLY = tuple(
    f for f in REQUIRED_FIELDS if not f.startswith("compensation.")
) + ("must_criteria.hours_per_week_max", "compensation.net_monthly_min", "compensation.gross_hourly_min")


def required_fields(profile: dict) -> tuple:
    return REQUIRED_FIELDS_NET_MONTHLY if evaluation.comp_basis(profile) == "net_monthly" else REQUIRED_FIELDS


def missing_fields(profile: dict) -> list:
    """Dotted paths of required fields that are still null / empty."""
    out = []
    for path in required_fields(profile):
        v = profile
        for part in path.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v is None or v == [] or v == "":
            out.append(path)
    return out


def profile_complete(profile: dict) -> bool:
    return not missing_fields(profile)


def require_complete(profile: dict) -> dict:
    miss = missing_fields(profile)
    if miss:
        raise ProfileError(f"Profil {profile.get('owner') or current_profile()!r} unvollständig: " + ", ".join(miss))
    return profile


def ensure_profile(name: str, owner: Optional[str] = None) -> str:
    """Create ``profiles/<name>/profile.json`` from the empty template if it
    does not exist yet. Never touches an existing profile. Returns the dir."""
    if not valid_name(name):
        raise ProfileError(f"Ungültiger Profilname: {name!r}")
    d = profile_dir(name)
    path = os.path.join(d, "profile.json")
    if not os.path.exists(path):
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profile_template(owner or name.capitalize()), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    return d


def _append(name: str, record: dict) -> None:
    os.makedirs(profile_dir(), exist_ok=True)
    with open(_p(name), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read(name: str) -> list:
    try:
        with open(_p(name), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\(m/w/d\)|\(w/m/d\)|\(f/m/d\)|\(m/f/d\)|\(all genders?\)|\(gn\)", " ", s)
    s = re.sub(r"\b(gmbh|ag|se|kg|co|inc|ltd|llc)\b", " ", s)
    return re.sub(r"[^a-z0-9äöüß]+", " ", s).strip()


def job_id(posting: dict) -> str:
    city = _norm((posting.get("location") or "").split(",")[0])
    key = f"{_norm(posting.get('company'))}|{_norm(posting.get('title'))}|{city}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def material_hash(posting: dict, ev: dict) -> str:
    """What counts as a 'material change' for a re-notification."""
    c = ev["comp"]
    key = json.dumps([posting.get("title"), c.get("fix"), c.get("ote"), c.get("source"),
                      posting.get("remote"), posting.get("required_start_by")], ensure_ascii=False)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def state() -> dict:
    jobs = {}
    for e in _read("register.jsonl"):
        jid = e["job_id"]
        if e["event"] == "upsert":
            prev = jobs.get(jid, {})
            urls = list(dict.fromkeys(prev.get("urls", []) + [e["posting"].get("url")]))
            jobs[jid] = {**prev, "job_id": jid, "posting": e["posting"], "evaluation": e["evaluation"],
                         "urls": urls, "first_seen": prev.get("first_seen", e["at"]), "last_seen": e["at"],
                         "notifications": prev.get("notifications", [])}
        elif e["event"] == "notified" and jid in jobs:
            jobs[jid]["notifications"].append({"at": e["at"], "hash": e["hash"], "channels": e.get("channels", [])})
        elif e["event"] == "inquiry_sent" and jid in jobs:
            jobs[jid]["inquiry_sent_at"] = e["at"]
        elif e["event"] == "manual_contact" and jid in jobs:
            jobs[jid]["manual_contact"] = e["contact"]
        elif e["event"] == "manual_comp" and jid in jobs:
            jobs[jid]["manual_comp"] = {**e["comp"], "entered_at": e["at"]}
        elif e["event"] == "applied" and jid in jobs:
            jobs[jid]["applied_at"] = e["at"]
            jobs[jid]["application_id"] = e.get("app_id")
        elif e["event"] == "enrich" and jid in jobs:
            # researched salary estimate / application route; each part
            # only replaces what the event carries
            if e.get("salary_estimate") is not None:
                jobs[jid]["salary_estimate"] = e["salary_estimate"]
            if e.get("contact_research") is not None:
                jobs[jid]["contact_research"] = e["contact_research"]
            if e.get("summary"):
                jobs[jid]["summary"] = e["summary"]
            jobs[jid]["enriched_at"] = e["at"]
        elif e["event"] == "archived" and jid in jobs:
            jobs[jid]["archived_at"] = e["at"] if e.get("value", True) else None
        elif e["event"] == "rejected" and jid in jobs:
            # "Nicht passend" in the hub: stays through every later run,
            # undone only by an explicit event with value False
            if e.get("value", True):
                jobs[jid]["rejected_at"] = e["at"]
                jobs[jid]["rejected_reason"] = e.get("reason") or None
            else:
                jobs[jid]["rejected_at"] = None
                jobs[jid]["rejected_reason"] = None
        elif e["event"] == "contact_inquiry_sent" and jid in jobs:
            jobs[jid]["contact_inquiry_sent_at"] = e["at"]
    for j in jobs.values():
        ev = j["evaluation"]
        j["reposted"] = len(j["urls"]) > 1
        last = j["notifications"][-1] if j["notifications"] else None
        if ev["decision"] == evaluation.NOTIFY and last and last["hash"] == material_hash(j["posting"], ev):
            j["status"] = "NOTIFIED"
        else:
            j["status"] = ev["decision"]
    return jobs


def upsert(posting: dict, profile: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    profile = require_complete(profile or load_profile())
    now = now or datetime.now()
    jid = job_id(posting)
    # A salary Demo User entered from an employer reply outlives later
    # research runs that only see the ad without numbers again.
    prev = state().get(jid) or {}
    posting = merge_research(posting, prev, profile)
    ev = evaluation.evaluate(posting, profile, now)
    _append("register.jsonl", {"event": "upsert", "job_id": jid, "at": now.isoformat(timespec="seconds"),
                               "posting": posting, "evaluation": ev})
    return state()[jid]


def merge_research(posting: dict, prev: dict, profile: dict) -> dict:
    """What a research run's posting is completed with before evaluation:
    the hub's manual contact/salary (always win), then the researched
    application route and salary estimate (survive every later run)."""
    posting = dict(posting)
    manual_contact = prev.get("manual_contact")
    cr = contacts.normalize(prev.get("contact_research"))
    if manual_contact and manual_contact.get("contact_email"):
        posting.update(manual_contact)
    elif cr and (not posting.get("contact_email") or posting.get("contact_kind") == "general" or cr.get("portal_only")):
        best = contacts.best_contact(cr)
        if best:
            posting.update({"contact_email": best["email"], "contact_name": best["name"], "contact_kind": best["kind"],
                            "contact_source": best.get("source_url") or "Nachrecherche", "contact_origin": "research"})
    if cr:
        posting["contact_research"] = cr
    manual = prev.get("manual_comp")
    if manual and not evaluation.compensation(posting, profile)["evidenced"]:
        posting["comp"] = {**(posting.get("comp") or {}), **{k: v for k, v in manual.items() if k != "entered_at"}}
    # summary: a Nachrecherche text wins unless a research run brings a
    # genuinely new one; a run without text keeps whatever was there
    incoming = (posting.get("summary") or "").strip()
    earlier = ((prev.get("posting") or {}).get("summary") or "").strip()
    enriched = prev.get("summary")
    if enriched and (not incoming or incoming == earlier):
        posting["summary"] = enriched
    elif not incoming and earlier:
        posting["summary"] = earlier
    est = prev.get("salary_estimate")
    if est is not None:
        posting["salary_estimate"] = est
    elif "salary_estimate" in posting and posting["salary_estimate"] is None:
        del posting["salary_estimate"]
    return posting


def set_enrichment(jid: str, salary_estimate: Optional[dict] = None, contact_research: Optional[dict] = None,
                   now: Optional[datetime] = None, origin: str = "research", summary: Optional[str] = None) -> dict:
    """Store a researched salary estimate and/or application route for a
    known job, then re-evaluate it. Manual hub entries keep priority."""
    j = state()[jid]
    now = now or datetime.now()
    rec = {"event": "enrich", "job_id": jid, "at": now.isoformat(timespec="seconds"), "origin": origin}
    if salary_estimate is not None:
        est = dict(salary_estimate)
        est.setdefault("researched_at", rec["at"])
        rec["salary_estimate"] = est
    if contact_research is not None:
        cr = contacts.normalize(contact_research) or {"contacts": [], "application_mode": "unknown"}
        cr.setdefault("researched_at", rec["at"])
        rec["contact_research"] = cr
    if summary and summary.strip():
        rec["summary"] = clip_summary(summary)
    _append("register.jsonl", rec)
    return upsert(j["posting"], now=now)


SUMMARY_MAX = 520


def clip_summary(text: str) -> str:
    """Whitespace-normalised, at most SUMMARY_MAX characters, cut at a
    sentence end where possible (never mid-word)."""
    t = " ".join((text or "").split())
    if len(t) <= SUMMARY_MAX:
        return t
    cut = t[:SUMMARY_MAX]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= SUMMARY_MAX // 2:
        return cut[:end + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 0 else cut).rstrip(",;:") + " …"


REJECT_REASONS = (("aufgaben", "Aufgaben"), ("gehalt", "Gehalt"), ("standort_reisen", "Standort / Reisen"),
                  ("unternehmen", "Unternehmen"), ("sonstiges", "Sonstiges"))


def set_rejected(jid: str, value: bool = True, reason: Optional[str] = None, now: Optional[datetime] = None) -> None:
    """"Nicht passend" (and its undo). The reason is optional and only
    recorded – it never changes the profile's search criteria."""
    if jid not in state():
        return
    reason = reason if reason in dict(REJECT_REASONS) else None
    _append("register.jsonl", {"event": "rejected", "job_id": jid, "value": bool(value), "reason": reason,
                               "at": (now or datetime.now()).isoformat(timespec="seconds")})


def is_rejected(j: dict) -> bool:
    return bool(j.get("rejected_at"))


def set_archived(jid: str, value: bool = True, now: Optional[datetime] = None) -> None:
    """Hand-archived in the hub (and back again)."""
    if jid in state():
        _append("register.jsonl", {"event": "archived", "job_id": jid, "value": bool(value),
                                   "at": (now or datetime.now()).isoformat(timespec="seconds")})


def mark_contact_inquiry_sent(jid: str, now: Optional[datetime] = None) -> None:
    if jid in state():
        _append("register.jsonl", {"event": "contact_inquiry_sent", "job_id": jid,
                                   "at": (now or datetime.now()).isoformat(timespec="seconds")})


def application_route(j: dict) -> dict:
    """contacts.route() for a register entry (manual contact wins)."""
    return contacts.route(j["posting"], contacts.normalize(j.get("contact_research")), j.get("manual_contact"))


def contact_inquiry_mailto(j: dict, profile: dict) -> Optional[str]:
    """Ask a general address for the recruiting contact (mailto, never sent here)."""
    r = application_route(j)
    if not r["inquiry_needed"] or not r["email"] or j["posting"].get("is_open") is False:
        return None
    return contacts.contact_inquiry_mailto(j["posting"], r["email"], profile, posting_language(j["posting"]))


def mark_notified(jid: str, channels: list, now: Optional[datetime] = None) -> None:
    j = state()[jid]
    _append("register.jsonl", {"event": "notified", "job_id": jid,
                               "at": (now or datetime.now()).isoformat(timespec="seconds"),
                               "hash": material_hash(j["posting"], j["evaluation"]), "channels": channels})


def set_manual_comp(jid: str, comp: dict, now: Optional[datetime] = None) -> dict:
    """Salary from an employer/recruiter answer, entered in the hub. Stored
    as its own event, then the posting is re-evaluated with it."""
    j = state()[jid]
    now = now or datetime.now()
    _append("register.jsonl", {"event": "manual_comp", "job_id": jid,
                               "at": now.isoformat(timespec="seconds"), "comp": comp})
    posting = {**j["posting"], "comp": {**(j["posting"].get("comp") or {}), **comp}}
    return upsert(posting, now=now)


def set_manual_contact(jid: str, name: str, email: str, now: Optional[datetime] = None) -> dict:
    """Contact the person found themselves (portal, LinkedIn, phone call)."""
    j = state()[jid]
    contact = {"contact_name": name or None, "contact_email": email,
               "contact_source": "Im Hub eingetragen"}
    _append("register.jsonl", {"event": "manual_contact", "job_id": jid,
                               "at": (now or datetime.now()).isoformat(timespec="seconds"), "contact": contact})
    return upsert({**j["posting"], **contact}, now=now)


def mark_applied(jid: str, app_id: str, now: Optional[datetime] = None) -> None:
    """An application mail left the house (application.send) — the job
    keeps that mark through every later research run."""
    _append("register.jsonl", {"event": "applied", "job_id": jid, "app_id": app_id,
                               "at": (now or datetime.now()).isoformat(timespec="seconds")})


def mark_inquiry_sent(jid: str, now: Optional[datetime] = None) -> None:
    """Recorded from the hub after the person sent the inquiry themselves."""
    if jid in state():
        _append("register.jsonl", {"event": "inquiry_sent", "job_id": jid,
                                   "at": (now or datetime.now()).isoformat(timespec="seconds")})


def posting_language(p: dict) -> str:
    """'de' or 'en'. The research run sets `language`; otherwise the gender
    suffix of the title is the most reliable tell, default German."""
    lang = (p.get("language") or "").lower()[:2]
    if lang in ("de", "en"):
        return lang
    t = (p.get("title") or "").lower()
    if re.search(r"\((m/f/d|f/m/d|m/f/x|all genders?)\)", t):
        return "en"
    return "de"


def inquiry_mailto(j: dict, profile: dict) -> Optional[str]:
    """Draft salary inquiry as a mailto: link, in the language of the ad.
    Never sent automatically — the person opens it on their phone and decides.
    Mentions nothing about their current pay."""
    p = j["posting"]
    if j["evaluation"]["comp"].get("evidenced") or p.get("is_open") is False or not p.get("contact_email"):
        return None
    name, title, url = p.get("contact_name"), p.get("title"), p.get("url")
    general = p.get("contact_kind") == "general" or not name
    sig = profile.get("contact_signature", "")
    if posting_language(p) == "en":
        subject = f"Question regarding the position {title}"
        greeting = "Dear Hiring Team," if general else f"Dear {name},"
        body = (f"{greeting}\n\nI am interested in the advertised position \u201c{title}\u201d ({url}).\n\n"
                "Before I submit my application: could you let me know the intended compensation range "
                "(base salary and variable target) as well as the working model (remote share, travel)?\n\n"
                f"Thank you and kind regards\n{sig}")
    else:
        subject = f"Frage zur Position {title}"
        greeting = "Sehr geehrte Damen und Herren," if general else f"Guten Tag {name},"
        body = (f"{greeting}\n\nich interessiere mich für die ausgeschriebene Position \u201e{title}\u201c ({url}).\n\n"
                "Bevor ich meine Unterlagen einreiche: Können Sie mir den vorgesehenen Gehaltsrahmen "
                "(Fixgehalt und variable Zielvergütung) sowie das Arbeitsmodell (Remote-Anteil, Reisetätigkeit) "
                f"nennen?\n\nVielen Dank und freundliche Grüße\n{sig}")
    return f"mailto:{quote(p.get('contact_email') or '')}?subject={quote(subject)}&body={quote(body)}"


def pending() -> list:
    return [j for j in state().values() if j["status"] == evaluation.NOTIFY and not j.get("rejected_at")]


def log_run(record: dict) -> None:
    _append("runs.jsonl", record)


def runs(limit: int = 20) -> list:
    return _read("runs.jsonl")[-limit:]


def _eur(v) -> str:
    return "unbekannt" if v is None else f"{v:,.0f} €".replace(",", ".")


def format_alert(j: dict, profile: Optional[dict] = None) -> str:
    """The exact notification format agreed with Demo User."""
    p, ev = j["posting"], j["evaluation"]
    cp = (profile or load_profile())["compensation"]
    c = ev["comp"]
    if c.get("basis") == "net_monthly":
        de = lambda v: f"{float(v):.2f}".replace(".", ",")
        comp_line = (f"Vergütung: {de(c['hourly'])} € brutto/Std. ({c.get('derived_from') or c.get('source')}), "
                     f"≈ {_eur(c['monthly_gross_at_max_hours'])} brutto/Monat bei {c['hours_max']:g} Std./Woche; "
                     f"Mindestsatz {de(cp.get('gross_hourly_min') or 0)} € brutto/Std. "
                     f"für {_eur(cp.get('net_monthly_min'))} netto/Monat.")
    else:
        comp_line = (f"Vergütung: Fix {_eur(c['fix'])}, OTE {_eur(c['ote'])} (Quelle: {c['source']}; {c['source_note']}). "
                     f"Gegenüber {_eur(cp['current_ote'])} OTE: {c.get('ote_delta_eur', 0):+,.0f} € ({c.get('ote_delta_pct', 0):+.1f} %). "
                     f"Konservativ erwartbar {_eur(c['conservative'])} vs. heute ~{_eur(cp['current_conservative'])} "
                     f"({c.get('conservative_delta_eur', 0):+,.0f} €, {c.get('conservative_delta_pct', 0):+.1f} %).").replace(",", ".")
    hours = p.get("hours_per_week")
    lines = [
        f"{p.get('title')} | {p.get('company')} | {p.get('url')}",
        "",
        "Warum relevant:",
        *[f"- {r}" for r in (p.get("why_relevant") or [])[:3]],
        "",
        f"Karrierefortschritt: {p.get('career_progress') or 'nicht beschrieben'}",
        "",
        comp_line,
    ]
    if c.get("source") == "company_extrapolated":
        lines.append("Achtung: Gehalt aus anderen Anzeigen derselben Firma abgeleitet: "
                     + ", ".join(x.get("url", "") for x in c.get("extrapolated_from", [])))
    if c.get("equity_note"):
        lines.append(f"Equity (nicht eingerechnet): {c['equity_note']}")
    if c.get("benefits_note"):
        lines.append(f"Zusatzleistungen: {c['benefits_note']}")
    travel = p.get("travel_pct")
    lines += [
        "",
        f"Arbeitsbedingungen: {p.get('location')}, Remote: {p.get('remote')}, Reisen: {str(travel) + ' %' if travel is not None else 'unbekannt'}"
        + (f", Wochenstunden: {hours:g}" if hours is not None else ""),
        "",
        (f"Verfügbarkeit: frühester Eintritt bei Kündigung heute {ev['earliest_start'].get('negotiated')} mit verhandelter Frist, "
         f"vertraglich {ev['earliest_start']['month_end']} (Monatsende) bzw. {ev['earliest_start']['quarter_end']} (Quartalsende). "
         f"Startfrist der Stelle: {p.get('required_start_by') or 'nicht genannt – im Gespräch klären'}."
         + ("".join(" " + n + "." for n in ev.get("notes", [])))),
        "",
        f"Vision und Mission: {p.get('mission_link') or 'keine konkrete Verbindung belegt'}",
        "",
        f"Offene Punkte und Empfehlung: {p.get('open_points') or '–'} → {p.get('recommendation') or '–'}",
    ]
    if p.get("synthetic"):
        lines.insert(0, "[SYNTHETISCHER TESTDATENSATZ – keine echte Stelle]")
    return "\n".join(lines)
