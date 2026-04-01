from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import json
import os
from typing import Optional

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

def get_current_term_label():
    now = datetime.now()
    term = "Spring" if now.month <= 5 else "Fall"
    return f"{term} {now.year}", term


def compute_dependent_counts(course_list):
    dependent_counts = {course["id"]: 0 for course in course_list}
    for course in course_list:
        for prereq in course.get("prereqs", []):
            if prereq in dependent_counts:
                dependent_counts[prereq] += 1
    return dependent_counts


DEPENDENT_COUNTS = compute_dependent_counts(COURSES)


def parse_course_number(course_id):
    try:
        return int(course_id.split(" ")[1])
    except (IndexError, ValueError):
        return 9999


def generate_schedule(completed_ids, concentration, target_term, max_credits):
    plan_root = DEGREE_PLANS["computer_science"]
    concentrations = plan_root["concentrations"]
    if concentration not in concentrations:
        raise HTTPException(status_code=400, detail=f"Unknown concentration '{concentration}'.")

    plan = concentrations[concentration]
    required_courses = [course_id for course_id in plan["required_courses"] if course_id not in completed_ids]
    elective_pool = [course_id for course_id in plan["elective_pool"] if course_id not in completed_ids]

    remaining_elective_slots = max(0, plan.get("elective_count", 0))
    in_progress = set(completed_ids)
    selected = []
    total_credits = 0

    # Required courses are prioritized; electives fill remaining room.
    candidate_ids = required_courses + elective_pool

    def is_eligible(course):
        offered = course.get("offered_in", ["Fall", "Spring"])
        prereqs = set(course.get("prereqs", []))
        return (
            course["id"] not in in_progress
            and (target_term in offered or "Both" in offered)
            and prereqs.issubset(in_progress)
        )

    def is_elective(course_id):
        return course_id in plan["elective_pool"] and course_id not in plan["required_courses"]

    sortable = []
    for course_id in candidate_ids:
        course = COURSE_BY_ID.get(course_id)
        if not course or not is_eligible(course):
            continue
        sortable.append(
            (
                0 if course_id in plan["required_courses"] else 1,
                -DEPENDENT_COUNTS.get(course_id, 0),
                parse_course_number(course_id),
                course,
            )
        )

    for _, _, _, course in sorted(sortable):
        if course["id"] in in_progress:
            continue
        if is_elective(course["id"]) and remaining_elective_slots <= 0:
            continue

        next_total = total_credits + course["credits"]
        if next_total > max_credits:
            continue

        total_credits = next_total
        in_progress.add(course["id"])
        selected.append(course)

        if is_elective(course["id"]):
            remaining_elective_slots -= 1

    remaining_required = [cid for cid in required_courses if cid not in {c["id"] for c in selected}]
    remaining_electives = [cid for cid in elective_pool if cid not in {c["id"] for c in selected}]

    return {
        "degree": plan_root["name"],
        "catalog_year": plan_root["catalog_year"],
        "concentration": concentration,
        "concentration_label": plan["label"],
        "target_term": target_term,
        "max_credits": max_credits,
        "generated_credits": total_credits,
        "recommended_courses": selected,
        "remaining_required_count": len(remaining_required),
        "remaining_elective_count": min(len(remaining_electives), remaining_elective_slots),
    }

@app.get("/api/dashboard/{user_id}")
async def get_dashboard_data(user_id: str, email: str):
    """Fetches history dynamically based on email, and saved schedules based on user_id."""
    
    # Get dynamic mock history from JSON using the email
    history_data = load_json("student_history.json")
    
    # If the email isn't in our JSON, give them a blank slate instead of crashing
    default_history = {"completed_courses": [], "gpa": 0.0}
    student_history = history_data.get(email, default_history)
    
    # Get saved upcoming schedule from Supabase (this uses the real user_id)
    try:
        if supabase:
            response = supabase.table("saved_schedules").select("*").eq("user_id", user_id).execute()
            upcoming_schedules = response.data
        else:
            upcoming_schedules = []
    except Exception as e:
        upcoming_schedules = []

    _, inferred_term = get_current_term_label()
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}
    generated_schedule = generate_schedule(
        completed_ids=completed_ids,
        concentration="general",
        target_term=inferred_term,
        max_credits=15,
    )

    return {
        "history": student_history,
        "upcoming": upcoming_schedules,
        "mock_generated_schedule": generated_schedule,
    }

@app.get("/api/degree-plans")
async def get_degree_plans():
    return DEGREE_PLANS


@app.get("/api/schedule/generate")
async def auto_generate_schedule(
    email: str,
    concentration: str = "general",
    max_credits: int = 15,
    term: Optional[str] = None,
):
    if max_credits <= 0:
        raise HTTPException(status_code=400, detail="max_credits must be greater than 0.")

    history_data = load_json("student_history.json")
    student_history = history_data.get(email, {"completed_courses": []})
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}

    term_label, inferred_term = get_current_term_label()
    target_term = term if term else inferred_term
    schedule = generate_schedule(
        completed_ids=completed_ids,
        concentration=concentration,
        target_term=target_term,
        max_credits=max_credits,
    )

    return {
        "email": email,
        "completed_course_count": len(completed_ids),
        "inferred_term": term_label,
        "schedule": schedule,
    }


# run with: uvicorn main:app --reload
