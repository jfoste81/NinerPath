"""Schedule generation, section variants, calendar/ICS helpers"""
from __future__ import annotations

import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Iterable, Optional

# Phase 4: cap exhaustive elective r-subsets (sum_k C(n,k) grows rapidly in n and r).
ELECTIVE_COMBINATION_POOL_MAX = 16
ELECTIVE_COMBINATION_ENUM_BUDGET = 10_000

from fastapi import HTTPException

import catalog
import degree_plan
from catalog import (
    COURSE_BY_ID,
    DEPENDENT_COUNTS,
    DEGREE_PLANS,
    OFFERINGS_BY_TERM_LABEL,
    _catalog_credits,
    _effective_plan_root,
    _gen_ed_deficit_catalog_course_ids,
    effective_class_standing,
    parse_course_number,
    prereqs_satisfied_tree,
    standing_satisfies_min,
)
from degree_plan import (
    normalize_degree_plan_for_schedule,
    _schedule_bundle_prereq_filter,
    _strict_prereq_filter,
)
from models import SCHEDULE_TARGET_IDEAL_CREDITS, SCHEDULE_TARGET_MIN_CREDITS

_fall_26_offerings = catalog._fall_26_offerings


DAY_CODE_TO_INDEX = {"M": 1, "T": 2, "W": 3, "R": 4, "F": 5, "S": 6}


def expand_meeting_days(days_str: str) -> list:
    if not days_str:
        return []
    return [DAY_CODE_TO_INDEX[c] for c in days_str.strip().upper() if c in DAY_CODE_TO_INDEX]


def parse_clock_to_minutes(clock: str) -> int:
    clock = clock.strip().upper()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", clock)
    if not m:
        return 0
    hour, minute, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    if ap == "PM" and hour != 12:
        hour += 12
    if ap == "AM" and hour == 12:
        hour = 0
    return hour * 60 + minute


def parse_meeting_window(time_field: str) -> tuple:
    if "-" not in time_field:
        return 0, 0
    left, right = [p.strip() for p in time_field.split("-", 1)]
    return parse_clock_to_minutes(left), parse_clock_to_minutes(right)


def section_time_slots(section: dict) -> list:
    days = expand_meeting_days(section.get("days", ""))
    start_m, end_m = parse_meeting_window(section.get("time", ""))
    return [(d, start_m, end_m) for d in days]


def _parse_flexible_time_to_minutes(s: str) -> int:
    """Parse '8:00 AM', '10:50 PM', or '14:30' into minutes from midnight; -1 if unusable."""
    s = (s or "").strip()
    if not s:
        return -1
    if re.search(r"\b(AM|PM)\b", s, re.I):
        return parse_clock_to_minutes(s)
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
    if not m:
        return -1
    hour = int(m.group(1)) % 24
    minute = int(m.group(2))
    return hour * 60 + min(max(minute, 0), 59)


_WEEKDAY_INDEX_TO_LETTER = {1: "M", 2: "T", 3: "W", 4: "R", 5: "F", 6: "S"}


def _weekday_indices_to_day_string(indices: list) -> str:
    return "".join(_WEEKDAY_INDEX_TO_LETTER[i] for i in sorted(indices) if i in _WEEKDAY_INDEX_TO_LETTER)


def _minutes_to_ampm(m: int) -> str:
    m = max(0, m)
    h24, mi = divmod(m, 60)
    if h24 == 0:
        h, ap = 12, "AM"
    elif 1 <= h24 <= 11:
        h, ap = h24, "AM"
    elif h24 == 12:
        h, ap = 12, "PM"
    else:
        h, ap = h24 - 12, "PM"
    return f"{h}:{mi:02d} {ap}"


def normalize_blocked_time_windows(raw: Any) -> list:
    """
    Student preference rows: { "days": "MWF" | "TR", "start": "8:00 AM"|"08:00", "end": "12:00 PM" }.
    Returns JSON-serializable dicts: weekdays (sorted indices 1–6), start_minutes, end_minutes.
    """
    if not raw or not isinstance(raw, list):
        return []
    out: list = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        days_s = str(item.get("days") or "").strip().upper()
        idxs = sorted(set(expand_meeting_days(days_s)))
        if not idxs:
            continue
        sm = _parse_flexible_time_to_minutes(str(item.get("start") or ""))
        em = _parse_flexible_time_to_minutes(str(item.get("end") or ""))
        if sm < 0 or em < 0:
            continue
        if em <= sm:
            sm, em = em, sm
            if em <= sm:
                continue
        out.append({"weekdays": idxs, "start_minutes": sm, "end_minutes": em})
    return out


