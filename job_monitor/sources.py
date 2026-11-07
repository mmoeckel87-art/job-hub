"""Canonical job sources the research task must scan on every run.

One list for every person (the ten largest German-language boards plus the
career-page hosts most employers publish on). A profile may add its own
boards under ``extra_sources`` (list of ``{"name", "site", "note"}``) –
Demo User' theme boards live there, Second User has none yet.

The list is rendered into the research briefs (``cli sources``) and into
the hub, so the brief, the hub and the code never drift apart."""

from typing import Optional

# Rank, name, public URL, site: filter for WebSearch, note for the researcher.
SOURCES = [
    {"rank": 1, "name": "StepStone", "url": "https://www.stepstone.de", "site": "site:stepstone.de",
     "note": "größte Börse für Fach- und Führungskräfte; Detailseiten offen"},
    {"rank": 2, "name": "Indeed", "url": "https://de.indeed.com", "site": "site:de.indeed.com",
     "note": "Aggregator mit Originalanzeigen; immer zur Firmenseite durchklicken"},
    {"rank": 3, "name": "LinkedIn Jobs", "url": "https://www.linkedin.com/jobs", "site": "site:linkedin.com/jobs",
     "note": "öffentliche Ansicht ohne Login nutzen; Gehalt nur, wenn der Arbeitgeber es nennt"},
    {"rank": 4, "name": "XING Jobs", "url": "https://www.xing.com/jobs", "site": "site:xing.com/jobs",
     "note": "stark im DACH-Mittelstand; Gehaltsschätzungen von XING zählen nicht"},
    {"rank": 5, "name": "Bundesagentur für Arbeit – Jobsuche", "url": "https://www.arbeitsagentur.de/jobsuche",
     "site": "site:arbeitsagentur.de/jobsuche", "note": "größter Bestand, Teilzeit-Filter; öffentlicher Dienst gut abgedeckt"},
    {"rank": 6, "name": "Glassdoor Jobs", "url": "https://www.glassdoor.de/Job", "site": "site:glassdoor.de/Job",
     "note": "nur die Anzeige zählt; Gehaltsschätzungen von Glassdoor nie übernehmen"},
    {"rank": 7, "name": "kimeta", "url": "https://www.kimeta.de", "site": "site:kimeta.de",
     "note": "Aggregator, findet Karriereseiten kleinerer Firmen"},
    {"rank": 8, "name": "Monster", "url": "https://www.monster.de", "site": "site:monster.de",
     "note": "Börse mit offenen Detailseiten"},
    {"rank": 9, "name": "Jobware", "url": "https://www.jobware.de", "site": "site:jobware.de",
     "note": "Fach- und Führungskräfte, Industrie und Technik"},
    {"rank": 10, "name": "stellenanzeigen.de", "url": "https://www.stellenanzeigen.de", "site": "site:stellenanzeigen.de",
     "note": "regionale Arbeitgeber, Mittelstand"},
]

# Employer career pages run on a handful of applicant-tracking hosts; a
# site: search there finds the original ad directly.
CAREER_PAGE_HOSTS = [
    {"name": "Personio", "site": "site:jobs.personio.de"},
    {"name": "Greenhouse", "site": "site:boards.greenhouse.io"},
    {"name": "Lever", "site": "site:jobs.lever.co"},
    {"name": "Workday", "site": "site:myworkdayjobs.com"},
    {"name": "SmartRecruiters", "site": "site:smartrecruiters.com"},
    {"name": "join.com", "site": "site:join.com"},
    {"name": "Ashby", "site": "site:jobs.ashbyhq.com"},
    {"name": "Recruitee", "site": "site:recruitee.com"},
    {"name": "softgarden", "site": "site:softgarden.io"},
]


def extra_sources(profile: Optional[dict]) -> list:
    out = []
    for s in (profile or {}).get("extra_sources") or []:
        if isinstance(s, dict) and s.get("site"):
            out.append({"name": s.get("name") or s["site"], "site": s["site"], "note": s.get("note") or ""})
    return out


def all_sources(profile: Optional[dict] = None) -> dict:
    return {"boards": list(SOURCES), "career_pages": list(CAREER_PAGE_HOSTS), "extra": extra_sources(profile)}


def site_filters(profile: Optional[dict] = None) -> list:
    """Every site: filter the researcher must rotate through."""
    s = all_sources(profile)
    return [x["site"] for x in s["boards"] + s["career_pages"] + s["extra"]]


def markdown(profile: Optional[dict] = None) -> str:
    """The source block for a research brief (same text for every person)."""
    s = all_sources(profile)
    lines = ["Quellen (jede Börse in jedem Lauf mindestens einmal, nicht nur die Websuche):"]
    for b in s["boards"]:
        lines.append(f"   {b['rank']}. {b['name']} – `{b['site']}` ({b['note']})")
    lines.append("   Karriereseiten direkt: " + ", ".join(f"`{h['site']}`" for h in s["career_pages"]))
    if s["extra"]:
        lines.append("   Zusätzlich für dieses Profil: " + ", ".join(
            f"{e['name']} `{e['site']}`" + (f" ({e['note']})" if e["note"] else "") for e in s["extra"]))
    lines.append("   Aggregator-Links sind oft tot – immer die Originalanzeige öffnen und daraus zitieren.")
    return "\n".join(lines)
