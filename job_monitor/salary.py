"""Salary estimate and threshold verdict for a posting.

A posting rarely states its pay. The research run (or the hub's
"Nachrecherche") collects an *estimate* with sources; this module turns it
into ranges the hub shows and a verdict against the person's thresholds.
Everything is deterministic — no number is invented here, only combined:

  origin      employer  (the ad or a recruiter states it)
              derived   (comparable postings / salary data of the same company)
              estimated (market comparison; the weakest kind)
  confidence  high | medium | low  — low is shown but never used to pre-screen
  verdict     met      "Schwelle voraussichtlich erfüllt"  (lower bounds clear it)
              overlap  "Spanne überschneidet Schwelle – Klärung nötig"
              below    "voraussichtlich darunter"          (upper bound misses it)
              unknown  no usable figure

An estimate's upper bound alone never counts as "met": the fix range's lower
end must reach fix_floor and the OTE range's lower end the required tier.
A target bonus is not a guaranteed payout: the "realistic" range applies the
profile's realisation factor to the variable part.
"""

from datetime import datetime
from typing import Optional

ORIGINS = ("employer", "derived", "estimated")
CONFIDENCES = ("high", "medium", "low")
VERDICTS = ("met", "overlap", "below", "unknown")

ORIGIN_LABEL = {"employer": "vom Arbeitgeber angegeben", "derived": "aus Vergleichsdaten abgeleitet",
                "estimated": "geschätzt"}
CONFIDENCE_LABEL = {"high": "hohe Sicherheit", "medium": "mittlere Sicherheit", "low": "geringe Sicherheit"}
VERDICT_LABEL = {"met": "Schwelle voraussichtlich erfüllt",
                 "overlap": "Spanne überschneidet Schwelle – Klärung nötig",
                 "below": "Voraussichtlich unter der Schwelle",
                 "unknown": "Gehalt noch nicht einschätzbar"}
VERDICT_SYMBOL = {"met": "●", "overlap": "◐", "below": "○", "unknown": "?"}
# confidence that is good enough to use the estimate for pre-screening
USABLE = ("high", "medium")

_INT_FIELDS = ("fix_min", "fix_max", "variable_min", "variable_max", "ote_min", "ote_max")


def _int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _ordered(lo, hi):
    if lo is None and hi is None:
        return None, None
    if lo is None:
        return hi, hi
    if hi is None:
        return lo, lo
    return (lo, hi) if lo <= hi else (hi, lo)


def from_comp(comp: dict) -> Optional[dict]:
    """An estimate-shaped view of a stated salary (evaluation.compensation
    output) so cards and verdicts have one shape. None without a fix."""
    if comp.get("fix") is None or comp.get("basis") == "net_monthly":
        return None
    src = comp.get("source")
    origin = "derived" if src == "company_extrapolated" else ("employer" if src in ("employer", "recruiter") else "estimated")
    fix = int(comp["fix"])
    var = comp.get("variable")
    ote = comp.get("ote")
    return {
        "origin": origin,
        "confidence": "high" if origin == "employer" else "medium",
        "fix_min": fix, "fix_max": fix,
        "variable_min": var, "variable_max": var,
        "ote_min": ote, "ote_max": ote,
        "bonus_realism": comp.get("realism") or "unknown",
        "rationale": comp.get("source_note") or "",
        "sources": [{"url": x.get("url"), "title": x.get("title"), "note": x.get("range"), "kind": "company_posting"}
                    for x in (comp.get("extrapolated_from") or [])],
        "company_facts": {},
        "equity_note": comp.get("equity_note") or "",
        "stated": True,
    }


def normalize(est: Optional[dict], profile: dict) -> Optional[dict]:
    """Clean an estimate dict (from research or the hub) and add the
    realistic range. Returns None when there is no fix figure at all."""
    if not est:
        return None
    out = {k: _int(est.get(k)) for k in _INT_FIELDS}
    out["fix_min"], out["fix_max"] = _ordered(out["fix_min"], out["fix_max"])
    out["variable_min"], out["variable_max"] = _ordered(out["variable_min"], out["variable_max"])
    out["ote_min"], out["ote_max"] = _ordered(out["ote_min"], out["ote_max"])
    if out["fix_min"] is None:
        return None
    # OTE from fix + variable when the research gave only the parts
    if out["ote_min"] is None and out["variable_min"] is not None:
        out["ote_min"] = out["fix_min"] + out["variable_min"]
        out["ote_max"] = out["fix_max"] + (out["variable_max"] if out["variable_max"] is not None else out["variable_min"])
    if out["variable_min"] is None and out["ote_min"] is not None:
        out["variable_min"] = max(0, out["ote_min"] - out["fix_min"])
        out["variable_max"] = max(0, out["ote_max"] - out["fix_max"])
    origin = est.get("origin") if est.get("origin") in ORIGINS else "estimated"
    confidence = est.get("confidence") if est.get("confidence") in CONFIDENCES else "low"
    realism = est.get("bonus_realism") if est.get("bonus_realism") in ("realistic", "uncertain", "unrealistic", "unknown") else "uncertain"
    factors = (profile.get("compensation") or {}).get("bonus_realisation_factors") or {}
    f = factors.get(realism, 0.35)
    out["realistic_min"] = round(out["fix_min"] + (out["variable_min"] or 0) * f)
    out["realistic_max"] = round(out["fix_max"] + (out["variable_max"] or 0) * f)
    sources = []
    for s in est.get("sources") or []:
        if isinstance(s, dict) and (s.get("url") or s.get("title") or s.get("note")):
            sources.append({"url": s.get("url"), "title": s.get("title"), "date": s.get("date"),
                            "note": s.get("note"), "kind": s.get("kind") or "market"})
    facts = est.get("company_facts") if isinstance(est.get("company_facts"), dict) else {}
    out.update({
        "origin": origin, "confidence": confidence, "bonus_realism": realism, "realisation_factor": f,
        "rationale": (est.get("rationale") or "").strip(),
        "sources": sources,
        "company_facts": {k: facts.get(k) for k in ("employees", "revenue_eur", "profitability", "funding_stage", "source", "note")},
        "equity_note": (est.get("equity_note") or "").strip(),
        "researched_at": est.get("researched_at"),
        "stated": bool(est.get("stated")),
        "usable": confidence in USABLE,
    })
    return out