def summarize_blocked_time_windows(norm: list) -> list:
    """Human-readable summary for API clients."""
    rows = []
    for blk in norm:
        if not isinstance(blk, dict):
            continue
        w = blk.get("weekdays") or []
        if not isinstance(w, list):
            continue
        rows.append(
            {
                "days": _weekday_indices_to_day_string([int(x) for x in w]),
                "start": _minutes_to_ampm(int(blk.get("start_minutes", 0))),
                "end": _minutes_to_ampm(int(blk.get("end_minutes", 0))),
                "start_minutes": int(blk.get("start_minutes", 0)),
                "end_minutes": int(blk.get("end_minutes", 0)),
            }
        )
    return rows


def section_hits_blocked_times(section: dict, blocked_windows: Optional[list]) -> bool:
    if not blocked_windows:
        return False
    for day, sm, em in section_time_slots(section):
        for blk in blocked_windows:
            if day not in (blk.get("weekdays") or []):
                continue
            bsm = int(blk.get("start_minutes", 0))
            bem = int(blk.get("end_minutes", 0))
            if sm < bem and bsm < em:
                return True
    return False


def slots_overlap(a, b) -> bool:
    da, sa, ea = a
    db, sb, eb = b
    return da == db and sa < eb and sb < ea


def sections_conflict(sec_a: dict, sec_b: dict) -> bool:
    for pa in section_time_slots(sec_a):
        for pb in section_time_slots(sec_b):
            if slots_overlap(pa, pb):
                return True
    return False


def bundle_conflicts_with(picked: list, sec: dict) -> bool:
    return any(sections_conflict(p, sec) for p in picked)


def enrich_section_for_calendar(sec: dict, color_index: int) -> dict:
    blocks = []
    for weekday, sm, em in section_time_slots(sec):
        blocks.append(
            {"weekday": weekday, "start_minutes": sm, "end_minutes": em}
        )
    out = dict(sec)
    out["calendar_blocks"] = blocks
    out["color_index"] = color_index
    return out


def _resolve_calendar_sections_term(requested_label: Optional[str]) -> Optional[str]:
    """Pick which mock offerings file key to use for section times (calendar layout)."""
    if not OFFERINGS_BY_TERM_LABEL:
        return None
    if requested_label and requested_label in OFFERINGS_BY_TERM_LABEL:
        return requested_label
    return next(iter(OFFERINGS_BY_TERM_LABEL.keys()))


def build_schedule_variants(
    recommended_course_ids_ordered: list,
    term_label: Optional[str],
    max_variants: int = 10,
    blocked_windows: Optional[list] = None,
) -> dict:
    """
    Non-conflicting section combinations using mock section rows (fall_2026_offerings.json).

    Only courses that appear in the mock catalog get calendar rows. Recommended courses without
    mock sections are omitted from the DFS (listed in omitted_course_ids) so other concentrations
    still get a calendar when possible.

    If the requested term_label has no offerings entry (e.g. Spring 2026), we still use the
    available mock catalog (e.g. Fall 2026) for meeting times—illustrative only.
    """
    calendar_term = _resolve_calendar_sections_term(term_label)
    if not calendar_term:
        return {
            "variants": [],
            "sections_term_label": None,
            "omitted_course_ids": list(recommended_course_ids_ordered),
        }

    sections = _fall_26_offerings.get("sections", [])
    by_course = {}
    for sec in sections:
        cid = sec.get("course_id")
        if not cid:
            continue
        by_course.setdefault(cid, []).append(sec)

    omitted = [c for c in recommended_course_ids_ordered if c not in by_course or not by_course[c]]
    schedulable = [c for c in recommended_course_ids_ordered if c in by_course and by_course[c]]
    if not schedulable:
        return {
            "variants": [],
            "sections_term_label": calendar_term,
            "omitted_course_ids": omitted,
        }

    search_order = sorted(schedulable, key=lambda c: len(by_course[c]))
    cid_rank = {c: j for j, c in enumerate(recommended_course_ids_ordered)}
    variants = []

    def dfs(i: int, picked: list) -> None:
        if len(variants) >= max_variants:
            return
        if i >= len(search_order):
            ordered_pick = sorted(picked, key=lambda s: cid_rank[s["course_id"]])
            enriched = [
                enrich_section_for_calendar(s, cid_rank[s["course_id"]])
                for s in ordered_pick
            ]
            variants.append({"variant_id": len(variants) + 1, "sections": enriched})
            return
        cid = search_order[i]
        for sec in by_course[cid]:
            if bundle_conflicts_with(picked, sec):
                continue
            if section_hits_blocked_times(sec, blocked_windows):
                continue
            dfs(i + 1, picked + [sec])

    dfs(0, [])
    return {
        "variants": variants,
        "sections_term_label": calendar_term,
        "omitted_course_ids": omitted,
    }


