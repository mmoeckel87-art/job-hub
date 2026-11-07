"""Deterministic job evaluation: must-criteria first, then fit score, then
compensation. The research step (a scheduled Claude task) only collects
facts with evidence into a posting dict; every notify/review/discard
decision is made here, in plain Python, so the same posting always gets
the same verdict and a high fit score can never outweigh a broken
must-criterion.

Decisions: NOTIFY | REVIEW | DISCARD (plus NOTIFIED for an unchanged
posting that was already reported).

Rules are read from the profile; every default equals the original
(executive, annual-OTE) behaviour, so a profile without the newer keys is
evaluated exactly as before:
  must_criteria.growth_mandate_required  (default True)
  must_criteria.lateral_ok               (default False)  lateral step is fine
  must_criteria.full_time                (default True)   False = part-time search
  must_criteria.hours_per_week_max       (part-time cap)
  must_criteria.ok_locations             (default Berlin/Potsdam)
  compensation.basis                     "annual_ote" (default) | "net_monthly"
For "net_monthly" the posting's pay is normalised to a gross hourly rate
(comp.hourly_gross, or monthly/annual gross with an hours reference) and
compared with compensation.gross_hourly_min."""

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

from . import salary

NOTIFY, REVIEW, DISCARD = "NOTIFY", "REVIEW", "DISCARD"

