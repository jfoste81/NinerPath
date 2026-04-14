"""Degree plan normalization for schedule and audit"""
from __future__ import annotations

from typing import Any

import catalog


def _dedupe_preserve(seq: list) -> list:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extend_course_strings(seq, out: list) -> None:
    """Append course id strings; recurse one level into lists (legacy nested prereq-style lists)."""
    if not seq:
        return
    for item in seq:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, list):
            for sub in item:
                if isinstance(sub, str) and sub.strip():
                    out.append(sub.strip())


def normalize_degree_plan_for_schedule(plan_root: dict, conc_key: str, raw: dict) -> dict:
    """
    Derive required_course_ids, elective_pool_ids, max_elective_picks, and label from degree_plans.json.
    Supports legacy keys (required_courses, elective_pool, elective_count) and current shapes
    (major_core on the degree, electives.choose/options, elective_subarea_*, required_options, etc.).
    """
    required: list[str] = []
    pool: list[str] = []

    _extend_course_strings(plan_root.get("major_core"), required)
    _extend_course_strings(plan_root.get("math_and_statistics"), required)

    for item in raw.get("major_core") or []:
        if isinstance(item, str) and item.strip():
            required.append(item.strip())
        elif isinstance(item, list):
            for sub in item:
                if isinstance(sub, str) and sub.strip():
                    pool.append(sub.strip())

    _extend_course_strings(raw.get("advanced_statistics"), required)
    _extend_course_strings(raw.get("related_courses"), required)
    _extend_course_strings(raw.get("required_courses"), required)
    _extend_course_strings(raw.get("required_options"), required)

    electives_obj = raw.get("electives")
    if isinstance(electives_obj, dict):
        _extend_course_strings(electives_obj.get("options"), pool)

    for k, v in raw.items():
        if str(k).startswith("elective_subarea_") and isinstance(v, list):
            _extend_course_strings(v, pool)

    _extend_course_strings(raw.get("required_security_elective"), pool)
    _extend_course_strings(raw.get("elective_pool"), pool)
    _extend_course_strings(plan_root.get("capstone_options"), pool)

    required = _dedupe_preserve(required)
    req_set = set(required)
    pool = [x for x in _dedupe_preserve(pool) if x not in req_set]

    max_e = raw.get("elective_count")
    if max_e is None and isinstance(electives_obj, dict):
        max_e = electives_obj.get("choose")
    subareas = [k for k in raw if str(k).startswith("elective_subarea_")]
    if max_e is None and subareas:
        max_e = len(subareas)
    if max_e is None:
        max_e = 0
    max_e = max(0, int(max_e))
    if plan_root.get("capstone_options"):
        max_e += 1

    label = raw.get("label") or conc_key.replace("_", " ").title()

    return {
        "required_course_ids": required,
        "elective_pool_ids": pool,
        "max_elective_picks": max_e,
        "concentration_label": label,
    }


def _strict_prereq_filter(course_dicts: list, completed_ids: set) -> list:
    """Prereqs must appear in academic history only (not satisfied by co-recommended courses)."""
    out = []
    done = set(completed_ids)
    for c in course_dicts:
        cid = c["id"]
        meta = catalog.COURSE_BY_ID.get(cid, c)
        prereqs = meta.get("prereqs") or []
        if catalog.prereqs_satisfied_tree(prereqs, done):
            out.append(c)
    return out


def _schedule_bundle_prereq_filter(course_dicts: list, completed_ids: set) -> list:
    """
    Same-term schedule: keep a course if its prereqs are met by completed history and/or courses
    listed earlier in this same recommendation (forward pass; list order must respect deps).
    """
    allow = set(completed_ids)
    out: list = []
    for c in course_dicts:
        meta = catalog.COURSE_BY_ID.get(c["id"], c)
        pr = meta.get("prereqs") or []
        if catalog.prereqs_satisfied_tree(pr, allow):
            out.append(c)
            allow.add(c["id"])
    return out

