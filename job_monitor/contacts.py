"""Where an application goes: the researched application route of a posting.

The research run looks, in this order, at the original ad / official
portal, the company's career page and public recruiting or HR contacts,
other current postings of the same company (same legal entity / region),
and finally the general contact address on the official website. Every
address keeps its source and finding date. Nothing is guessed from name
patterns; a confidential posting is not pinned on an employer an
aggregator merely hints at — the agency is the contact then.

  kind         recruiting | hr | agency | general | portal
  suitable     may receive CV and personal documents (recruiting/hr/agency,
               or anything the person confirmed in the hub)
  mode         email | portal | agency | general_only | unknown

A general address is a way to reach the company, not a recipient for the
CV: the hub then offers a short inquiry for the responsible recruiting
contact instead of an application. Portal-only employers get the portal
link and no mail application.
"""

import re
from typing import Optional
from urllib.parse import quote

KINDS = ("recruiting", "hr", "agency", "general", "portal")
KIND_LABEL = {"recruiting": "Recruiting-Kontakt", "hr": "HR-Kontakt", "agency": "Personalberatung / Vermittler",
              "general": "Allgemeine Adresse", "portal": "Bewerbungsportal"}
MODE_LABEL = {"email": "Bewerbung per E-Mail möglich", "portal": "Bewerbung nur über das Portal",
              "agency": "Bewerbung über den Vermittler", "general_only": "Nur allgemeine Adresse gefunden",
              "unknown": "Bewerbungsweg noch unbekannt"}
_EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[a-zA-Z]{2,}$")
_SUITABLE_KINDS = ("recruiting", "hr", "agency")


def valid_email(s: str) -> bool:
    return bool(s) and _EMAIL.match(s.strip()) is not None


def normalize(cr: Optional[dict]) -> Optional[dict]:
    """Clean a contact-research dict from the research run or the hub."""
    if not cr:
        return None
    contacts = []
    for c in cr.get("contacts") or []:
        if not isinstance(c, dict):
            continue
        email = (c.get("email") or "").strip()
        kind = c.get("kind") if c.get("kind") in KINDS else ("portal" if c.get("url") and not email else "general")
        if email and not valid_email(email):
            continue
        if not email and not c.get("url"):
            continue
        suitable = c.get("suitable_for_application")
        if suitable is None:
            suitable = kind in _SUITABLE_KINDS
        contacts.append({
            "email": email or None, "name": (c.get("name") or "").strip() or None, "kind": kind,
            "url": c.get("url"), "source_url": c.get("source_url") or c.get("source"),
            "found_at": c.get("found_at"), "suitable_for_application": bool(suitable),
            "company_match": c.get("company_match", True) is not False,
            "note": (c.get("note") or "").strip(),
        })
    portal_url = (cr.get("portal_url") or "").strip() or None
    portal_only = bool(cr.get("portal_only"))
    confidential = bool(cr.get("confidential"))
    mode = cr.get("application_mode") if cr.get("application_mode") in MODE_LABEL else None
    if mode is None:
        if portal_only:
            mode = "portal"
        elif confidential and any(c["kind"] == "agency" for c in contacts):
            mode = "agency"
        elif any(c["email"] and c["suitable_for_application"] and c["company_match"] for c in contacts):
            mode = "email"
        elif any(c["email"] for c in contacts):
            mode = "general_only"
        elif portal_url:
            mode = "portal"
        else:
            mode = "unknown"
    return {"researched_at": cr.get("researched_at"), "application_mode": mode, "portal_url": portal_url,
            "portal_only": portal_only, "confidential": confidential, "contacts": contacts,
            "note": (cr.get("note") or "").strip()}


def best_contact(cr: Optional[dict]) -> Optional[dict]:
    """The address an application may go to, or None. A general address is
    never returned here (see general_contact)."""
    if not cr or cr.get("portal_only"):
        return None
    order = {"recruiting": 0, "hr": 1, "agency": 2}
    cands = [c for c in cr["contacts"] if c["email"] and c["suitable_for_application"] and c["company_match"]
             and c["kind"] in order]
    if cr.get("confidential"):
        cands = [c for c in cands if c["kind"] == "agency"] or cands
    cands.sort(key=lambda c: order[c["kind"]])
    return cands[0] if cands else None


