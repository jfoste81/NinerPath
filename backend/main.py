import uuid
from datetime import datetime, timezone, date, timedelta
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import asyncio
import json
import os
from itertools import combinations
import re
from typing import Optional, Any, Iterable

# Full-time floor and typical target for generated recommendations (credit hours)
SCHEDULE_TARGET_MIN_CREDITS = 12
SCHEDULE_TARGET_IDEAL_CREDITS = 15

# Class standing thresholds (earned credit hours). Used when student history has no explicit standing.
STANDING_ORDER = ("Freshman", "Sophomore", "Junior", "Senior")
STANDING_RANK = {name: i for i, name in enumerate(STANDING_ORDER)}
STANDING_THRESHOLDS = (
    (30, "Sophomore"),
    (60, "Junior"),
    (90, "Senior"),
)

# Load variables from the .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    # Vite default; include both hostnames so either URL in the browser works
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pull keys securely from the environment
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Helper to load JSON
def load_json(filename):
    with open(f"data/{filename}", "r") as file:
        return json.load(file)


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


def _saved_schedules_path() -> str:
    return os.path.join("data", "saved_schedules.json")


def _read_all_local_saved_schedules() -> list:
    path = _saved_schedules_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    rows = data.get("schedules") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def _course_ids_from_saved_payload(raw: Any) -> list:
    """Supabase uses jsonb `courses`; local fallback uses `course_ids`. Either may be a JSON string."""
    cids = raw
    if isinstance(cids, str):
        try:
            cids = json.loads(cids)
        except json.JSONDecodeError:
            cids = []
    if not isinstance(cids, list):
        return []
    out: list = []
    for x in cids:
        if isinstance(x, str):
            s = x.strip()
            if s:
                out.append(s)
        elif isinstance(x, dict):
            cid = str(x.get("id") or x.get("course_id") or "").strip()
            if cid:
                out.append(cid)
    return out


def _normalize_saved_schedule_row(row: dict) -> dict:
    out = dict(row) if isinstance(row, dict) else {}
    cids = out.get("course_ids")
    if cids is None:
        cids = out.get("courses")
    out["course_ids"] = _course_ids_from_saved_payload(cids)
    term = (out.get("term") or out.get("term_label") or "").strip()
    out["term"] = term
    if not out.get("created_at"):
        out["created_at"] = str(out.get("inserted_at") or out.get("created_at") or "")
    if not out.get("id"):
        out["id"] = str(out.get("uuid") or uuid.uuid4())
    return out


def _local_schedules_for_user(user_id: str) -> list:
    uid = (user_id or "").strip()
    if not uid:
        return []
    return [_normalize_saved_schedule_row(r) for r in _read_all_local_saved_schedules() if str(r.get("user_id", "")).strip() == uid]


async def _list_saved_schedules_async(user_id: str) -> list:
    merged: list = []
    seen_ids: set = set()
    if supabase:
        try:

            def _fetch():
                return supabase.table("saved_schedules").select("*").eq("user_id", user_id).execute()

            response = await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=8.0)
            for row in response.data or []:
                norm = _normalize_saved_schedule_row(row)
                rid = norm.get("id")
                if rid:
                    seen_ids.add(str(rid))
                merged.append(norm)
        except (asyncio.TimeoutError, Exception):
            pass
    for norm in _local_schedules_for_user(user_id):
        rid = str(norm.get("id") or "")
        if rid and rid in seen_ids:
            continue
        merged.append(norm)
    merged.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return _dedupe_saved_rows_latest_per_term(merged)


def _latest_saved_course_ids_for_term(rows: list, term_label: str) -> set:
    tnorm = (term_label or "").strip()
    best = None
    best_key = ""
    for r in rows:
        if not isinstance(r, dict):
            continue
        term = (r.get("term") or r.get("term_label") or "").strip()
        if term != tnorm:
            continue
        ca = str(r.get("created_at") or "")
        if ca >= best_key:
            best_key = ca
            best = r
    if not best:
        return set()
    return set(best.get("course_ids") or [])