def bundle_has_feasible_meeting_layout(
    course_ids_ordered: list,
    term_label: Optional[str],
    blocked_windows: Optional[list] = None,
) -> bool:
    """
    True when mock offerings admit at least one pairwise non-overlapping section assignment for
    courses that have section rows. If every course is omitted from the calendar (no mock sections),
    the bundle is still accepted. When no term catalog is available, do not block generation.
    """
    built = build_schedule_variants(course_ids_ordered, term_label, max_variants=1, blocked_windows=blocked_windows)
    if built["variants"]:
        return True
    if not _resolve_calendar_sections_term(term_label):
        return True
    omitted_set = set(built["omitted_course_ids"])
    return all(cid in omitted_set for cid in course_ids_ordered)


def attach_schedule_variants(
    schedule_dict: dict,
    term_label: Optional[str],
    max_variants: int = 10,
    blocked_windows: Optional[list] = None,
):
    courses = schedule_dict.get("recommended_courses") or []
    order = [c["id"] for c in courses]
    bw = blocked_windows if blocked_windows is not None else schedule_dict.get("blocked_time_windows_normalized")
    built = build_schedule_variants(order, term_label, max_variants, blocked_windows=bw)
    schedule_dict["schedule_variants"] = built["variants"]
    schedule_dict["schedule_calendar_sections_term"] = built["sections_term_label"]
    schedule_dict["schedule_calendar_omitted_courses"] = built["omitted_course_ids"]
    return schedule_dict


def attach_variants_to_combination_options(schedule_dict: dict, term_label: Optional[str], max_variants: int = 10) -> None:
    """Build calendar variants per class combination; mirror first combo onto the root schedule for legacy fields."""
    opts = schedule_dict.get("combination_options") or []
    bw = schedule_dict.get("blocked_time_windows_normalized")
    if not opts:
        attach_schedule_variants(schedule_dict, term_label, max_variants, blocked_windows=bw)
        return
    for opt in opts:
        attach_schedule_variants(opt, term_label, max_variants, blocked_windows=bw)
    first = opts[0]
    schedule_dict["schedule_variants"] = list(first.get("schedule_variants") or [])
    schedule_dict["schedule_calendar_sections_term"] = first.get("schedule_calendar_sections_term")
    schedule_dict["schedule_calendar_omitted_courses"] = list(first.get("schedule_calendar_omitted_courses") or [])


def _elective_combo_max_r(n_pool: int, desired_max_r: int, budget: int) -> int:
    """Largest r in [0, min(desired_max_r, n_pool)] with sum_{k=0}^{r} C(n_pool, k) <= budget."""
    if n_pool <= 0 or budget < 1:
        return 0
    desired_max_r = min(max(0, desired_max_r), n_pool)
    for r in range(desired_max_r, -1, -1):
        total = sum(math.comb(n_pool, k) for k in range(r + 1))
        if total <= budget:
            return r
    return 0