def general_contact(cr: Optional[dict]) -> Optional[dict]:
    if not cr:
        return None
    for c in cr["contacts"]:
        if c["email"] and c["kind"] == "general":
            return c
    return None


def route(posting: dict, cr: Optional[dict], manual: Optional[dict] = None) -> dict:
    """The application route of a job for the card and the readiness check.

    manual = the contact entered in the hub (wins over everything).
    Returns {mode, label, email, name, kind, portal_url, source, inquiry_needed}."""
    if manual and manual.get("contact_email"):
        return {"mode": "email", "label": "Adresse im Hub eingetragen", "email": manual["contact_email"],
                "name": manual.get("contact_name"), "kind": "manual", "portal_url": None,
                "source": manual.get("contact_source") or "Im Hub eingetragen", "inquiry_needed": False}
    ad_email = (posting.get("contact_email") or "").strip() or None
    ad_kind = posting.get("contact_kind")
    if ad_email and ad_kind != "general" and not (cr and cr.get("portal_only")):
        researched = posting.get("contact_origin") == "research"
        return {"mode": "email", "label": (KIND_LABEL.get(ad_kind, "Kontakt") + " recherchiert") if researched else "Adresse aus der Anzeige",
                "email": ad_email,
                "name": posting.get("contact_name"), "kind": ad_kind or "recruiting", "portal_url": None,
                "source": posting.get("contact_source") or posting.get("url"), "inquiry_needed": False}
    best = best_contact(cr)
    if best:
        return {"mode": "email", "label": KIND_LABEL[best["kind"]] + " recherchiert", "email": best["email"],
                "name": best["name"], "kind": best["kind"], "portal_url": None,
                "source": best.get("source_url"), "inquiry_needed": False}
    if cr and cr["application_mode"] == "portal" or (cr and cr.get("portal_only")):
        return {"mode": "portal", "label": MODE_LABEL["portal"], "email": None, "name": None, "kind": "portal",
                "portal_url": cr.get("portal_url") or posting.get("url"), "source": cr.get("portal_url"),
                "inquiry_needed": False}
    general = general_contact(cr) or ({"email": ad_email, "name": posting.get("contact_name"),
                                       "source_url": posting.get("contact_source")} if ad_email else None)
    if general:
        return {"mode": "general_only", "label": MODE_LABEL["general_only"], "email": general["email"],
                "name": general.get("name"), "kind": "general", "portal_url": (cr or {}).get("portal_url"),
                "source": general.get("source_url"), "inquiry_needed": True}
    if cr and cr.get("portal_url"):
        return {"mode": "portal", "label": MODE_LABEL["portal"], "email": None, "name": None, "kind": "portal",
                "portal_url": cr["portal_url"], "source": cr["portal_url"], "inquiry_needed": False}
    return {"mode": "unknown", "label": MODE_LABEL["unknown"], "email": None, "name": None, "kind": None,
            "portal_url": None, "source": None, "inquiry_needed": False}


def contact_inquiry_mailto(posting: dict, email: str, profile: dict, language: str) -> str:
    """A short mail to a general address asking for the responsible
    recruiting contact. Never sent by the hub – the person opens it."""
    title, url = posting.get("title") or "", posting.get("url") or ""
    sig = profile.get("contact_signature", "")
    if language == "en":
        subject = f"Application for {title} – contact person?"
        body = (f"Dear Sir or Madam,\n\nI would like to apply for the advertised position “{title}” ({url}).\n\n"
                "Could you let me know who is responsible for this position in recruiting, and to which address "
                "I may send my application documents?\n\nThank you and kind regards\n{sig}").format(sig=sig)
    else:
        subject = f"Bewerbung als {title} – Ansprechpartner?"
        body = (f"Sehr geehrte Damen und Herren,\n\nich möchte mich auf die ausgeschriebene Position „{title}“ ({url}) bewerben.\n\n"
                "Könnten Sie mir mitteilen, wer im Recruiting für diese Stelle zuständig ist und an welche Adresse "
                f"ich meine Unterlagen senden darf?\n\nVielen Dank und freundliche Grüße\n{sig}")
    return f"mailto:{quote(email)}?subject={quote(subject)}&body={quote(body)}"