def _replace_local_saved_schedule_for_term(user_id: str, term_label: str, row: dict) -> None:
    """Keep at most one saved schedule per (user_id, term) in the local JSON store."""
    uid = (user_id or "").strip()
    tnorm = (term_label or "").strip()
    path = _saved_schedules_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {"schedules": []}
    if not isinstance(data, dict):
        data = {"schedules": []}
    schedules = data.setdefault("schedules", [])
    kept = []
    for existing in schedules:
        if not isinstance(existing, dict):
            continue
        eu = str(existing.get("user_id", "")).strip()
        et = (str(existing.get("term") or existing.get("term_label") or "")).strip()
        if eu == uid and et == tnorm:
            continue
        kept.append(existing)
    kept.append(row)
    data["schedules"] = kept
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _dedupe_saved_rows_latest_per_term(rows: list) -> list:
    """One row per term (latest created_at) so legacy duplicates do not clutter the UI."""
    best_by_term: dict = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        term = (r.get("term") or r.get("term_label") or "").strip() or "__no_term__"
        ca = str(r.get("created_at") or "")
        prev = best_by_term.get(term)
        if prev is None or ca >= str(prev.get("created_at") or ""):
            best_by_term[term] = r
    out = list(best_by_term.values())
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return out


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


async def _find_saved_schedule_row(user_id: str, schedule_id: str) -> Optional[dict]:
    uid = (user_id or "").strip()
    sid = str(schedule_id or "").strip()
    if not uid or not sid:
        return None
    rows = await _list_saved_schedules_async(uid)
    for r in rows:
        if str(r.get("id") or "") == sid:
            return r
    return None


def compute_dependent_counts(course_list):
    dependent_counts = {course["id"]: 0 for course in course_list}
    for course in course_list:
        for prereq in iter_prereq_course_ids(course.get("prereqs") or []):
            if prereq in dependent_counts:
                dependent_counts[prereq] += 1
    return dependent_counts


DEPENDENT_COUNTS = compute_dependent_counts(COURSES)
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

def parse_course_number(course_id):
    try:
        return int(course_id.split(" ")[1])
    except (IndexError, ValueError):
        return 9999


