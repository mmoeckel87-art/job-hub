"""Command line used by the scheduled research task (and by hand).

  python3 -m job_monitor.cli known              # register snapshot for dedup
  python3 -m job_monitor.cli ingest FILE.json   # evaluate + store postings
  python3 -m job_monitor.cli notify             # send pending alerts (desktop), print them
  python3 -m job_monitor.cli run-log --status ok --searched 40 --new 3 --note "..."
  python3 -m job_monitor.cli status | pause | resume
  python3 -m job_monitor.cli profiles            # persons that have a profile directory
  python3 -m job_monitor.cli --profile second init   # create an empty profile template
  python3 -m job_monitor.cli sources             # the source list for the research brief
  python3 -m job_monitor.cli documents           # uploaded CV / cover letter
  python3 -m job_monitor.cli apply JOB_ID [--send]   # Autobewerbung from the command line
  python3 -m job_monitor.cli enrich-targets      # open jobs for the salary/contact Nachrecherche
  python3 -m job_monitor.cli enrich FILE.json    # store researched estimates / application routes

Every command works on one person: `--profile NAME` (before the command) or
the env var JOB_MONITOR_PROFILE; default is demo. Run from repository root/."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from . import application, documents, register, sources, salary


def _desktop_notify(title: str, message: str) -> bool:
    if sys.platform != "darwin" or os.environ.get("JOB_MONITOR_NO_DESKTOP") == "1":
        return False
    script = f'display notification {json.dumps(message)} with title {json.dumps(title)}'
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10, capture_output=True)
        return True
    except Exception:
        return False


def cmd_known(_args) -> None:
    out = [{"job_id": j["job_id"], "company": j["posting"].get("company"), "title": j["posting"].get("title"),
            "urls": j["urls"], "status": "REJECTED" if j.get("rejected_at") else j["status"], "last_seen": j["last_seen"],
            "rejected": bool(j.get("rejected_at")), "applied": bool(j.get("applied_at")),
            "has_summary": bool((j["posting"].get("summary") or "").strip())}
           for j in register.state().values()]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_ingest(args) -> None:
    with open(args.file, encoding="utf-8") as f:
        postings = json.load(f)
    if isinstance(postings, dict):
        postings = [postings]
    profile = register.require_complete(register.load_profile())
    for p in postings:
        # researched salary estimate / application route travel inside the
        # posting but are stored as their own event (they outlive later runs)
        est, cr = p.pop("salary_estimate", None), p.pop("contact_research", None)
        known_before = register.state().get(register.job_id(p)) or {}
        j = register.upsert(p, profile)
        if est or cr:
            j = register.set_enrichment(j["job_id"], salary_estimate=est, contact_research=cr)
        if known_before.get("rejected_at"):
            print(f"REJECTED  {j['evaluation']['fit']:5.1f}  {p.get('company')} – {p.get('title')}  | als nicht passend markiert, bleibt im Archiv")
            continue
        print(f"{j['status']:9} {j['evaluation']['fit']:5.1f}  {p.get('company')} – {p.get('title')}  "
              f"| {'; '.join(j['evaluation']['reasons'])}")


def cmd_enrich(args) -> None:
    """Store researched salary estimates / application routes for known
    jobs: FILE.json = [{"job_id", "salary_estimate": {...}, "contact_research": {...}}]."""
    with open(args.file, encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict):
        items = [items]
    known = register.state()
    for it in items:
        jid = it.get("job_id")
        if jid not in known:
            print(f"unknown   {jid}")
            continue
        j = register.set_enrichment(jid, salary_estimate=it.get("salary_estimate"), contact_research=it.get("contact_research"),
                                    summary=it.get("summary"))
        s = j["evaluation"].get("salary") or {}
        route = register.application_route(j)
        print(f"{j['status']:9} {j['evaluation']['fit']:5.1f}  {j['posting'].get('company')} – {j['posting'].get('title')}  "
              f"| Gehalt {salary.eur_range(s['fix_min'], s['fix_max'])} fix, {s['label']} ({s['origin_label']}, {s['confidence_label'] or 'keine'}) "
              f"| Weg: {route['label']}")


def cmd_enrich_targets(_args) -> None:
    """Open jobs that still need (or may refresh) a salary estimate and an
    application route – the work list for the Nachrecherche run."""
    out = []
    for j in register.state().values():
        p = j["posting"]
        if p.get("is_open") is False or j.get("applied_at") or j.get("archived_at") or j.get("rejected_at") or j["status"] == "DISCARD":
            continue
        s = j["evaluation"].get("salary") or {}     # evaluations stored before the salary block existed
        route = register.application_route(j)
        out.append({"job_id": j["job_id"], "company": p.get("company"), "title": p.get("title"),
                    "location": p.get("location"), "url": p.get("url"), "urls": j["urls"],
                    "company_stage": p.get("company_stage"), "risk_flags": p.get("risk_flags"),
                    "required_tier": s.get("required_tier"),
                    "salary_stated": bool(j["evaluation"]["comp"].get("evidenced")),
                    "salary_origin": s.get("origin"), "salary_confidence": s.get("confidence"),
                    "salary_researched_at": s.get("researched_at"),
                    "has_summary": bool((p.get("summary") or "").strip()),
                    "contact_route": route["mode"], "contact_email": route.get("email"),
                    "contact_researched_at": (j.get("contact_research") or {}).get("researched_at"),
                    "manual_comp": bool(j.get("manual_comp")), "manual_contact": bool(j.get("manual_contact")),
                    "comp_note": (p.get("comp") or {}).get("source_note"), "notes": p.get("notes")})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_notify(_args) -> None:
    profile = register.load_profile()
    if profile.get("paused"):
        print(json.dumps({"paused": True, "alerts": []}))
        return
    if not register.profile_complete(profile):
        print(json.dumps({"paused": True, "incomplete": register.missing_fields(profile), "alerts": []}))
        return
    alerts_dir = os.path.join(register.profile_dir(), "alerts")
    os.makedirs(alerts_dir, exist_ok=True)
    sent = []
    for j in register.pending():
        text = register.format_alert(j)
        with open(os.path.join(alerts_dir, f"{j['job_id']}.md"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        p, c = j["posting"], j["evaluation"]["comp"]
        headline = f"{p.get('title')} | {p.get('company')} | OTE {c['ote']:,} €".replace(",", ".")
        title = f"Jobmonitor ({profile.get('owner') or register.current_profile()}): neuer Treffer"
        channels = ["hub"] + (["desktop"] if _desktop_notify(title, headline) else [])
        register.mark_notified(j["job_id"], channels)
        sent.append({"job_id": j["job_id"], "headline": headline, "channels": channels, "text": text})
    print(json.dumps({"paused": False, "alerts": sent}, ensure_ascii=False, indent=1))


def cmd_run_log(args) -> None:
    register.log_run({"at": datetime.now().isoformat(timespec="seconds"), "status": args.status,
                      "searched": args.searched, "new": args.new, "note": args.note})
    print("ok")


def cmd_status(_args) -> None:
    jobs = register.state().values()
    counts = {}
    for j in jobs:
        counts[j["status"]] = counts.get(j["status"], 0) + 1
    runs = register.runs(1)
    profile = register.load_profile()
    print(json.dumps({"profile": register.current_profile(), "paused": profile.get("paused"),
                      "incomplete": register.missing_fields(profile), "counts": counts,
                      "last_run": runs[-1] if runs else None}, ensure_ascii=False))


def cmd_profiles(_args) -> None:
    out = []
    for name in register.list_profiles():
        with register.profile_context(name):
            p = register.load_profile()
            out.append({"profile": name, "owner": p.get("owner"), "paused": p.get("paused"),
                        "complete": register.profile_complete(p), "jobs": len(register.state())})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_init(args) -> None:
    name = register.current_profile()
    existed = name in register.list_profiles()
    d = register.ensure_profile(name, owner=args.owner)
    print(("exists " if existed else "created ") + d)


def _set_paused(value: bool) -> None:
    profile = register.load_profile()
    profile["paused"] = value
    profile.setdefault("changes", []).append({"date": datetime.now().date().isoformat(),
                                              "change": "Monitor pausiert" if value else "Monitor fortgesetzt"})
    register.save_profile(profile)
    print("paused" if value else "resumed")


def cmd_sources(_args) -> None:
    print(sources.markdown(register.load_profile()))


def cmd_documents(_args) -> None:
    print(json.dumps({"profile": register.current_profile(), **documents.status()}, ensure_ascii=False, indent=1))


def cmd_apply(args) -> None:
    """Draft + tailor for one job; --send sends when JOB_MONITOR_APPLY_ARMED=1."""
    a = application.run_autobewerbung(args.job_id)
    out = {k: a.get(k) for k in ("app_id", "job_id", "status", "to", "subject", "guard", "error", "tailored")}
    if args.send and a["status"] in ("pending_approval", "needs_review"):
        out["send"] = application.send(a["app_id"], dry_run=False)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="job_monitor")
    ap.add_argument("--profile", default=None, help="Person (Verzeichnis unter data/profiles/), Standard: demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("known")
    pi = sub.add_parser("ingest")
    pi.add_argument("file")
    sub.add_parser("notify")
    pr = sub.add_parser("run-log")
    pr.add_argument("--status", required=True, choices=["ok", "partial", "error"])
    pr.add_argument("--searched", type=int, default=0)
    pr.add_argument("--new", type=int, default=0)
    pr.add_argument("--note", default="")
    sub.add_parser("status")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("profiles")
    sub.add_parser("sources")
    sub.add_parser("documents")
    pa = sub.add_parser("apply")
    pa.add_argument("job_id")
    pa.add_argument("--send", action="store_true")
    pe = sub.add_parser("enrich")
    pe.add_argument("file")
    sub.add_parser("enrich-targets")
    pinit = sub.add_parser("init")
    pinit.add_argument("--owner", default=None, help="Anzeigename, Standard: Profilname groß geschrieben")
    args = ap.parse_args(argv)
    if args.profile:
        try:
            register.set_default_profile(args.profile, must_exist=args.cmd != "init")
        except register.ProfileError as e:
            raise SystemExit(str(e))
    {"known": cmd_known, "profiles": cmd_profiles, "init": cmd_init, "ingest": cmd_ingest, "notify": cmd_notify, "run-log": cmd_run_log,
     "sources": cmd_sources, "documents": cmd_documents, "apply": cmd_apply,
     "enrich": cmd_enrich, "enrich-targets": cmd_enrich_targets,
     "status": cmd_status, "pause": lambda a: _set_paused(True), "resume": lambda a: _set_paused(False)}[args.cmd](args)


if __name__ == "__main__":
    main()