def _best_credit_subset(course_dicts: list, cap: int) -> list:
    """Pick 0/1 subset of course_dicts maximizing total credits without exceeding cap.

    0/1 knapsack via dynamic programming, O(n * cap). Tie-break on equal total credits:
    prefer more courses; then prefer a tighter fit (higher usable capacity index), matching
    prior behavior where possible. Non-positive credit rows are always included (no cap cost).
    """
    if not course_dicts or cap <= 0:
        return []
    cap_i = max(0, int(cap))
    zeros: list = []
    pos: list = []
    weights: list = []
    for c in course_dicts:
        w = int(c.get("credits") or 0)
        if w <= 0:
            zeros.append(dict(c))
        else:
            pos.append(dict(c))
            weights.append(w)
    n_p = len(pos)
    if n_p == 0:
        return zeros

    # dp[i][c] = (total_credits, course_count) best using first i positive-weight courses, budget c
    dp: list = [[(0, 0)] * (cap_i + 1) for _ in range(n_p + 1)]
    take = [[False] * (cap_i + 1) for _ in range(n_p + 1)]
    for i in range(1, n_p + 1):
        w = weights[i - 1]
        for c in range(cap_i + 1):
            skip = dp[i - 1][c]
            best = skip
            took = False
            if c >= w:
                ps, pc = dp[i - 1][c - w]
                cand = (ps + w, pc + 1)
                if cand > best:
                    best = cand
                    took = True
            dp[i][c] = best
            take[i][c] = took

    best_c = max(range(cap_i + 1), key=lambda c: (dp[n_p][c], c))
    res: list = []
    c = best_c
    for i in range(n_p, 0, -1):
        if take[i][c]:
            res.append(pos[i - 1])
            c -= weights[i - 1]
    res = res[::-1] + zeros
    return res