def verdict(est: Optional[dict], profile: dict, tier: Optional[int]) -> dict:
    """Compare the ranges with fix_floor and the required OTE tier. ``tier``
    comes from evaluation.required_tier (risk flags / exceptional fit)."""
    cp = profile.get("compensation") or {}
    if not est or est.get("fix_min") is None:
        return {"verdict": "unknown", "label": VERDICT_LABEL["unknown"], "symbol": VERDICT_SYMBOL["unknown"],
                "detail": "Keine Gehaltsangabe und noch keine belastbare Schätzung.", "fix": "unknown", "ote": "unknown"}
    floor = cp.get("fix_floor")
    minimum = (cp.get("tiers") or {}).get("exceptional_fit")   # absolute OTE minimum
    fix_lo, fix_hi = est["fix_min"], est["fix_max"]
    ote_lo = est["ote_min"] if est.get("ote_min") is not None else fix_lo
    ote_hi = est["ote_max"] if est.get("ote_max") is not None else fix_hi
    bonus_known = est.get("ote_min") is not None

    def _cmp(lo, hi, need):
        if need is None:
            return "ok"
        if lo >= need:
            return "ok"
        if hi < need:
            return "below"
        return "overlap"

    fix_v = _cmp(fix_lo, fix_hi, floor)
    ote_v = _cmp(ote_lo, ote_hi, tier)
    if not bonus_known and ote_v == "below":
        ote_v = "overlap"      # the unknown bonus may still close the gap – nothing is proven
    if minimum is not None and ote_hi < minimum and bonus_known:
        ote_v = "below"
    if fix_v == "below" or ote_v == "below":
        v = "below"
    elif fix_v == "ok" and ote_v == "ok":
        v = "met"
    else:
        v = "overlap"
    parts = []
    if floor is not None:
        parts.append({"ok": "Fixgehalt-Untergrenze passt.", "overlap": "Fixgehalt-Spanne reicht nur im oberen Teil über die Untergrenze.",
                      "below": f"Fixgehalt voraussichtlich unter {floor:,} €.".replace(",", ".")}[fix_v])
    if tier is not None:
        if not bonus_known:
            parts.append("Variable Vergütung unbekannt – OTE-Stufe nicht prüfbar." if ote_v != "ok" else "Fix allein erreicht die OTE-Stufe.")
        else:
            parts.append({"ok": "OTE-Stufe erreicht.", "overlap": "Bonus noch zu klären.",
                          "below": f"Gesamtvergütung voraussichtlich unter {tier:,} €.".replace(",", ".")}[ote_v])
    if v == "met" and not est.get("stated"):
        parts.append("Eine Schätzung ist keine Arbeitgeberzusage.")
    return {"verdict": v, "label": VERDICT_LABEL[v], "symbol": VERDICT_SYMBOL[v], "detail": " ".join(parts),
            "fix": fix_v, "ote": ote_v}


def summary(est: Optional[dict], profile: dict, tier: Optional[int]) -> dict:
    """What evaluation stores as ``salary`` and the card renders."""
    v = verdict(est, profile, tier)
    out = {"origin": None, "origin_label": "keine Angabe", "confidence": None, "confidence_label": "",
           "fix_min": None, "fix_max": None, "variable_min": None, "variable_max": None,
           "ote_min": None, "ote_max": None, "realistic_min": None, "realistic_max": None,
           "sources": [], "rationale": "", "company_facts": {}, "equity_note": "", "usable": False,
           "stated": False, "researched_at": None, "required_tier": tier, **v}
    if est:
        out.update({k: est.get(k) for k in ("origin", "confidence", "fix_min", "fix_max", "variable_min", "variable_max",
                                             "ote_min", "ote_max", "realistic_min", "realistic_max", "sources",
                                             "rationale", "company_facts", "equity_note", "usable", "stated",
                                             "researched_at", "bonus_realism")})
        out["origin_label"] = ORIGIN_LABEL.get(est["origin"], "geschätzt")
        out["confidence_label"] = CONFIDENCE_LABEL.get(est["confidence"], "")
    return out


def eur_range(lo, hi) -> str:
    if lo is None:
        return "unbekannt"
    f = lambda v: f"{int(v):,} €".replace(",", ".")
    return f(lo) if hi is None or hi == lo else f"{f(lo)[:-2]}–{f(hi)}"


def new_estimate(**fields) -> dict:
    """Helper for the CLI/tests: an estimate dict with a timestamp."""
    return {"researched_at": datetime.now().isoformat(timespec="seconds"), **fields}
