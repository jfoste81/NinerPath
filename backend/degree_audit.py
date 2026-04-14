"""Degree audit table construction"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

import catalog
import degree_plan
from catalog import (
    COURSE_BY_ID,
    DEGREE_PLANS,
    GEN_EDS,
    REGISTRATION_TERM_LABEL,
    _catalog_credits,
    _foundation_course_id_set,
    _effective_plan_root,
    _gen_ed_credits_completed_in_category,
    parse_course_number,
)
from degree_plan import normalize_degree_plan_for_schedule

def get_gen_ed_progress(student_history, gen_eds):
    completed_ids = {
        course["id"] for course in student_history.get("completed_courses", [])
    }

    progress = []

    for category in gen_eds:
        completed_courses = [
            course_id for course_id in category["courses"]
            if course_id in completed_ids
        ]

        progress.append({
            "category": category["category"],
            "completed_courses": completed_courses,
            "completed_count": len(completed_courses),
            "required_credits": category["required_credits"]
        })

    return progress

def _build_gen_ed_subsection(category: dict, by_id: dict, completed_set: set, planned_ids: set) -> dict:
    """One gen-ed competency block: header + completed course rows + optional single-line still-needed row."""
    title = str(category.get("category") or "General education")
    pool = sorted(
        {c.strip() for c in category.get("courses", []) if isinstance(c, str) and c.strip()},
        key=parse_course_number,
    )
    try:
        req = int(category.get("required_credits", 0) or 0)
    except (TypeError, ValueError):
        req = 0
    done_cr = _gen_ed_credits_completed_in_category(category, completed_set)
    remaining = [c for c in pool if c not in completed_set]
    planned_in_remaining = [c for c in remaining if c in planned_ids]

    if done_cr >= req:
        header_status = "completed"
    elif planned_in_remaining:
        header_status = "planned"
    else:
        header_status = "incomplete"

    rows: list = []
    for cid in pool:
        if cid not in completed_set:
            continue
        if cid not in COURSE_BY_ID:
            continue
        r = _audit_row_course(cid, by_id, completed_set, planned_ids)
        r["requirement_group"] = title
        rows.append(r)

    if done_cr < req:
        deficit = max(0, req - done_cr)
        rem_display = [c for c in remaining if c in COURSE_BY_ID]
        if not rem_display:
            rem_display = list(remaining)
        rows.append(
            {
                "kind": "still_needed_pool",
                "course_id": "—",
                "deficit_credits": deficit,
                "alternatives": rem_display,
                "planned_in_pool": planned_in_remaining,
                "status": "planned" if planned_in_remaining else "incomplete",
                "grade": "—",
                "credits": deficit,
                "term": "—",
                "repeated": "",
            }
        )

    return {
        "title": title,
        "header_status": header_status,
        "credits_applied": done_cr,
        "credits_required": req,
        "rows": rows,
    }


def _elective_subarea_sort_key(k: str) -> tuple:
    m = re.match(r"^elective_subarea_(\d+)$", str(k))
    return (int(m.group(1)) if m else 9999, k)


def _choice_or_single_row(alts: list, by_id: dict, completed_set: set, planned_ids: set) -> dict:
    if len(alts) == 1:
        return _audit_row_course(alts[0], by_id, completed_set, planned_ids)
    return _audit_row_choice(alts, by_id, completed_set, planned_ids)


def _header_from_row(row: dict) -> str:
    st = row.get("status") or "incomplete"
    if st in ("completed", "registered"):
        return "completed"
    if st == "planned":
        return "planned"
    return "incomplete"


def _build_concentration_elective_subsections(
    plan_root: dict, raw: dict, sched: dict, by_id: dict, completed_set: set, planned_ids: set
) -> list:
    """Structured elective / pool blocks (subareas, choose-N lists, security pick, leftovers)."""
    cap_ids = set(str(c).strip() for c in (plan_root.get("capstone_options") or []) if isinstance(c, str) and c.strip())
    pool_ids = list(sched.get("elective_pool_ids") or [])
    assigned: set = set()
    out: list = []

    def mark(ids: Iterable[str]) -> None:
        for x in ids:
            if isinstance(x, str) and x.strip():
                assigned.add(x.strip())

    sub_keys = sorted([k for k in raw if str(k).startswith("elective_subarea_")], key=_elective_subarea_sort_key)
    for k in sub_keys:
        v = raw.get(k)
        if not isinstance(v, list):
            continue
        alts = [x.strip() for x in v if isinstance(x, str) and x.strip()]
        if not alts:
            continue
        mark(alts)
        m = re.match(r"^elective_subarea_(\d+)$", str(k))
        num = m.group(1) if m else "?"
        title = f"Elective subarea {num}"
        row = _choice_or_single_row(alts, by_id, completed_set, planned_ids)
        if row.get("kind") != "choice":
            row["requirement_group"] = title
        done_pick = 1 if row.get("status") in ("completed", "registered") else 0
        out.append(
            {
                "title": title,
                "header_status": _header_from_row(row),
                "picks_applied": done_pick,
                "picks_required": 1,
                "credits_applied": 0,
                "credits_required": 0,
                "rows": [row],
            }
        )

    electives_obj = raw.get("electives")
    if isinstance(electives_obj, dict):
        opts = [x.strip() for x in (electives_obj.get("options") or []) if isinstance(x, str) and x.strip()]
        if opts:
            mark(opts)
            title = "Concentration electives"
            try:
                choose_n = int(electives_obj.get("choose") or 0)
            except (TypeError, ValueError):
                choose_n = 0
            done_ids = [o for o in opts if o in completed_set]
            n_done = len(done_ids)
            remaining = [o for o in opts if o not in completed_set]
            planned_r = [o for o in remaining if o in planned_ids]
            rows: list = []
            for o in sorted(done_ids, key=parse_course_number):
                if o not in COURSE_BY_ID:
                    continue
                r = _audit_row_course(o, by_id, completed_set, planned_ids)
                r["requirement_group"] = title
                rows.append(r)
            if choose_n > 0 and n_done < choose_n:
                rem_display = [o for o in remaining if o in COURSE_BY_ID]
                if not rem_display:
                    rem_display = list(remaining)
                rows.append(
                    {
                        "kind": "still_needed_pool",
                        "course_id": "—",
                        "deficit_count": max(0, choose_n - n_done),
                        "alternatives": rem_display,
                        "planned_in_pool": planned_r,
                        "status": "planned" if planned_r else "incomplete",
                        "grade": "—",
                        "credits": max(0, choose_n - n_done),
                        "term": "—",
                        "repeated": "",
                    }
                )
            elif choose_n <= 0:
                for o in sorted(remaining, key=parse_course_number):
                    if o not in COURSE_BY_ID:
                        continue
                    r = _audit_row_course(o, by_id, completed_set, planned_ids)
                    r["requirement_group"] = title
                    rows.append(r)
            if choose_n > 0 and (rows or n_done >= choose_n):
                hdr = "completed" if n_done >= choose_n else ("planned" if planned_r else "incomplete")
                out.append(
                    {
                        "title": f"{title} (choose {choose_n})",
                        "header_status": hdr,
                        "picks_applied": min(n_done, choose_n),
                        "picks_required": choose_n,
                        "credits_applied": sum(_catalog_credits(c) for c in done_ids),
                        "credits_required": 0,
                        "rows": rows,
                    }
                )
            elif rows:
                hdr = "completed" if all(r.get("status") in ("completed", "registered") for r in rows) else (
                    "planned" if any(r.get("status") == "planned" for r in rows) else "incomplete"
                )
                out.append(
                    {
                        "title": title,
                        "header_status": hdr,
                        "credits_applied": 0,
                        "credits_required": 0,
                        "hide_progress": True,
                        "rows": rows,
                    }
                )

    sec = raw.get("required_security_elective")
    if isinstance(sec, list) and sec:
        alts = [x.strip() for x in sec if isinstance(x, str) and x.strip()]
        if alts:
            mark(alts)
            title = "Security elective requirement"
            row = _choice_or_single_row(alts, by_id, completed_set, planned_ids)
            if row.get("kind") != "choice":
                row["requirement_group"] = title
            done_pick = 1 if row.get("status") in ("completed", "registered") else 0
            out.append(
                {
                    "title": title,
                    "header_status": _header_from_row(row),
                    "picks_applied": done_pick,
                    "picks_required": 1,
                    "credits_applied": 0,
                    "credits_required": 0,
                    "rows": [row],
                }
            )

    legacy_pool = raw.get("elective_pool")
    if isinstance(legacy_pool, list) and legacy_pool:
        lp = [x.strip() for x in legacy_pool if isinstance(x, str) and x.strip()]
        lp = [x for x in lp if x not in assigned]
        if lp:
            mark(lp)
            rows = []
            for cid in sorted(lp, key=parse_course_number):
                if cid not in COURSE_BY_ID:
                    continue
                r = _audit_row_course(cid, by_id, completed_set, planned_ids)
                r["requirement_group"] = "Program elective pool"
                rows.append(r)
            if rows:
                st = "completed" if all(r.get("status") in ("completed", "registered") for r in rows) else (
                    "planned" if any(r.get("status") == "planned" for r in rows) else "incomplete"
                )
                out.append(
                    {
                        "title": "Program elective pool",
                        "header_status": st,
                        "hide_progress": True,
                        "credits_applied": 0,
                        "credits_required": 0,
                        "rows": rows,
                    }
                )

    foundation_ids = _foundation_course_id_set(plan_root)
    leftover = [cid for cid in pool_ids if cid not in assigned and cid not in cap_ids and cid not in foundation_ids]
    if leftover:
        rows = []
        for cid in sorted(leftover, key=parse_course_number):
            if cid not in COURSE_BY_ID:
                continue
            r = _audit_row_course(cid, by_id, completed_set, planned_ids)
            r["requirement_group"] = "Scheduling pool"
            rows.append(r)
        if rows:
            st = "completed" if all(r.get("status") in ("completed", "registered") for r in rows) else (
                "planned" if any(r.get("status") == "planned" for r in rows) else "incomplete"
            )
            out.append(
                {
                    "title": "Additional scheduling pool courses",
                    "header_status": st,
                    "hide_progress": True,
                    "credits_applied": 0,
                    "credits_required": 0,
                    "rows": rows,
                }
            )

    return out


def _audit_row_course(cid: str, by_id: dict, completed_set: set, planned_ids: set) -> dict:
    meta = COURSE_BY_ID.get(cid) or {}
    name = meta.get("name", cid)
    credits = _catalog_credits(cid)
    rec = by_id.get(cid)
    if rec:
        grade = str(rec.get("grade", "")).strip() or "—"
        up = grade.upper()
        status = "registered" if up == "REG" else "completed"
        return {
            "kind": "course",
            "course_id": cid,
            "title": name,
            "status": status,
            "grade": grade,
            "credits": credits,
            "term": rec.get("term") or "—",
            "repeated": "",
        }
    if cid in planned_ids:
        return {
            "kind": "course",
            "course_id": cid,
            "title": name,
            "status": "planned",
            "grade": "—",
            "credits": credits,
            "term": REGISTRATION_TERM_LABEL,
            "repeated": "",
        }
    return {
        "kind": "course",
        "course_id": cid,
        "title": name,
        "status": "incomplete",
        "grade": "—",
        "credits": credits,
        "term": "—",
        "repeated": "",
    }


def _audit_row_choice(
    alternatives: list,
    by_id: dict,
    completed_set: set,
    planned_ids: set,
    *,
    requirement_label: str | None = None,
) -> dict:
    alts = [a.strip() for a in alternatives if isinstance(a, str) and a.strip()]
    taken = [a for a in alts if a in completed_set]
    label = " or ".join(alts)

    def _extras() -> dict:
        return {"requirement_label": requirement_label} if requirement_label else {}

    if taken:
        cid = taken[0]
        meta = COURSE_BY_ID.get(cid) or {}
        rec = by_id[cid]
        grade = str(rec.get("grade", "")).strip() or "—"
        up = grade.upper()
        status = "registered" if up == "REG" else "completed"
        return {
            "kind": "choice",
            "course_id": label,
            "title": meta.get("name", cid),
            "status": status,
            "grade": grade,
            "credits": _catalog_credits(cid),
            "term": rec.get("term") or "—",
            "repeated": "",
            "alternatives": alts,
            **_extras(),
        }
    planned_alts = [a for a in alts if a in planned_ids]
    if planned_alts:
        cid = planned_alts[0]
        meta = COURSE_BY_ID.get(cid) or {}
        return {
            "kind": "choice",
            "course_id": label,
            "title": meta.get("name", cid),
            "status": "planned",
            "grade": "—",
            "credits": _catalog_credits(cid),
            "term": REGISTRATION_TERM_LABEL,
            "repeated": "",
            "alternatives": alts,
            **_extras(),
        }
    return {
        "kind": "choice",
        "course_id": label,
        "title": f"Still needed: 1 class in {label}",
        "status": "incomplete",
        "grade": "—",
        "credits": max((_catalog_credits(a) for a in alts), default=0),
        "term": "—",
        "repeated": "",
        "alternatives": alts,
        **_extras(),
    }


def build_degree_audit(
    degree_key: str, conc_key: str, student_history: dict, planned_ids: Optional[Iterable[str]] = None
) -> dict:
    plan_root = _effective_plan_root(degree_key)
    concentrations = plan_root.get("concentrations") or {}
    if conc_key not in concentrations:
        conc_key = plan_root.get("default_concentration") or next(iter(concentrations.keys()), "systems_and_networks")
    raw = concentrations[conc_key]
    completed = student_history.get("completed_courses") or []
    by_id = {r["id"]: r for r in completed if isinstance(r, dict) and r.get("id")}
    completed_set = set(by_id.keys())
    sched = normalize_degree_plan_for_schedule(plan_root, conc_key, raw)
    planned_set = set(planned_ids) if planned_ids else set()
    foundation_ids = _foundation_course_id_set(plan_root)

    sections: list = []
    seen2: set = set()

    gen_ed_subsections = [_build_gen_ed_subsection(cat, by_id, completed_set, planned_set) for cat in GEN_EDS]
    if gen_ed_subsections:
        sections.append(
            {
                "id": "gen_ed",
                "title": "General education",
                "layout": "subsections",
                "subsections": gen_ed_subsections,
            }
        )

    major_rows = []
    for cid in plan_root.get("major_core") or []:
        if isinstance(cid, str) and cid.strip():
            major_rows.append(_audit_row_course(cid.strip(), by_id, completed_set, planned_set))
    for cid in plan_root.get("math_and_statistics") or []:
        if isinstance(cid, str) and cid.strip():
            major_rows.append(_audit_row_course(cid.strip(), by_id, completed_set, planned_set))
    caps = [c.strip() for c in (plan_root.get("capstone_options") or []) if isinstance(c, str) and c.strip()]
    if len(caps) >= 2:
        major_rows.append(
            _audit_row_choice(caps, by_id, completed_set, planned_set, requirement_label="Capstone")
        )
    elif len(caps) == 1:
        major_rows.append(_audit_row_course(caps[0], by_id, completed_set, planned_set))
    if major_rows:
        sections.append(
            {
                "id": "major_courses",
                "title": "Foundation of Computing / major courses",
                "rows": major_rows,
            }
        )

    block2 = []
    for item in raw.get("major_core") or []:
        if isinstance(item, str) and item.strip():
            cid = item.strip()
            if cid in foundation_ids:
                continue
            if cid not in seen2:
                seen2.add(cid)
                block2.append(_audit_row_course(cid, by_id, completed_set, planned_set))
        elif isinstance(item, list):
            block2.append(_audit_row_choice(item, by_id, completed_set, planned_set))
    for field in ("advanced_statistics", "related_courses"):
        for cid in raw.get(field) or []:
            if isinstance(cid, str) and cid.strip():
                cid = cid.strip()
                if cid not in seen2:
                    seen2.add(cid)
                    block2.append(_audit_row_course(cid, by_id, completed_set, planned_set))
    for cid in raw.get("required_courses") or []:
        if isinstance(cid, str) and cid.strip():
            cid = cid.strip()
            if cid not in seen2:
                seen2.add(cid)
                block2.append(_audit_row_course(cid, by_id, completed_set, planned_set))
    for cid in raw.get("required_options") or []:
        if isinstance(cid, str) and cid.strip():
            cid = cid.strip()
            if cid not in seen2:
                seen2.add(cid)
                block2.append(_audit_row_course(cid, by_id, completed_set, planned_set))
    if block2:
        sections.append(
            {
                "id": "concentration",
                "title": f"Concentration — {sched['concentration_label']}",
                "rows": block2,
            }
        )

    elec_subs = _build_concentration_elective_subsections(plan_root, raw, sched, by_id, completed_set, planned_set)
    if elec_subs:
        sections.append(
            {
                "id": "electives",
                "title": "Concentration electives",
                "layout": "subsections",
                "subsections": elec_subs,
            }
        )

    cr_other = raw.get("electives_other_disciplines_credits")
    if cr_other is None:
        cr_other = plan_root.get("electives_other_disciplines_credits")
    tech = raw.get("technical_electives_credits")
    if cr_other:
        try:
            n = int(cr_other)
        except (TypeError, ValueError):
            n = 0
        sections.append(
            {
                "id": "other_credits",
                "title": "Other degree requirements",
                "rows": [
                    {
                        "kind": "note",
                        "course_id": "—",
                        "title": f"Electives / breadth credits toward degree (not listed course-by-course): {cr_other} cr.",
                        "status": "incomplete",
                        "grade": "—",
                        "credits": n,
                        "term": "—",
                        "repeated": "",
                    }
                ],
            }
        )
    elif tech:
        sections.append(
            {
                "id": "technical_electives",
                "title": "Technical electives",
                "rows": [
                    {
                        "kind": "note",
                        "course_id": "—",
                        "title": f"Additional technical elective credits: {tech} cr (select with advisor / catalog).",
                        "status": "incomplete",
                        "grade": "—",
                        "credits": int(tech) if str(tech).isdigit() else 0,
                        "term": "—",
                        "repeated": "",
                    }
                ],
            }
        )

    req_ids = sched["required_course_ids"]
    concentration_credits_required = sum(_catalog_credits(c) for c in req_ids)
    concentration_credits_applied = sum(_catalog_credits(c) for c in req_ids if c in completed_set)
    badge = (
        "COMPLETE"
        if concentration_credits_required > 0 and concentration_credits_applied >= concentration_credits_required
        else "INCOMPLETE"
    )
    try:
        degree_total_credits = int(plan_root.get("total_degree_credits") or 120)
    except (TypeError, ValueError):
        degree_total_credits = 120
    degree_credits_applied = sum(_catalog_credits(cid) for cid in completed_set)
    major_title = f"{plan_root.get('name', 'Major')} — {sched['concentration_label']}"

    return {
        "major_title": major_title,
        "status_badge": badge,
        "degree_total_credits": degree_total_credits,
        "degree_credits_applied": degree_credits_applied,
        "concentration_credits_required": concentration_credits_required,
        "concentration_credits_applied": concentration_credits_applied,
        "credits_required": degree_total_credits,
        "credits_applied": degree_credits_applied,
        "catalog_year": plan_root.get("catalog_year", "2025-2026"),
        "gpa": student_history.get("gpa"),
        "footnote": "Core courses and Area of Concentration courses must be completed with a grade of B or better. This view uses NinerPath mock data.",
        "footer_note": "NOTE: If the capstone is shared with the concentration, additional elective credits may be required per catalog.",
        "registration_term_label": REGISTRATION_TERM_LABEL,
        "sections": sections,
    }