def generate_schedule(
    completed_ids,
    concentration,
    target_term,
    max_credits,
    degree_key: str = "bs_computer_science",
    target_min_credits: int = SCHEDULE_TARGET_MIN_CREDITS,
    target_ideal_credits: int = SCHEDULE_TARGET_IDEAL_CREDITS,
    term_label: Optional[str] = None,
    class_standing_override: Optional[str] = None,
    max_combinations: int = 3,
    schedule_preferences: Optional[dict] = None,
):
    sprefs = schedule_preferences if isinstance(schedule_preferences, dict) else None
    blocked_norm = normalize_blocked_time_windows((sprefs or {}).get("blocked_time_windows"))

    plan_root = _effective_plan_root(degree_key)
    if not plan_root or not plan_root.get("concentrations"):
        raise HTTPException(status_code=400, detail=f"Unknown degree plan '{degree_key}'.")
    concentrations = plan_root["concentrations"]
    if concentration not in concentrations:
        raise HTTPException(status_code=400, detail=f"Unknown concentration '{concentration}' for {degree_key}.")

    raw_conc = concentrations[concentration]
    sched = normalize_degree_plan_for_schedule(plan_root, concentration, raw_conc)
    req_ids = sched["required_course_ids"]
    elec_ids = sched["elective_pool_ids"]
    max_elective_picks = sched["max_elective_picks"]
    concentration_label = sched["concentration_label"]
    req_set = set(req_ids)

    required_courses = [course_id for course_id in req_ids if course_id not in completed_ids]
    elective_pool = [course_id for course_id in elec_ids if course_id not in completed_ids]

    completed_set = set(completed_ids)
    offerings_allowlist = OFFERINGS_BY_TERM_LABEL.get(term_label) if term_label else None
    student_standing = effective_class_standing(completed_set, class_standing_override)

    def is_eligible(course):
        offered = course.get("offered_in", ["Fall", "Spring"])
        if course["id"] in completed_set:
            return False
        if target_term not in offered and "Both" not in offered:
            return False
        if not prereqs_satisfied_tree(course.get("prereqs") or [], completed_set):
            return False
        if not standing_satisfies_min(student_standing, course.get("min_standing")):
            return False
        if offerings_allowlist is not None and course["id"] not in offerings_allowlist:
            return False
        return True

    elec_set = set(elec_ids)

    def is_elective(course_id):
        return course_id in elec_set and course_id not in req_set

    def sort_key_tuple(course_id):
        return (
            0 if course_id in req_set else 1,
            -DEPENDENT_COUNTS.get(course_id, 0),
            parse_course_number(course_id),
        )

    req_list = []
    seen_req = set()
    for course_id in sorted(required_courses, key=sort_key_tuple):
        course = COURSE_BY_ID.get(course_id)
        if not course or not is_eligible(course):
            continue
        if course_id in seen_req:
            continue
        seen_req.add(course_id)
        req_list.append(dict(course))

    elec_list = []
    seen_e = set()
    for course_id in sorted(elective_pool, key=sort_key_tuple):
        course = COURSE_BY_ID.get(course_id)
        if not course or not is_eligible(course):
            continue
        if course_id in seen_e:
            continue
        seen_e.add(course_id)
        elec_list.append(dict(course))

    # Include degree gen-ed options in the same search space as concentration electives (capped).
    _ge_pool_cap = 10
    _ge_added = 0
    for cid in _gen_ed_deficit_catalog_course_ids(completed_set):
        if _ge_added >= _ge_pool_cap:
            break
        if cid in seen_e or cid in req_set:
            continue
        course = COURSE_BY_ID.get(cid)
        if not course or not is_eligible(course):
            continue
        seen_e.add(cid)
        elec_list.append(dict(course))
        _ge_added += 1

    gen_ed_suggestions: list = []
    for cid in _gen_ed_deficit_catalog_course_ids(completed_set):
        course = COURSE_BY_ID.get(cid)
        if not course or not is_eligible(course):
            continue
        gen_ed_suggestions.append(
            {
                "id": course["id"],
                "name": course.get("name", cid),
                "credits": _catalog_credits(cid),
            }
        )

    schedule_cap = max(1, max_credits)
    max_combo = max(1, min(int(max_combinations or 3), 3))

    _extra_combo_slots = min(4, max(0, _ge_added))
    max_e = min(max_elective_picks + _extra_combo_slots, len(elec_list), 8)
    n_pool = min(len(elec_list), ELECTIVE_COMBINATION_POOL_MAX)
    elec_combo_pool = elec_list[:n_pool]
    max_r = _elective_combo_max_r(n_pool, max_e, ELECTIVE_COMBINATION_ENUM_BUDGET)

    raw_candidates: list = []
    combo_iters = 0
    stop_combo = False
    for r in range(max_r + 1):
        for idxs in combinations(range(n_pool), r):
            combo_iters += 1
            if combo_iters > ELECTIVE_COMBINATION_ENUM_BUDGET:
                stop_combo = True
                break
            elec_pick = [elec_combo_pool[i] for i in idxs]
            used_e = sum(int(c.get("credits") or 0) for c in elec_pick)
            if used_e > schedule_cap:
                continue
            req_pick = _best_credit_subset(req_list, schedule_cap - used_e)
            bundle = elec_pick + req_pick
            total = sum(int(c.get("credits") or 0) for c in bundle)
            if total <= 0:
                continue
            n_req = sum(1 for c in bundle if c["id"] in req_set)
            ideal = min(target_ideal_credits, schedule_cap)
            rank = (
                total > 0,
                total,
                -abs(total - ideal),
                n_req,
                len(bundle),
                tuple(sorted(c["id"] for c in bundle)),
            )
            raw_candidates.append((rank, [dict(c) for c in bundle]))
        if stop_combo:
            break

    raw_candidates.sort(key=lambda x: x[0], reverse=True)

    def order_for_display(c):
        cid = c["id"]
        if cid in req_set:
            return (0, req_ids.index(cid))
        if cid in elec_set:
            return (1, elec_ids.index(cid))
        return (2, cid)

    sk = lambda c: sort_key_tuple(c["id"])

    def greedy_fallback_pack():
        """If optimization returns nothing, still suggest whatever fits under the cap (may be <12 cr)."""
        picked = []
        tot = 0
        rem_e = max_elective_picks
        for c in sorted(req_list, key=sk):
            if tot + c["credits"] <= schedule_cap:
                picked.append(c)
                tot += c["credits"]
        for c in sorted(elec_list, key=sk):
            if rem_e <= 0:
                break
            if tot + c["credits"] <= schedule_cap:
                picked.append(c)
                tot += c["credits"]
                if is_elective(c["id"]):
                    rem_e -= 1
        return picked

    def finalize_from_base_bundle(base_bundle: list) -> dict:
        selected = sorted(base_bundle, key=order_for_display)
        total_credits = sum(c["credits"] for c in selected)
        if total_credits == 0 and (req_list or elec_list):
            g2 = greedy_fallback_pack()
            if g2:
                selected = sorted(g2, key=order_for_display)
                total_credits = sum(c["credits"] for c in selected)
        sel_ids = {c["id"] for c in selected}
        # Category order in gen_eds.json (Communication → …) so foundational gen eds fill first.
        for cid in _gen_ed_deficit_catalog_course_ids(completed_set):
            if cid in sel_ids:
                continue
            course = COURSE_BY_ID.get(cid)
            if not course or not is_eligible(course):
                continue
            dc = dict(course)
            if total_credits + dc["credits"] > schedule_cap:
                continue
            selected.append(dc)
            sel_ids.add(cid)
            total_credits += dc["credits"]
        selected = _schedule_bundle_prereq_filter(selected, completed_set)
        total_credits = sum(c["credits"] for c in selected)
        selected = sorted(selected, key=order_for_display)
        sel_ids = {c["id"] for c in selected}
        remaining_required = [cid for cid in required_courses if cid not in sel_ids]
        remaining_electives = [cid for cid in elective_pool if cid not in sel_ids]
        elective_slots_left = max_elective_picks - sum(1 for c in selected if is_elective(c["id"]))
        return {
            "generated_credits": total_credits,
            "meets_full_time_target": total_credits >= target_min_credits,
            "recommended_courses": selected,
            "remaining_required_count": len(remaining_required),
            "remaining_elective_count": min(len(remaining_electives), max(0, elective_slots_left)),
        }

    deduped_finalized: list = []
    seen_sets: set = set()
    for _rank, bundle in raw_candidates:
        key = frozenset(c["id"] for c in bundle)
        if key in seen_sets:
            continue
        part = finalize_from_base_bundle([dict(c) for c in bundle])
        core_ids = [c["id"] for c in bundle]
        if not bundle_has_feasible_meeting_layout(core_ids, term_label, blocked_norm):
            continue
        seen_sets.add(key)
        deduped_finalized.append(part)
        if len(deduped_finalized) >= max_combo:
            break

    if not deduped_finalized and (req_list or elec_list):
        g = greedy_fallback_pack()
        if g and sum(c["credits"] for c in g) > 0:
            part = finalize_from_base_bundle([dict(c) for c in g])
            core_ids = [c["id"] for c in g]
            if bundle_has_feasible_meeting_layout(core_ids, term_label, blocked_norm):
                deduped_finalized = [part]

    combination_options: list = []
    for i, part in enumerate(deduped_finalized):
        opt = dict(part)
        opt["combination_id"] = i + 1
        opt["combination_label"] = f"Combination {chr(ord('A') + i)}"
        combination_options.append(opt)

    meta = {
        "degree": plan_root["name"],
        "catalog_year": plan_root.get("catalog_year", ""),
        "concentration": concentration,
        "concentration_label": concentration_label,
        "target_term": target_term,
        "term_label": term_label,
        "max_credits": max_credits,
        "schedule_cap_applied": schedule_cap,
        "target_min_credits": target_min_credits,
        "target_ideal_credits": target_ideal_credits,
        "combination_options": combination_options,
        "gen_ed_suggestions": gen_ed_suggestions,
        "schedule_preferences": sprefs or {},
        "blocked_time_windows_applied": summarize_blocked_time_windows(blocked_norm),
        "blocked_time_windows_normalized": blocked_norm,
    }
    if not combination_options:
        return {
            **meta,
            "generated_credits": 0,
            "meets_full_time_target": False,
            "recommended_courses": [],
            "remaining_required_count": len(required_courses),
            "remaining_elective_count": min(len(elective_pool), max_elective_picks),
        }
    first = combination_options[0]
    return {
        **meta,
        "generated_credits": first["generated_credits"],
        "meets_full_time_target": first["meets_full_time_target"],
        "recommended_courses": first["recommended_courses"],
        "remaining_required_count": first["remaining_required_count"],
        "remaining_elective_count": first["remaining_elective_count"],
    }


