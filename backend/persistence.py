"""Saved schedules: local JSON + optional Supabase (Phase 1)."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Optional

import config


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
    return [
        _normalize_saved_schedule_row(r)
        for r in _read_all_local_saved_schedules()
        if str(r.get("user_id", "")).strip() == uid
    ]


async def _list_saved_schedules_async(user_id: str) -> list:
    merged: list = []
    seen_ids: set = set()
    if config.supabase:
        try:

            def _fetch():
                return config.supabase.table("saved_schedules").select("*").eq("user_id", user_id).execute()

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
        et = str(existing.get("term") or existing.get("term_label") or "").strip()
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


async def find_saved_schedule_row(user_id: str, schedule_id: str) -> Optional[dict]:
    uid = (user_id or "").strip()
    sid = str(schedule_id or "").strip()
    if not uid or not sid:
        return None
    rows = await _list_saved_schedules_async(uid)
    for r in rows:
        if str(r.get("id") or "") == sid:
            return r
    return None