def _best_credit_subset_dp(course_dicts: list, cap: int) -> list:
    """0/1 knapsack: max credits <= cap (for larger required pools)."""
    n = len(course_dicts)
    if n == 0 or cap <= 0:
        return []
    dp = [[0] * (cap + 1) for _ in range(n + 1)]
    take = [[False] * (cap + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        w = course_dicts[i - 1]["credits"]
        for c in range(cap + 1):
            dp[i][c] = dp[i - 1][c]
            if c >= w:
                with_w = dp[i - 1][c - w] + w
                if with_w > dp[i][c]:
                    dp[i][c] = with_w
                    take[i][c] = True
    best_c = max(range(cap + 1), key=lambda c: (dp[n][c], c))
    res = []
    c = best_c
    for i in range(n, 0, -1):
        if take[i][c]:
            res.append(course_dicts[i - 1])
            c -= course_dicts[i - 1]["credits"]
    return res[::-1]


def _best_credit_subset(course_dicts: list, cap: int) -> list:
    """Pick 0/1 subset of course_dicts maximizing total credits without exceeding cap.
    Tie-break: higher credit sum wins; then more courses; then lexicographic ids."""
    n = len(course_dicts)
    if n == 0 or cap <= 0:
        return []
    if n > 22:
        return _best_credit_subset_dp(course_dicts, cap)
    best_pick = []
    best_sum = -1
    best_tie = ()
    for mask in range(1 << n):
        total = 0
        pick = []
        for i in range(n):
            if mask >> i & 1:
                w = course_dicts[i]["credits"]
                if total + w > cap:
                    total = cap + 1
                    break
                total += w
                pick.append(course_dicts[i])
        if total > cap:
            continue
        tie = (len(pick), tuple(sorted(c["id"] for c in pick)))
        if total > best_sum or (total == best_sum and tie > best_tie):
            best_sum = total
            best_tie = tie
            best_pick = pick
    return best_pick


def _strict_prereq_filter(course_dicts: list, completed_ids: set) -> list:
    """Prereqs must appear in academic history only (not satisfied by co-recommended courses)."""
    out = []
    done = set(completed_ids)
    for c in course_dicts:
        cid = c["id"]
        meta = COURSE_BY_ID.get(cid, c)
        prereqs = meta.get("prereqs") or []
        if prereqs_satisfied_tree(prereqs, done):
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
        meta = COURSE_BY_ID.get(c["id"], c)
        pr = meta.get("prereqs") or []
        if prereqs_satisfied_tree(pr, allow):
            out.append(c)
            allow.add(c["id"])
    return out


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
    raw_candidates: list = []
    for r in range(max_e + 1):
        for idxs in combinations(range(len(elec_list)), r):
            elec_pick = [elec_list[i] for i in idxs]
            used_e = sum(c["credits"] for c in elec_pick)
            if used_e > schedule_cap:
                continue
            req_pick = _best_credit_subset(req_list, schedule_cap - used_e)
            bundle = elec_pick + req_pick
            total = sum(c["credits"] for c in bundle)
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

@app.get("/api/dashboard/{user_id}")
async def get_dashboard_data(
    user_id: str,
    email: str,
    degree: str = "bs_computer_science",
    concentration: str = "systems_and_networks",
    max_schedule_variants: int = 12,
):
    """Fetches history dynamically based on email, and saved schedules based on user_id."""
    
    # Get dynamic mock history from JSON using the email
    history_data = load_json("student_history.json")
    
    # If the email isn't in our JSON, give them a blank slate instead of crashing
    default_history = {"completed_courses": [], "gpa": 0.0}
    student_history = history_data.get(email, default_history)
    if degree not in DEGREE_PLANS:
        degree = "bs_computer_science"
    plan_meta = DEGREE_PLANS[degree]
    if concentration not in plan_meta["concentrations"]:
        concentration = plan_meta.get("default_concentration", "systems_and_networks")
    
    upcoming_schedules = await _list_saved_schedules_async(user_id)

    eff_label, eff_season = registration_schedule_term()
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}
    sp = student_history.get("schedule_preferences") if isinstance(student_history.get("schedule_preferences"), dict) else {}
    generated_schedule = generate_schedule(
        completed_ids=completed_ids,
        concentration=concentration,
        target_term=eff_season,
        max_credits=15,
        degree_key=degree,
        term_label=eff_label,
        class_standing_override=student_history.get("class_standing"),
        schedule_preferences=sp,
    )
    cap = max(1, min(max_schedule_variants, 24))
    attach_variants_to_combination_options(generated_schedule, eff_label, cap)

    return {
        "history": student_history,
        "upcoming": upcoming_schedules,
        "mock_generated_schedule": generated_schedule,
    }

@app.get("/api/degree-audit")
async def get_degree_audit(
    email: str,
    degree: str = "bs_computer_science",
    concentration: str = "systems_and_networks",
    user_id: Optional[str] = None,
):
    """Degree progress table data (completed vs remaining) for the landing audit view."""
    history_data = load_json("student_history.json")
    student_history = history_data.get(email, {"completed_courses": [], "gpa": 0.0})
    if degree not in DEGREE_PLANS:
        degree = "bs_computer_science"
    plan_meta = DEGREE_PLANS[degree]
    if concentration not in plan_meta["concentrations"]:
        concentration = plan_meta.get("default_concentration", "systems_and_networks")
    planned: set = set()
    uid = (user_id or "").strip()
    if uid:
        rows = await _list_saved_schedules_async(uid)
        planned = _latest_saved_course_ids_for_term(rows, REGISTRATION_TERM_LABEL)
    audit = build_degree_audit(degree, concentration, student_history, planned_ids=planned)
    return {"email": email, "degree": degree, "concentration": concentration, "audit": audit}


@app.get("/api/student/schedule-preferences")
async def get_schedule_preferences(email: str):
    """Load saved schedule preferences (e.g. blocked meeting times) for a student email."""
    em = str(email or "").strip()
    if not em:
        raise HTTPException(status_code=400, detail="email is required.")
    history_data = load_json("student_history.json")
    row = history_data.get(em)
    sp = {}
    if isinstance(row, dict):
        sp = row.get("schedule_preferences") or {}
    if not isinstance(sp, dict):
        sp = {}
    return {"email": em, "schedule_preferences": sp}


@app.post("/api/student/schedule-preferences")
async def save_schedule_preferences(payload: dict = Body(...)):
    """Persist schedule preferences into student_history.json (mock/local store)."""
    email = str(payload.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="email is required.")
    windows = payload.get("blocked_time_windows")
    if windows is not None and not isinstance(windows, list):
        raise HTTPException(status_code=400, detail="blocked_time_windows must be a list or omitted.")
    path = os.path.join("data", "student_history.json")
    history_data = load_json("student_history.json")
    if not isinstance(history_data, dict):
        history_data = {}
    row = history_data.get(email)
    if not isinstance(row, dict):
        row = {"completed_courses": []}
    sp = row.get("schedule_preferences") if isinstance(row.get("schedule_preferences"), dict) else {}
    if windows is not None:
        if windows:
            sp = {**sp, "blocked_time_windows": windows}
        else:
            sp = {k: v for k, v in sp.items() if k != "blocked_time_windows"}
    row["schedule_preferences"] = sp
    history_data[email] = row
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=2)
    return {"ok": True, "email": email, "schedule_preferences": sp}