ICAL_BYDAY_FROM_DAY_INDEX = {1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA"}
_DAY_INDEX_TO_PYTHON_WEEKDAY = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}


def _ical_text_escape(s: str) -> str:
    if not s:
        return ""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _ics_fold_property(name: str, value: str) -> str:
    line = f"{name}:{value}"
    if len(line) <= 75:
        return line
    parts = []
    rest = line
    first = True
    while rest:
        take = 73 if first else 74
        parts.append(rest[:take])
        rest = rest[take:]
        first = False
    return "\r\n ".join(parts)


def _export_term_first_class_date(term_label: Optional[str]) -> date:
    tl = (term_label or "").lower()
    if "spring" in tl and "2026" in tl:
        return date(2026, 1, 13)
    if "fall" in tl and "2026" in tl:
        return date(2026, 8, 24)
    return date(2026, 8, 24)


def _export_term_rrule_until(term_label: Optional[str]) -> str:
    """UNTIL in same floating local form as DTSTART (no Z). Approximate last class week."""
    tl = (term_label or "").lower()
    if "spring" in tl and "2026" in tl:
        return "20260501T235900"
    return "20261205T235900"


def _first_calendar_date_on_or_after(term_start: date, day_index: int) -> date:
    wd = _DAY_INDEX_TO_PYTHON_WEEKDAY.get(day_index)
    if wd is None:
        return term_start
    d = term_start
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


