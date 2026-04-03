from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import json
import os
from itertools import combinations
import re
from typing import Optional

# Full-time floor and typical target for generated recommendations (credit hours)
SCHEDULE_TARGET_MIN_CREDITS = 12
SCHEDULE_TARGET_IDEAL_CREDITS = 15

# Load variables from the .env file
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], 
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
DEGREE_PLANS = load_json("degree_plans.json")
GEN_EDS = load_json("gen_eds.json")

_fall_26_offerings = load_json("fall_2026_offerings.json")
# When scheduling for a label in this map, only those course_ids may be recommended.
OFFERINGS_BY_TERM_LABEL = {}
_tl = (_fall_26_offerings.get("term") or "").strip()
if _tl:
    OFFERINGS_BY_TERM_LABEL[_tl] = {
        s["course_id"]
        for s in _fall_26_offerings.get("sections", [])
        if s.get("course_id")
    }


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
            dfs(i + 1, picked + [sec])

    dfs(0, [])
    return {
        "variants": variants,
        "sections_term_label": calendar_term,
        "omitted_course_ids": omitted,
    }


def attach_schedule_variants(schedule_dict: dict, term_label: Optional[str], max_variants: int = 10):
    courses = schedule_dict.get("recommended_courses") or []
    order = [c["id"] for c in courses]
    built = build_schedule_variants(order, term_label, max_variants)
    schedule_dict["schedule_variants"] = built["variants"]
    schedule_dict["schedule_calendar_sections_term"] = built["sections_term_label"]
    schedule_dict["schedule_calendar_omitted_courses"] = built["omitted_course_ids"]
    return schedule_dict


def compute_dependent_counts(course_list):
    dependent_counts = {course["id"]: 0 for course in course_list}
    for course in course_list:
        for prereq in course.get("prereqs", []):
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
        if all(p in done for p in prereqs):
            out.append(c)
    return out