@app.post("/api/schedules/save")
async def save_schedule(payload: dict = Body(...)):
    """Persist a Fall plan for the degree audit (Supabase when configured, else local JSON)."""
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required.")
    raw_ids = payload.get("course_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=400, detail="course_ids must be a non-empty list.")
    course_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
    if not course_ids:
        raise HTTPException(status_code=400, detail="course_ids must contain at least one course id.")
    term_label = str(payload.get("term_label") or REGISTRATION_TERM_LABEL).strip() or REGISTRATION_TERM_LABEL
    try:
        variant_index = int(payload.get("variant_index", 0))
    except (TypeError, ValueError):
        variant_index = 0
    try:
        combination_index = int(payload.get("combination_index", 0))
    except (TypeError, ValueError):
        combination_index = 0
    now = datetime.now(timezone.utc).isoformat()
    saved_row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "term": term_label,
        "course_ids": course_ids,
        "variant_index": variant_index,
        "combination_index": combination_index,
        "created_at": now,
    }
    if supabase:
        try:
            # Table schema: id, user_id, term, courses (jsonb), created_at — one active plan per term per user
            insert_payload = {
                "user_id": user_id,
                "term": term_label,
                "courses": course_ids,
            }

            def _replace_and_insert():
                supabase.table("saved_schedules").delete().eq("user_id", user_id).eq("term", term_label).execute()
                return supabase.table("saved_schedules").insert(insert_payload).execute()

            await asyncio.wait_for(asyncio.to_thread(_replace_and_insert), timeout=8.0)
            return {"ok": True, "source": "supabase", "saved": saved_row}
        except (asyncio.TimeoutError, Exception):
            pass
    _replace_local_saved_schedule_for_term(user_id, term_label, saved_row)
    return {"ok": True, "source": "local", "saved": saved_row}