def _fmt_ics_local_datetime(d: date, minutes_from_midnight: int) -> str:
    m = max(0, int(minutes_from_midnight))
    hh, mm = divmod(m, 60)
    return f"{d.year:04d}{d.month:02d}{d.day:02d}T{hh:02d}{mm:02d}00"


def build_schedule_ics_document(
    enriched_sections: list,
    term_label: Optional[str],
    calendar_title: str = "NinerPath schedule",
) -> str:
    """
    Build iCalendar text from enriched section rows (calendar_blocks or raw days/time).
    Uses illustrative semester dates for Fall 2026 mock data; adjust in calendar after import if needed.
    """
    term_start = _export_term_first_class_date(term_label)
    until_part = _export_term_rrule_until(term_label)
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UNC Charlotte//NinerPath//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        _ics_fold_property("X-WR-CALNAME", _ical_text_escape(calendar_title)),
    ]
    for sec in enriched_sections:
        if not isinstance(sec, dict):
            continue
        cid = str(sec.get("course_id") or "").strip()
        cat = COURSE_BY_ID.get(cid) or {}
        title = str(sec.get("title") or cat.get("name") or cid)
        loc = str(sec.get("location") or "")
        instr = str(sec.get("instructor") or "")
        blocks = sec.get("calendar_blocks")
        if not blocks:
            blocks = []
            for wd, sm, em in section_time_slots(sec):
                blocks.append({"weekday": wd, "start_minutes": sm, "end_minutes": em})
        if not blocks:
            continue
        for blk in blocks:
            if not isinstance(blk, dict):
                continue
            di = int(blk.get("weekday", 0))
            sm = int(blk.get("start_minutes", 0))
            em = int(blk.get("end_minutes", 0))
            if em <= sm:
                continue
            byday = ICAL_BYDAY_FROM_DAY_INDEX.get(di)
            if not byday:
                continue
            first_d = _first_calendar_date_on_or_after(term_start, di)
            dtstart = _fmt_ics_local_datetime(first_d, sm)
            dtend = _fmt_ics_local_datetime(first_d, em)
            summary = _ical_text_escape(f"{cid} — {title}")
            desc_parts = [f"Course: {cid}", f"Title: {title}"]
            if instr:
                desc_parts.append(f"Instructor: {instr}")
            desc_parts.append("Imported from NinerPath (mock section times).")
            desc = _ical_text_escape("\n".join(desc_parts))
            loc_esc = _ical_text_escape(loc) if loc else ""
            uid = f"{uuid.uuid4()}@ninerpath.local"
            out_lines.append("BEGIN:VEVENT")
            out_lines.append(_ics_fold_property("UID", uid))
            out_lines.append(_ics_fold_property("DTSTAMP", dtstamp))
            out_lines.append(_ics_fold_property("DTSTART", dtstart))
            out_lines.append(_ics_fold_property("DTEND", dtend))
            out_lines.append(_ics_fold_property("RRULE", f"FREQ=WEEKLY;BYDAY={byday};UNTIL={until_part}"))
            out_lines.append(_ics_fold_property("SUMMARY", summary))
            if loc_esc:
                out_lines.append(_ics_fold_property("LOCATION", loc_esc))
            out_lines.append(_ics_fold_property("DESCRIPTION", desc))
            out_lines.append("END:VEVENT")
    out_lines.append("END:VCALENDAR")
    return "\r\n".join(out_lines) + "\r\n"
