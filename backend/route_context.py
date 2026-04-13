"""Shared student-history and degree/concentration resolution for API routes (Phase 5)."""
from __future__ import annotations

import copy
from typing import Any, NamedTuple

import catalog

# Used when email is missing from student_history; copy on return so callers cannot mutate a shared default.
DEFAULT_STUDENT_HISTORY: dict[str, Any] = {"completed_courses": [], "gpa": 0.0}
# Minimal row for endpoints that create a new student record (e.g. first-time prefs save).
MINIMAL_NEW_STUDENT_ROW: dict[str, Any] = {"completed_courses": []}


def normalize_degree_concentration(degree: str, concentration: str) -> tuple[str, str]:
    """Ensure degree and concentration exist in catalog data; fall back to BS CS defaults."""
    if degree not in catalog.DEGREE_PLANS:
        degree = "bs_computer_science"
    plan_meta = catalog.DEGREE_PLANS[degree]
    if concentration not in plan_meta["concentrations"]:
        concentration = plan_meta.get("default_concentration", "systems_and_networks")
    return degree, concentration


def student_history_row(
    history_data: Any,
    email: str,
    *,
    missing_placeholder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return the student row for ``email``, or a deep copy of ``missing_placeholder`` (default:
    ``DEFAULT_STUDENT_HISTORY``) if absent or invalid. When the row exists in ``history_data``,
    the stored dict is returned (same reference as the cache).
    """
    ph = missing_placeholder if missing_placeholder is not None else DEFAULT_STUDENT_HISTORY
    if not isinstance(history_data, dict):
        return copy.deepcopy(ph)
    raw = history_data.get(email)
    if not isinstance(raw, dict):
        return copy.deepcopy(ph)
    return raw


def schedule_preferences_subset(student_history: dict[str, Any]) -> dict[str, Any]:
    """Normalized ``schedule_preferences`` dict for scheduler inputs (empty dict if missing or wrong type)."""
    sp = student_history.get("schedule_preferences")
    return sp if isinstance(sp, dict) else {}


class StudentDegreeContext(NamedTuple):
    """Resolved degree, concentration, and student history row for scheduling/audit endpoints."""

    degree: str
    concentration: str
    student_history: dict[str, Any]


def load_student_degree_context(
    history_data: Any,
    email: str,
    degree: str,
    concentration: str,
) -> StudentDegreeContext:
    """Fetch student row, normalize degree/concentration keys against ``catalog.DEGREE_PLANS``."""
    d, c = normalize_degree_concentration(degree, concentration)
    row = student_history_row(history_data, email)
    return StudentDegreeContext(degree=d, concentration=c, student_history=row)
