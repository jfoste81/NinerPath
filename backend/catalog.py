"""Static catalog: courses, degree plans, offerings, prereqs, standing (Phase 1)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable, Optional

from data_access import load_json
from models import STANDING_ORDER, STANDING_RANK, STANDING_THRESHOLDS

COURSES = load_json("courses.json")
COURSE_BY_ID = {course["id"]: course for course in COURSES}


def _normalize_standing_label(label: Optional[str]) -> Optional[str]:
    if not label or not str(label).strip():
        return None
    s = str(label).strip().lower()
    for name in STANDING_ORDER:
        if name.lower() == s:
            return name
    return None


def infer_class_standing_from_credits(earned_credits: float) -> str:
    standing = "Freshman"
    for threshold, name in STANDING_THRESHOLDS:
        if earned_credits >= threshold:
            standing = name
    return standing


def earned_credits_from_completed(completed_ids: Iterable[str]) -> float:
    total = 0.0
    for cid in completed_ids:
        meta = COURSE_BY_ID.get(cid)
        if meta:
            total += float(meta.get("credits") or 0)
    return total


def effective_class_standing(completed_ids: Iterable[str], override: Optional[str] = None) -> str:
    fixed = _normalize_standing_label(override)
    if fixed:
        return fixed
    return infer_class_standing_from_credits(earned_credits_from_completed(completed_ids))


def standing_satisfies_min(student_standing: str, min_standing: Optional[str]) -> bool:
    if not min_standing or not str(min_standing).strip():
        return True
    req = _normalize_standing_label(min_standing)
    if not req:
        return True
    su = _normalize_standing_label(student_standing)
    if not su:
        su = "Freshman"
    return STANDING_RANK.get(su, 0) >= STANDING_RANK.get(req, 0)


def _prereq_token_satisfied(token: str, completed: set) -> bool:
    """One catalog slot: course id or compound 'ID and ID ...' (all parts completed)."""
    if not token or not isinstance(token, str):
        return False
    if " and " in token:
        parts = [p.strip() for p in token.split(" and ") if p.strip()]
        return bool(parts) and all(p in completed for p in parts)
    return token in completed


def _prereqs_or_group_satisfied(or_group: list, completed: set) -> bool:
    """Any alternative satisfies the group; nested lists are nested OR."""
    if not or_group:
        return False
    for alt in or_group:
        if isinstance(alt, str):
            if _prereq_token_satisfied(alt, completed):
                return True
        elif isinstance(alt, list):
            if _prereqs_or_group_satisfied(alt, completed):
                return True
        else:
            return False
    return False


def prereqs_satisfied_tree(prereqs: Any, completed: set) -> bool:
    """
    Top-level prereqs: conjunction (AND) of conjuncts. Each list conjunct is one OR group.
    """
    if not prereqs:
        return True
    if not isinstance(prereqs, list):
        return False
    for conjunct in prereqs:
        if isinstance(conjunct, str):
            if not _prereq_token_satisfied(conjunct, completed):
                return False
        elif isinstance(conjunct, list):
            if not _prereqs_or_group_satisfied(conjunct, completed):
                return False
        else:
            return False
    return True


def _iter_compound_course_ids(token: str) -> Iterable[str]:
    if " and " in token:
        for p in token.split(" and "):
            p = p.strip()
            if p:
                yield p
    else:
        yield token


def _iter_or_group_course_ids(or_group: list) -> Iterable[str]:
    for alt in or_group:
        if isinstance(alt, str):
            yield from _iter_compound_course_ids(alt)
        elif isinstance(alt, list):
            yield from _iter_or_group_course_ids(alt)


def iter_prereq_course_ids(prereqs: Any) -> Iterable[str]:
    """Course ids referenced in a prereq tree (for sorting / dependents)."""
    if not prereqs or not isinstance(prereqs, list):
        return
    for conjunct in prereqs:
        if isinstance(conjunct, str):
            yield from _iter_compound_course_ids(conjunct)
        elif isinstance(conjunct, list):
            yield from _iter_or_group_course_ids(conjunct)


DEGREE_PLANS = load_json("degree_plans.json")
GEN_EDS = load_json("gen_eds.json")


def _effective_plan_root(degree_key: str) -> dict:
    """Degree-level plan object, with shared Foundation ``major_core`` for B.A. if the JSON omits it."""
    base = DEGREE_PLANS.get(degree_key)
    if not isinstance(base, dict):
        return {}
    if base.get("major_core"):
        return base
    if degree_key == "ba_computer_science":
        bs = DEGREE_PLANS.get("bs_computer_science") or {}
        mc = bs.get("major_core")
        if isinstance(mc, list) and mc:
            merged = dict(base)
            merged["major_core"] = list(mc)
            return merged
    return base


def _foundation_course_id_set(plan_root: dict) -> set:
    """Catalog ids that belong in Foundation of Computing (degree-level core + math/stat)."""
    out: set = set()
    for cid in plan_root.get("major_core") or []:
        if isinstance(cid, str) and cid.strip():
            out.add(cid.strip())
    for cid in plan_root.get("math_and_statistics") or []:
        if isinstance(cid, str) and cid.strip():
            out.add(cid.strip())
    return out


def _ensure_catalog_sections(offerings: dict) -> dict:
    """Ensure every course in courses.json has at least one mock section (scheduling + calendar)."""
    out = dict(offerings)
    sections = list(out.get("sections") or [])
    have = {s.get("course_id") for s in sections if s.get("course_id")}
    slot_templates = [
        ("MWF", "1:00 PM - 1:50 PM"),
        ("TR", "2:00 PM - 3:15 PM"),
        ("MW", "4:00 PM - 5:15 PM"),
        ("TR", "9:30 AM - 10:45 AM"),
    ]
    n = 0
    for course in COURSES:
        cid = course["id"]
        if cid in have:
            continue
        days, time = slot_templates[n % len(slot_templates)]
        n += 1
        try:
            cr = int(course.get("credits") or 0)
        except (TypeError, ValueError):
            cr = 0
        sections.append(
            {
                "course_id": cid,
                "section": f"AUT{n:03d}",
                "title": course.get("name", cid),
                "credits": cr or 3,
                "instructor": "TBD",
                "days": days,
                "time": time,
                "location": "TBD",
                "enrollment_cap": 40,
                "enrolled": 0,
            }
        )
        have.add(cid)
    out["sections"] = sections
    return out


_fall_26_offerings = _ensure_catalog_sections(load_json("fall_2026_offerings.json"))
# When scheduling for a label in this map, only those course_ids may be recommended.
OFFERINGS_BY_TERM_LABEL = {}
_tl = (_fall_26_offerings.get("term") or "").strip()
if _tl:
    OFFERINGS_BY_TERM_LABEL[_tl] = {
        s["course_id"]
        for s in _fall_26_offerings.get("sections", [])
        if s.get("course_id")
    }

# All mock scheduling uses this term (Fall 2026 offerings catalog only).
REGISTRATION_TERM_LABEL = (_fall_26_offerings.get("term") or "Fall 2026").strip() or "Fall 2026"
REGISTRATION_TERM_SEASON = REGISTRATION_TERM_LABEL.split()[0] if REGISTRATION_TERM_LABEL.split() else "Fall"

def registration_schedule_term() -> tuple[str, str]:
    """Sole registration term for schedule generation and section calendar (Fall 2026 mock data)."""
    return REGISTRATION_TERM_LABEL, REGISTRATION_TERM_SEASON


def get_current_term_label():
    now = datetime.now()
    term = "Spring" if now.month <= 5 else "Fall"
    return f"{term} {now.year}", term


def resolve_schedule_term(term_query: Optional[str] = None):
    """Returns (term_label, season) e.g. ('Fall 2026', 'Fall') for catalog season checks."""
    now = datetime.now()
    default_label, default_season = get_current_term_label()
    if not term_query or not str(term_query).strip():
        return default_label, default_season
    q = str(term_query).strip()
    parts = q.split()
    if len(parts) >= 2 and parts[0] in ("Fall", "Spring", "Summer", "Winter") and parts[1].isdigit():
        return q, parts[0]
    if len(parts) == 1 and parts[0] in ("Fall", "Spring", "Summer", "Winter"):
        return f"{parts[0]} {now.year}", parts[0]
    return default_label, default_season


def compute_dependent_counts(course_list):
    dependent_counts = {course["id"]: 0 for course in course_list}
    for course in course_list:
        for prereq in iter_prereq_course_ids(course.get("prereqs") or []):
            if prereq in dependent_counts:
                dependent_counts[prereq] += 1
    return dependent_counts


DEPENDENT_COUNTS = compute_dependent_counts(COURSES)


def _catalog_credits(cid: str) -> int:
    m = COURSE_BY_ID.get(cid) or {}
    try:
        return int(m.get("credits") or 0)
    except (TypeError, ValueError):
        return 0


def _gen_ed_credits_completed_in_category(category: dict, completed_set: set) -> int:
    pool = [c.strip() for c in category.get("courses", []) if isinstance(c, str) and c.strip()]
    return sum(_catalog_credits(cid) for cid in pool if cid in completed_set)


def _gen_ed_category_satisfied(category: dict, completed_set: set) -> bool:
    try:
        req = int(category.get("required_credits", 0) or 0)
    except (TypeError, ValueError):
        req = 0
    return _gen_ed_credits_completed_in_category(category, completed_set) >= req


def _gen_ed_deficit_catalog_course_ids(completed_set: set) -> list:
    """Catalog courses that may still count toward an unsatisfied gen-ed category (for scheduling)."""
    out: list = []
    seen: set = set()
    for cat in GEN_EDS:
        if _gen_ed_category_satisfied(cat, completed_set):
            continue
        for cid in cat.get("courses", []) or []:
            if not isinstance(cid, str) or not cid.strip():
                continue
            cid = cid.strip()
            if cid in completed_set or cid in seen:
                continue
            if cid not in COURSE_BY_ID:
                continue
            seen.add(cid)
            out.append(cid)
    return out


def parse_course_number(course_id):
    try:
        return int(course_id.split(" ")[1])
    except (IndexError, ValueError):
        return 9999