@app.get("/api/schedules/{schedule_id}/export.ics")
async def export_saved_schedule_ics(
    schedule_id: str,
    user_id: str,
    email: Optional[str] = None,
):
    """
    Download an iCalendar (.ics) file for a saved schedule. Import into Google Calendar via
    File → Import (web) or calendar Settings → Import & export.

    Section times come from mock offerings; recurrence uses illustrative Fall 2026 dates.
    Pass the same email used in NinerPath so blocked-time preferences can match the saved variant when possible.
    """
    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required.")
    row = await _find_saved_schedule_row(uid, schedule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Saved schedule not found.")
    course_ids = list(row.get("course_ids") or [])
    if not course_ids:
        raise HTTPException(status_code=400, detail="No courses in this saved schedule.")
    term_label = (row.get("term") or row.get("term_label") or REGISTRATION_TERM_LABEL).strip() or REGISTRATION_TERM_LABEL
    try:
        variant_index = int(row.get("variant_index") or 0)
    except (TypeError, ValueError):
        variant_index = 0
    variant_index = max(0, variant_index)

    blocked: list = []
    em = str(email or "").strip()
    if em:
        hist = load_json("student_history.json").get(em)
        if isinstance(hist, dict):
            sp = hist.get("schedule_preferences") or {}
            if isinstance(sp, dict):
                blocked = normalize_blocked_time_windows(sp.get("blocked_time_windows"))

    max_v = max(32, variant_index + 12)
    built = build_schedule_variants(course_ids, term_label, max_variants=max_v, blocked_windows=blocked or None)
    variants = built.get("variants") or []
    if not variants and blocked:
        built = build_schedule_variants(course_ids, term_label, max_variants=max_v, blocked_windows=None)
        variants = built.get("variants") or []
    if not variants:
        raise HTTPException(
            status_code=404,
            detail="Could not build a conflict-free weekly layout from mock section data for these courses.",
        )
    vi = min(variant_index, len(variants) - 1)
    sections = variants[vi].get("sections") or []
    if not sections:
        raise HTTPException(status_code=404, detail="No section rows available for export.")
    ics_body = build_schedule_ics_document(sections, term_label, calendar_title=f"NinerPath — {term_label}")
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", term_label.strip()).strip("-").lower() or "schedule"
    filename = f"ninerpath-{safe}.ics"
    return Response(
        content=ics_body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/degree-plans")
async def get_degree_plans():
    return DEGREE_PLANS

@app.get("/api/geneds/{email}")
async def get_gen_ed_status(email: str):
    history_data = load_json("student_history.json")
    
    student_history = history_data.get(email)
    if not student_history:
        raise HTTPException(status_code=404, detail="Student not found")

    return {
        "email": email,
        "gen_ed_progress": get_gen_ed_progress(student_history, GEN_EDS)
    }


@app.get("/api/offerings/fall-2026")
async def get_fall_2026_offerings():
    return _fall_26_offerings


@app.get("/api/schedule/generate")
async def auto_generate_schedule(
    email: str,
    degree: str = "bs_computer_science",
    concentration: str = "systems_and_networks",
    max_credits: int = 15,
    max_schedule_variants: int = 12,
):
    if max_credits <= 0:
        raise HTTPException(status_code=400, detail="max_credits must be greater than 0.")

    history_data = load_json("student_history.json")
    student_history = history_data.get(email, {"completed_courses": []})
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}
    sp = student_history.get("schedule_preferences") if isinstance(student_history.get("schedule_preferences"), dict) else {}

    if degree not in DEGREE_PLANS:
        degree = "bs_computer_science"
    plan_meta = DEGREE_PLANS[degree]
    if concentration not in plan_meta["concentrations"]:
        concentration = plan_meta.get("default_concentration", "systems_and_networks")

    eff_label, eff_season = registration_schedule_term()
    schedule = generate_schedule(
        completed_ids=completed_ids,
        concentration=concentration,
        target_term=eff_season,
        max_credits=max_credits,
        degree_key=degree,
        term_label=eff_label,
        class_standing_override=student_history.get("class_standing"),
        schedule_preferences=sp,
    )
    cap = max(1, min(max_schedule_variants, 24))
    attach_variants_to_combination_options(schedule, eff_label, cap)

    return {
        "email": email,
        "completed_course_count": len(completed_ids),
        "inferred_term": eff_label,
        "schedule": schedule,
    }


# run with: uvicorn main:app --reload
