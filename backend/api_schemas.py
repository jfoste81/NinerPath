"""
Pydantic request/response models for HTTP boundaries (Phase 3).

Shapes match existing API contracts; extra keys are allowed on responses where noted.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# --- Query / shared ---


class DashboardQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=1)
    degree: str = Field(default="bs_computer_science", min_length=1)
    concentration: str = Field(default="systems_and_networks", min_length=1)
    max_schedule_variants: int = Field(default=12, ge=1, le=100)


class DegreeAuditQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=1)
    degree: str = Field(default="bs_computer_science", min_length=1)
    concentration: str = Field(default="systems_and_networks", min_length=1)
    user_id: Optional[str] = None

    @field_validator("user_id", mode="before")
    @classmethod
    def _blank_user_id_to_none(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class ScheduleGenerateQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=1)
    degree: str = Field(default="bs_computer_science", min_length=1)
    concentration: str = Field(default="systems_and_networks", min_length=1)
    max_credits: int = Field(default=15, ge=1, le=40)
    max_schedule_variants: int = Field(default=12, ge=1, le=100)


class SchedulePreferencesEmailQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(..., min_length=1)


class ExportIcsQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: str = Field(..., min_length=1)
    email: Optional[str] = None


# --- Request bodies ---


class SchedulePreferencesBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    email: str = Field(..., min_length=1)
    blocked_time_windows: Optional[list[Any]] = None

    @field_validator("email", mode="before")
    @classmethod
    def _email_str(cls, v: Any) -> str:
        return str(v or "").strip()

    @model_validator(mode="after")
    def _validate_windows(self) -> SchedulePreferencesBody:
        if self.blocked_time_windows is not None and not isinstance(self.blocked_time_windows, list):
            raise ValueError("blocked_time_windows must be a list or omitted.")
        return self


class ScheduleSaveBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str = Field(..., min_length=1)
    course_ids: list[str]
    term_label: Optional[str] = None
    variant_index: int = 0
    combination_index: int = 0

    @field_validator("user_id", mode="before")
    @classmethod
    def _strip_uid(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("course_ids", mode="before")
    @classmethod
    def _normalize_course_ids(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("course_ids must be a non-empty list.")
        out: list[str] = []
        for x in v:
            s = str(x).strip() if x is not None else ""
            if s:
                out.append(s)
        if not out:
            raise ValueError("course_ids must contain at least one course id.")
        return out

    @field_validator("term_label", mode="before")
    @classmethod
    def _strip_term(cls, v: Any) -> Optional[str]:
        if v is None or v == "":
            return None
        return str(v).strip()

    @field_validator("variant_index", "combination_index", mode="before")
    @classmethod
    def _int_fields(cls, v: Any) -> int:
        try:
            return int(v if v is not None else 0)
        except (TypeError, ValueError):
            return 0


# --- Response bodies (serialization pass-through; nested dicts preserved) ---


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    history: dict[str, Any]
    upcoming: list[Any]
    mock_generated_schedule: dict[str, Any]


class DegreeAuditResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    email: str
    degree: str
    concentration: str
    audit: dict[str, Any]


class SchedulePreferencesGetResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    email: str
    schedule_preferences: dict[str, Any]


class SchedulePreferencesSaveResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    email: str
    schedule_preferences: dict[str, Any]


class ScheduleSaveResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    source: str
    saved: dict[str, Any]


class GenEdStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    email: str
    gen_ed_progress: list[Any]


class AutoGenerateScheduleResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    email: str
    completed_course_count: int
    inferred_term: str
    schedule: dict[str, Any]