FIT_WEIGHTS = {"domain": 30, "function": 25, "career": 20, "conditions": 15, "mission": 10}
CAREER_STEP_SCORE = {"step_up": 1.0, "lateral_with_lever": 0.7, "unknown": 0.3, "lateral": 0.0, "down": 0.0}
OK_LOCATIONS = ("berlin", "potsdam")


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def earliest_start(profile: dict, today: Optional[date] = None) -> dict:
    """Earliest start if notice were given today: the contractual variants
    (month end / quarter end, rule still unknown) and the negotiated
    shorter notice. Only a deadline the negotiated variant can't meet is
    a hard exclusion."""
    today = today or date.today()
    np_ = profile["notice_period"]
    neg_months = np_.get("negotiable_months")
    negotiated = None
    if neg_months:
        n_end = _add_months(today, neg_months)
        negotiated = date(n_end.year, n_end.month, calendar.monthrange(n_end.year, n_end.month)[1]) + timedelta(days=1)
    raw_end = _add_months(today, profile["notice_period"]["months"])
    month_end = date(raw_end.year, raw_end.month, calendar.monthrange(raw_end.year, raw_end.month)[1])
    q_month = ((raw_end.month - 1) // 3 + 1) * 3
    quarter_end = date(raw_end.year, q_month, calendar.monthrange(raw_end.year, q_month)[1])
    rule = profile["notice_period"].get("end_rule", "unknown")
    return {
        "month_end": month_end + timedelta(days=1),
        "quarter_end": quarter_end + timedelta(days=1),
        "rule": rule,
        "negotiated": negotiated or (month_end + timedelta(days=1)),
    }


def fit_score(posting: dict, profile: Optional[dict] = None) -> tuple:
    """0-100. A dimension without an evidence string counts as 0, so an
    unsupported claim can't raise the score. With must_criteria.lateral_ok
    a lateral move is the target and scores full career credit."""
    parts = {}
    fit = posting.get("fit") or {}
    for dim in ("domain", "function", "conditions", "mission"):
        item = fit.get(dim) or {}
        score = float(item.get("score") or 0) if (item.get("evidence") or "").strip() else 0.0
        parts[dim] = round(FIT_WEIGHTS[dim] * max(0.0, min(1.0, score)), 1)
    step = posting.get("career_step") or "unknown"
    table = CAREER_STEP_SCORE
    if profile and (profile.get("must_criteria") or {}).get("lateral_ok"):
        table = {**CAREER_STEP_SCORE, "lateral": 1.0, "lateral_with_lever": 1.0, "unknown": 0.7}
    parts["career"] = round(FIT_WEIGHTS["career"] * table.get(step, 0.3), 1)
    return round(sum(parts.values()), 1), parts


def comp_basis(profile: dict) -> str:
    return (profile.get("compensation") or {}).get("basis") or "annual_ote"


def hourly_gross(posting: dict) -> dict:
    """Normalise a part-time posting's pay to a gross hourly rate. Only
    figures the ad states; an annual or monthly figure needs the hours it
    refers to (comp.hours_reference, else the posting's hours_per_week)."""
    c = posting.get("comp") or {}
    hours_ref = c.get("hours_reference") or posting.get("hours_per_week")
    if c.get("hourly_gross") is not None:
        return {"hourly": float(c["hourly_gross"]), "derived_from": "Stundenlohn laut Anzeige"}
    if c.get("monthly_gross") is not None and hours_ref:
        return {"hourly": round(float(c["monthly_gross"]) / (float(hours_ref) * 52 / 12), 2),
                "derived_from": f"{c['monthly_gross']} € brutto/Monat bei {hours_ref} Std./Woche"}
    annual = c.get("fix_min") or c.get("fix_max")
    if annual is not None and hours_ref:
        return {"hourly": round(float(annual) / (float(hours_ref) * 52), 2),
                "derived_from": f"{annual} € brutto/Jahr bei {hours_ref} Std./Woche"}
    return {"hourly": None, "derived_from": None,
            "missing": "Stundenbezug fehlt" if (annual is not None or c.get("monthly_gross") is not None) else "keine Zahl"}


def _compensation_hourly(posting: dict, profile: dict) -> dict:
    """Same output shape as compensation(), for the net_monthly basis."""
    c = posting.get("comp") or {}
    cp = profile["compensation"]
    hours_max = (profile.get("must_criteria") or {}).get("hours_per_week_max") or cp.get("hours_per_week_max")
    h = hourly_gross(posting)
    hourly = h["hourly"]
    monthly = round(hourly * float(hours_max) * 52 / 12) if (hourly is not None and hours_max) else None
    return {
        "basis": "net_monthly", "hourly": hourly, "hours_max": hours_max,
        "monthly_gross_at_max_hours": monthly, "derived_from": h.get("derived_from"),
        "fix": monthly, "variable": None, "ote": monthly, "realism": "n/a", "conservative": monthly,
        "source": c.get("source"), "source_note": c.get("source_note") or "",
        "equity_note": "", "benefits_note": c.get("benefits_note") or "",
        "evidenced": c.get("source") in cp["accepted_sources"] and hourly is not None
                     and (c.get("source") != "company_extrapolated" or bool(c.get("extrapolated_from"))),
        "extrapolated_from": c.get("extrapolated_from") or [],
        "required_hourly": cp.get("gross_hourly_min"),
    }


def compensation(posting: dict, profile: dict) -> dict:
    """Nominal vs. conservative view. Conservative = guaranteed fix (lower
    end of a range) + variable target x realisation factor. Equity is
    reported but never counted."""
    if comp_basis(profile) == "net_monthly":
        return _compensation_hourly(posting, profile)
    c = posting.get("comp") or {}
    cp = profile["compensation"]
    fix = c.get("fix_min") or c.get("fix_max")
    variable = c.get("variable_target")
    ote = c.get("ote")
    if ote is None and fix is not None and variable is not None:
        ote = fix + variable
    if variable is None and ote is not None and fix is not None:
        variable = max(0, ote - fix)
    realism = c.get("bonus_realism") or "unknown"
    if c.get("source") == "company_extrapolated" and realism == "realistic":
        realism = "uncertain"   # a sister posting's bonus says little about this role's payout
    factor = cp["bonus_realisation_factors"].get(realism, 0.35)
    conservative = None
    if fix is not None:
        conservative = round(fix + (variable or 0) * factor)
    out = {
        "fix": fix, "variable": variable, "ote": ote, "realism": realism,
        "conservative": conservative, "source": c.get("source"),
        "source_note": c.get("source_note") or "", "equity_note": c.get("equity_note") or "",
        "benefits_note": c.get("benefits_note") or "",
        "evidenced": (c.get("source") in cp["accepted_sources"] and fix is not None and ote is not None
                      and (c.get("source") != "company_extrapolated" or bool(c.get("extrapolated_from")))),
        "extrapolated_from": c.get("extrapolated_from") or [],
    }
    if ote is not None:
        out["ote_delta_eur"] = ote - cp["current_ote"]
        out["ote_delta_pct"] = round((ote - cp["current_ote"]) / cp["current_ote"] * 100, 1)
    if conservative is not None:
        out["conservative_delta_eur"] = conservative - cp["current_conservative"]
        out["conservative_delta_pct"] = round(
            (conservative - cp["current_conservative"]) / cp["current_conservative"] * 100, 1)
    return out


def required_tier(posting: dict, profile: dict, fit: float) -> tuple:
    cp = profile["compensation"]
    flags = [f for f in (posting.get("risk_flags") or []) if f in cp["high_risk_flags"]]
    if posting.get("relocation_required") and "relocation" not in flags:
        flags.append("relocation")
    if (posting.get("travel_pct") or 0) >= 40 and "high_travel" not in flags:
        flags.append("high_travel")
    if flags:
        return cp["tiers"]["high_risk"], "Risikostufe (" + ", ".join(flags) + ")"
    if fit >= cp["exceptional_fit_score"]:
        return cp["tiers"]["exceptional_fit"], "außergewöhnliche Passung"
    return cp["tiers"]["standard"], "Standard"


def _location_ok(posting: dict, profile: Optional[dict] = None) -> bool:
    loc = (posting.get("location") or "").lower()
    remote = posting.get("remote") or "unknown"
    ok = tuple((profile or {}).get("must_criteria", {}).get("ok_locations") or OK_LOCATIONS)
    if any(c in loc for c in ok):
        return True
    if remote in ("remote_de", "remote"):
        return True
    # elsewhere: acceptable only via relocation (which raises the tier) or
    # a genuinely good hybrid model; plain onsite elsewhere is not.
    return bool(posting.get("relocation_required")) or remote == "hybrid"


def evaluate(posting: dict, profile: dict, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    discard, review, ok, notes = [], [], [], []
    mc = profile["must_criteria"]
    th = profile["thresholds"]
    cp = profile["compensation"]

    # ── Must criteria / exclusions ────────────────────────────────────
    if posting.get("is_open") is False:
        discard.append("Anzeige abgelaufen oder nicht mehr offen")
    if posting.get("role_family") not in mc["role_families"]:
        discard.append("Rollentyp außerhalb des Zielprofils")
    if mc.get("growth_mandate_required", True):
        if posting.get("growth_mandate") is False:
            discard.append("Kein Growth-Mandat (Bestandskundenpflege / operativer Verkauf)")
        elif posting.get("growth_mandate") is None:
            review.append("Growth-Mandat nicht belegt")
    step = posting.get("career_step") or "unknown"
    if mc.get("lateral_ok"):
        if step == "down":
            discard.append("Rückschritt gegenüber heutiger Rolle")
    elif step in ("lateral", "down"):
        discard.append("Kein Karriereschritt (lateral) – Titel allein reicht nicht")
    elif step == "lateral_with_lever" and not posting.get("levers"):
        discard.append("Senior-IC-Rolle ohne belegten strategischen Hebel")
    elif step == "unknown":
        review.append("Karrierefortschritt unklar")
    if mc.get("full_time", True):
        if posting.get("full_time") is False:
            discard.append("Keine Vollzeitstelle")
    else:
        hours_max = mc.get("hours_per_week_max")
        hours = posting.get("hours_per_week")
        if hours is not None and hours_max and float(hours) > float(hours_max):
            discard.append(f"{hours:g} Std./Woche über der Obergrenze von {hours_max:g} Std.")
        elif hours is None and posting.get("full_time") is True and not posting.get("part_time_possible"):
            discard.append("Vollzeitstelle, Teilzeit nicht angeboten")
        elif hours is None:
            review.append("Wochenstunden nicht belegt")
    if posting.get("language_ok") is False:
        discard.append("Arbeitssprache passt nicht")
    if not _location_ok(posting, profile):
        discard.append("Standort/Präsenzmodell nicht " + ("/".join(mc["ok_locations"]).title() if mc.get("ok_locations") else "Berlin") + "-kompatibel")

    start = earliest_start(profile, now.date())
    req = posting.get("required_start_by")
    if req:
        req_d = date.fromisoformat(req)
        if req_d < start["negotiated"]:
            discard.append(f"Zwingender Start bis {req_d:%d.%m.%Y} vor frühestmöglichem Eintritt, auch mit verkürzter Frist ({start['negotiated']:%d.%m.%Y})")
        elif req_d < start["month_end"]:
            notes.append(f"Start bis {req_d:%d.%m.%Y} nur mit verhandelter Verkürzung der Kündigungsfrist")
        elif start["rule"] != "month_end" and req_d < start["quarter_end"]:
            notes.append("Startfrist nur bei Kündigung zum Monatsende einhaltbar – Vertragswortlaut klären")

    # ── Fit (professional match only; the salary picture is judged
    # separately below, so an unknown salary no longer lowers the fit) ──
    fit, fit_parts = fit_score(posting, profile)
    if fit < th["fit_review"]:
        discard.append(f"Fachliche Passung zu gering ({fit:.0f}/100)")
    elif fit < th["fit_notify"]:
        review.append(f"Passung unter Meldeschwelle ({fit:.0f}/100)")

    # ── Compensation ──────────────────────────────────────────────────
    comp = compensation(posting, profile)
    if comp.get("basis") == "net_monthly":
        need = comp.get("required_hourly")
        if not comp["evidenced"]:
            h = hourly_gross(posting)
            review.append("Kein Gehalt angegeben oder ableitbar – abgewertet"
                          + (f" ({h['missing']})" if h.get("missing") == "Stundenbezug fehlt" else ""))
        elif need is not None and comp["hourly"] < float(need):
            discard.append(f"{comp['hourly']:.2f} € brutto/Std. unter Mindestsatz {float(need):.2f} €".replace(".", ","))
        else:
            if comp.get("source") == "company_extrapolated":
                notes.append("Gehalt aus vergleichbaren Anzeigen derselben Firma abgeleitet, nicht für diese Stelle bestätigt")
            flags = [f for f in (posting.get("risk_flags") or []) if f in cp.get("high_risk_flags", [])]
            if flags:
                review.append("Risikomerkmale: " + ", ".join(flags))
        tier, tier_reason = need, "Mindest-Stundensatz"
    else:
        tier, tier_reason = required_tier(posting, profile, fit)
    comp["required_ote"] = tier
    comp["tier_reason"] = tier_reason
    # ── Salary picture: stated figures, else the researched estimate ──
    if comp.get("basis") == "net_monthly":
        sal = salary.summary(None, profile, None)
    elif comp["evidenced"]:
        sal = salary.summary(salary.normalize(salary.from_comp(comp), profile), profile, tier)
    else:
        sal = salary.summary(salary.normalize(posting.get("salary_estimate"), profile), profile, tier)
    if comp.get("basis") == "net_monthly":
        pass
    elif not comp["evidenced"]:
        if sal["verdict"] == "unknown":
            review.append("Kein Gehalt angegeben und noch keine belastbare Schätzung")
        elif not sal["usable"]:
            review.append(f"Gehaltsschätzung nur mit geringer Sicherheit ({sal['label']}) – vor einer Meldung klären")
        elif sal["verdict"] == "met":
            notes.append(f"Gehalt {sal['origin_label']} ({sal['confidence_label']}), keine Arbeitgeberzusage – Schwelle voraussichtlich erfüllt")
        elif sal["verdict"] == "overlap":
            review.append("Geschätzte Gehaltsspanne überschneidet die Schwelle – Klärung nötig")
        else:
            review.append(f"Geschätztes Gehalt voraussichtlich unter der Schwelle ({sal['detail']})")
    else:
        if comp["source"] == "company_extrapolated":
            notes.append("Gehalt aus vergleichbaren Anzeigen derselben Firma abgeleitet, nicht für diese Stelle bestätigt")
        if comp["realism"] == "unrealistic" and comp["fix"] < cp["fix_floor"]:
            discard.append(f"Hohes OTE, aber Fix {comp['fix']:,} € unter Floor und Bonus unrealistisch".replace(",", "."))
        elif comp["fix"] < cp["fix_floor"]:
            if fit >= cp["exceptional_fit_score"]:
                review.append("Fix unter 120k-Floor – nur wegen außergewöhnlicher Rolle weiter prüfen")
            else:
                discard.append(f"Fix {comp['fix']:,} € unter 120k-Floor".replace(",", "."))
        if comp["ote"] < cp["tiers"]["exceptional_fit"]:
            discard.append(f"OTE {comp['ote']:,} € unter 130k-Mindestschwelle".replace(",", "."))
        elif comp["ote"] < tier:
            review.append(f"OTE unter erforderlicher Stufe {tier:,} € ({tier_reason})".replace(",", "."))
        # conservative value must beat today's conservative value by the
        # same percentage the nominal tier demands over today's OTE
        needed = round(cp["current_conservative"] * tier / cp["current_ote"])
        comp["required_conservative"] = needed
        if comp["conservative"] is not None and comp["conservative"] < needed:
            msg = f"Konservativ erwartbar {comp['conservative']:,} € < benötigt {needed:,} €".replace(",", ".")
            (discard if comp["realism"] == "unrealistic" else review).append(msg)

    # ── Freshness ─────────────────────────────────────────────────────
    verified = posting.get("verified_at")
    if not verified:
        review.append("Nicht verifiziert")
    else:
        age_h = (now - datetime.fromisoformat(verified)).total_seconds() / 3600
        if age_h > th["reverify_hours"]:
            review.append("Vor Meldung erneut prüfen (Verifikation älter als 48 h)")

    if discard:
        decision = DISCARD
    elif review:
        decision = REVIEW
    else:
        decision = NOTIFY
        ok.append("Alle Muss-Kriterien erfüllt, Vergütung belegt und über Schwelle")
    return {
        "decision": decision,
        "reasons": discard or review or ok,
        "all_review_reasons": review,
        "notes": notes,
        "fit": fit, "fit_parts": fit_parts,
        "comp": comp,
        "salary": sal,
        "earliest_start": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in start.items()},
        "evaluated_at": now.isoformat(timespec="seconds"),
    }