def generate_schedule(
    completed_ids,
    concentration,
    target_term,
    max_credits,
    degree_key: str = "bs_computer_science",
    target_min_credits: int = SCHEDULE_TARGET_MIN_CREDITS,
    target_ideal_credits: int = SCHEDULE_TARGET_IDEAL_CREDITS,
    term_label: Optional[str] = None,
):
    plan_root = DEGREE_PLANS.get(degree_key)
    if not plan_root:
        raise HTTPException(status_code=400, detail=f"Unknown degree plan '{degree_key}'.")
    concentrations = plan_root["concentrations"]
    if concentration not in concentrations:
        raise HTTPException(status_code=400, detail=f"Unknown concentration '{concentration}' for {degree_key}.")

    plan = concentrations[concentration]
    required_courses = [course_id for course_id in plan["required_courses"] if course_id not in completed_ids]
    elective_pool = [course_id for course_id in plan["elective_pool"] if course_id not in completed_ids]

    max_elective_picks = max(0, plan.get("elective_count", 0))
    completed_set = set(completed_ids)
    offerings_allowlist = OFFERINGS_BY_TERM_LABEL.get(term_label) if term_label else None

    def is_eligible(course):
        offered = course.get("offered_in", ["Fall", "Spring"])
        prereqs = set(course.get("prereqs", []))
        if course["id"] in completed_set:
            return False
        if target_term not in offered and "Both" not in offered:
            return False
        if not prereqs.issubset(completed_set):
            return False
        if offerings_allowlist is not None and course["id"] not in offerings_allowlist:
            return False
        return True

    def is_elective(course_id):
        return course_id in plan["elective_pool"] and course_id not in plan["required_courses"]

    def sort_key_tuple(course_id):
        return (
            0 if course_id in plan["required_courses"] else 1,
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

    schedule_cap = max(1, max_credits)

    best_bundle = []
    best_rank = None
    max_e = min(max_elective_picks, len(elec_list))

    for r in range(max_e + 1):
        for idxs in combinations(range(len(elec_list)), r):
            elec_pick = [elec_list[i] for i in idxs]
            used_e = sum(c["credits"] for c in elec_pick)
            if used_e > schedule_cap:
                continue
            req_pick = _best_credit_subset(req_list, schedule_cap - used_e)
            bundle = elec_pick + req_pick
            total = sum(c["credits"] for c in bundle)
            n_req = sum(1 for c in bundle if c["id"] in plan["required_courses"])
            ideal = min(target_ideal_credits, schedule_cap)
            # Prefer any non-empty schedule over empty; then maximize credits toward schedule_cap;
            # then hug the ideal load on ties; then more required courses; then stable ids.
            rank = (
                total > 0,
                total,
                -abs(total - ideal),
                n_req,
                len(bundle),
                tuple(sorted(c["id"] for c in bundle)),
            )
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_bundle = bundle

    def order_for_display(c):
        cid = c["id"]
        if cid in plan["required_courses"]:
            return (0, plan["required_courses"].index(cid))
        if cid in plan["elective_pool"]:
            return (1, plan["elective_pool"].index(cid))
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

    selected = sorted(best_bundle, key=order_for_display)
    total_credits = sum(c["credits"] for c in selected)
    if total_credits == 0 and (req_list or elec_list):
        g = greedy_fallback_pack()
        if g:
            selected = sorted(g, key=order_for_display)
            total_credits = sum(c["credits"] for c in selected)
    selected = _strict_prereq_filter(selected, completed_set)
    total_credits = sum(c["credits"] for c in selected)
    sel_ids = {c["id"] for c in selected}

    remaining_required = [cid for cid in required_courses if cid not in sel_ids]
    remaining_electives = [cid for cid in elective_pool if cid not in sel_ids]
    elective_slots_left = max_elective_picks - sum(1 for c in selected if is_elective(c["id"]))

    return {
        "degree": plan_root["name"],
        "catalog_year": plan_root["catalog_year"],
        "concentration": concentration,
        "concentration_label": plan["label"],
        "target_term": target_term,
        "term_label": term_label,
        "max_credits": max_credits,
        "schedule_cap_applied": schedule_cap,
        "target_min_credits": target_min_credits,
        "target_ideal_credits": target_ideal_credits,
        "generated_credits": total_credits,
        "meets_full_time_target": total_credits >= target_min_credits,
        "recommended_courses": selected,
        "remaining_required_count": len(remaining_required),
        "remaining_elective_count": min(len(remaining_electives), max(0, elective_slots_left)),
    }

@app.get("/api/dashboard/{user_id}")
async def get_dashboard_data(
    user_id: str,
    email: str,
    degree: str = "bs_computer_science",
    concentration: str = "systems_and_networks",
    term_label: Optional[str] = None,
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
    
    # Get saved upcoming schedule from Supabase (this uses the real user_id)
    try:
        if supabase:
            response = supabase.table("saved_schedules").select("*").eq("user_id", user_id).execute()
            upcoming_schedules = response.data
        else:
            upcoming_schedules = []
    except Exception as e:
        upcoming_schedules = []

    eff_label, eff_season = resolve_schedule_term(term_label)
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}
    generated_schedule = generate_schedule(
        completed_ids=completed_ids,
        concentration=concentration,
        target_term=eff_season,
        max_credits=15,
        degree_key=degree,
        term_label=eff_label,
    )
    cap = max(1, min(max_schedule_variants, 24))
    attach_schedule_variants(generated_schedule, eff_label, cap)

    return {
        "history": student_history,
        "upcoming": upcoming_schedules,
        "mock_generated_schedule": generated_schedule,
    }

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
    return load_json("fall_2026_offerings.json")


@app.get("/api/schedule/generate")
async def auto_generate_schedule(
    email: str,
    degree: str = "bs_computer_science",
    concentration: str = "systems_and_networks",
    max_credits: int = 15,
    term: Optional[str] = None,
    term_label: Optional[str] = None,
    max_schedule_variants: int = 12,
):
    if max_credits <= 0:
        raise HTTPException(status_code=400, detail="max_credits must be greater than 0.")

    history_data = load_json("student_history.json")
    student_history = history_data.get(email, {"completed_courses": []})
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}

    if degree not in DEGREE_PLANS:
        degree = "bs_computer_science"
    plan_meta = DEGREE_PLANS[degree]
    if concentration not in plan_meta["concentrations"]:
        concentration = plan_meta.get("default_concentration", "systems_and_networks")

    eff_label, eff_season = resolve_schedule_term(term_label or term)
    schedule = generate_schedule(
        completed_ids=completed_ids,
        concentration=concentration,
        target_term=eff_season,
        max_credits=max_credits,
        degree_key=degree,
        term_label=eff_label,
    )
    cap = max(1, min(max_schedule_variants, 24))
    attach_schedule_variants(schedule, eff_label, cap)

    return {
        "email": email,
        "completed_course_count": len(completed_ids),
        "inferred_term": eff_label,
        "schedule": schedule,
    }


# run with: uvicorn main:app --reload
