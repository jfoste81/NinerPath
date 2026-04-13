"""
NinerPath FastAPI application (Phase 1): routes, CORS, and wiring only.
Core logic lives in catalog, degree_plan, degree_audit, scheduler_service, persistence, data_access.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import api_schemas
import config  # noqa: F401 — loads dotenv and Supabase client
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

import catalog
import data_access
import degree_audit
import persistence
import route_context
import scheduler_service as scheduling


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    data_access.ensure_student_history_loaded()
    yield


app = FastAPI(lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://ninerpath.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validate_query_model(model_cls: type, request: Request):
    try:
        return model_cls.model_validate(dict(request.query_params))
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from e


async def _dashboard_query(request: Request) -> api_schemas.DashboardQuery:
    return _validate_query_model(api_schemas.DashboardQuery, request)


async def _degree_audit_query(request: Request) -> api_schemas.DegreeAuditQuery:
    return _validate_query_model(api_schemas.DegreeAuditQuery, request)


async def _schedule_generate_query(request: Request) -> api_schemas.ScheduleGenerateQuery:
    return _validate_query_model(api_schemas.ScheduleGenerateQuery, request)


async def _schedule_preferences_email_query(request: Request) -> api_schemas.SchedulePreferencesEmailQuery:
    return _validate_query_model(api_schemas.SchedulePreferencesEmailQuery, request)


async def _export_ics_query(request: Request) -> api_schemas.ExportIcsQuery:
    return _validate_query_model(api_schemas.ExportIcsQuery, request)


@app.get("/api/dashboard/{user_id}", response_model=api_schemas.DashboardResponse)
async def get_dashboard_data(
    user_id: str,
    q: api_schemas.DashboardQuery = Depends(_dashboard_query),
):
    """Fetches history dynamically based on email, and saved schedules based on user_id."""
    email = q.email
    max_schedule_variants = q.max_schedule_variants
    history_data = data_access.get_student_history()
    ctx = route_context.load_student_degree_context(history_data, email, q.degree, q.concentration)
    degree, concentration, student_history = ctx.degree, ctx.concentration, ctx.student_history

    upcoming_schedules = await persistence._list_saved_schedules_async(user_id)

    eff_label, eff_season = catalog.registration_schedule_term()
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}
    sp = route_context.schedule_preferences_subset(student_history)
    generated_schedule = scheduling.generate_schedule(
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
    scheduling.attach_variants_to_combination_options(generated_schedule, eff_label, cap)

    return {
        "history": student_history,
        "upcoming": upcoming_schedules,
        "mock_generated_schedule": generated_schedule,
    }


@app.get("/api/degree-audit", response_model=api_schemas.DegreeAuditResponse)
async def get_degree_audit(
    q: api_schemas.DegreeAuditQuery = Depends(_degree_audit_query),
):
    """Degree progress table data (completed vs remaining) for the landing audit view."""
    email = q.email
    user_id = q.user_id
    history_data = data_access.get_student_history()
    ctx = route_context.load_student_degree_context(history_data, email, q.degree, q.concentration)
    degree, concentration, student_history = ctx.degree, ctx.concentration, ctx.student_history
    planned: set = set()
    uid = (user_id or "").strip()
    if uid:
        rows = await persistence._list_saved_schedules_async(uid)
        planned = persistence._latest_saved_course_ids_for_term(rows, catalog.REGISTRATION_TERM_LABEL)
    audit = degree_audit.build_degree_audit(degree, concentration, student_history, planned_ids=planned)
    return {"email": email, "degree": degree, "concentration": concentration, "audit": audit}


@app.get("/api/student/schedule-preferences", response_model=api_schemas.SchedulePreferencesGetResponse)
async def get_schedule_preferences(
    q: api_schemas.SchedulePreferencesEmailQuery = Depends(_schedule_preferences_email_query),
):
    """Load saved schedule preferences (e.g. blocked meeting times) for a student email."""
    em = q.email
    history_data = data_access.get_student_history()
    row = route_context.student_history_row(history_data, em)
    sp = route_context.schedule_preferences_subset(row)
    return {"email": em, "schedule_preferences": sp}


@app.post("/api/student/schedule-preferences", response_model=api_schemas.SchedulePreferencesSaveResponse)
async def save_schedule_preferences(payload: api_schemas.SchedulePreferencesBody = Body(...)):
    """Persist schedule preferences into student_history.json (mock/local store)."""
    email = payload.email
    windows = payload.blocked_time_windows
    history_data = data_access.get_student_history()
    if not isinstance(history_data, dict):
        history_data = {}
    row = route_context.student_history_row(
        history_data, email, missing_placeholder=route_context.MINIMAL_NEW_STUDENT_ROW
    )
    sp = route_context.schedule_preferences_subset(row)
    if windows is not None:
        if windows:
            sp = {**sp, "blocked_time_windows": windows}
        else:
            sp = {k: v for k, v in sp.items() if k != "blocked_time_windows"}
    row["schedule_preferences"] = sp
    history_data[email] = row
    data_access.write_student_history(history_data)
    return {"ok": True, "email": email, "schedule_preferences": sp}


@app.post("/api/schedules/save", response_model=api_schemas.ScheduleSaveResponse)
async def save_schedule(payload: api_schemas.ScheduleSaveBody = Body(...)):
    """Persist a Fall plan for the degree audit (Supabase when configured, else local JSON)."""
    user_id = payload.user_id
    course_ids = payload.course_ids
    term_label = (payload.term_label or catalog.REGISTRATION_TERM_LABEL).strip() or catalog.REGISTRATION_TERM_LABEL
    variant_index = payload.variant_index
    combination_index = payload.combination_index
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
    if config.supabase:
        try:
            insert_payload = {
                "user_id": user_id,
                "term": term_label,
                "courses": course_ids,
            }

            def _replace_and_insert():
                config.supabase.table("saved_schedules").delete().eq("user_id", user_id).eq("term", term_label).execute()
                return config.supabase.table("saved_schedules").insert(insert_payload).execute()

            await asyncio.wait_for(asyncio.to_thread(_replace_and_insert), timeout=8.0)
            return {"ok": True, "source": "supabase", "saved": saved_row}
        except (asyncio.TimeoutError, Exception):
            pass
    persistence._replace_local_saved_schedule_for_term(user_id, term_label, saved_row)
    return {"ok": True, "source": "local", "saved": saved_row}


@app.get("/api/schedules/{schedule_id}/export.ics")
async def export_saved_schedule_ics(
    schedule_id: str,
    q: api_schemas.ExportIcsQuery = Depends(_export_ics_query),
):
    """
    Download an iCalendar (.ics) file for a saved schedule. Import into Google Calendar via
    File → Import (web) or calendar Settings → Import & export.

    Section times come from mock offerings; recurrence uses illustrative Fall 2026 dates.
    Pass the same email used in NinerPath so blocked-time preferences can match the saved variant when possible.
    """
    uid = q.user_id
    email = q.email
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required.")
    row = await persistence.find_saved_schedule_row(uid, schedule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Saved schedule not found.")
    course_ids = list(row.get("course_ids") or [])
    if not course_ids:
        raise HTTPException(status_code=400, detail="No courses in this saved schedule.")
    term_label = (row.get("term") or row.get("term_label") or catalog.REGISTRATION_TERM_LABEL).strip() or catalog.REGISTRATION_TERM_LABEL
    try:
        variant_index = int(row.get("variant_index") or 0)
    except (TypeError, ValueError):
        variant_index = 0
    variant_index = max(0, variant_index)

    blocked: list = []
    em = str(email or "").strip()
    if em:
        hist = route_context.student_history_row(data_access.get_student_history(), em)
        sp = route_context.schedule_preferences_subset(hist)
        blocked = scheduling.normalize_blocked_time_windows(sp.get("blocked_time_windows"))

    max_v = max(32, variant_index + 12)
    built = scheduling.build_schedule_variants(course_ids, term_label, max_variants=max_v, blocked_windows=blocked or None)
    variants = built.get("variants") or []
    if not variants and blocked:
        built = scheduling.build_schedule_variants(course_ids, term_label, max_variants=max_v, blocked_windows=None)
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
    ics_body = scheduling.build_schedule_ics_document(sections, term_label, calendar_title=f"NinerPath — {term_label}")
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
    return catalog.DEGREE_PLANS


@app.get("/api/geneds/{email}", response_model=api_schemas.GenEdStatusResponse)
async def get_gen_ed_status(email: str):
    history_data = data_access.get_student_history()
    student_history = history_data.get(email)
    if not student_history:
        raise HTTPException(status_code=404, detail="Student not found")
    return {
        "email": email,
        "gen_ed_progress": degree_audit.get_gen_ed_progress(student_history, catalog.GEN_EDS),
    }


@app.get("/api/offerings/fall-2026")
async def get_fall_2026_offerings():
    return catalog._fall_26_offerings


@app.get("/api/schedule/generate", response_model=api_schemas.AutoGenerateScheduleResponse)
async def auto_generate_schedule(
    q: api_schemas.ScheduleGenerateQuery = Depends(_schedule_generate_query),
):
    email = q.email
    max_credits = q.max_credits
    max_schedule_variants = q.max_schedule_variants

    history_data = data_access.get_student_history()
    ctx = route_context.load_student_degree_context(history_data, email, q.degree, q.concentration)
    degree, concentration, student_history = ctx.degree, ctx.concentration, ctx.student_history
    completed_ids = {course["id"] for course in student_history.get("completed_courses", [])}
    sp = route_context.schedule_preferences_subset(student_history)

    eff_label, eff_season = catalog.registration_schedule_term()
    schedule = scheduling.generate_schedule(
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
    scheduling.attach_variants_to_combination_options(schedule, eff_label, cap)

    return {
        "email": email,
        "completed_course_count": len(completed_ids),
        "inferred_term": eff_label,
        "schedule": schedule,
    }


# run with: uvicorn main:app --reload
