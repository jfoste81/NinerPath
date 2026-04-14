"""File-backed JSON reads/writes; student_history is cached in memory"""
from __future__ import annotations

import copy
import json
import os
import threading

_STUDENT_HISTORY_FILENAME = "student_history.json"
_student_history_lock = threading.Lock()
_student_history_cache: dict | None = None


def load_json(filename: str):
    with open(f"data/{filename}", "r", encoding="utf-8") as file:
        return json.load(file)


def _load_student_history_from_disk() -> dict:
    raw = load_json(_STUDENT_HISTORY_FILENAME)
    if not isinstance(raw, dict):
        return {}
    return raw


def ensure_student_history_loaded() -> None:
    """Populate the student_history cache from disk (call from app lifespan)."""
    global _student_history_cache
    with _student_history_lock:
        if _student_history_cache is None:
            _student_history_cache = _load_student_history_from_disk()


def get_student_history() -> dict:
    """
    Return a deep copy of the root student_history object (email -> record).

    Avoids disk I/O on every request; writers use write_student_history to persist and refresh cache.
    """
    global _student_history_cache
    with _student_history_lock:
        if _student_history_cache is None:
            _student_history_cache = _load_student_history_from_disk()
        return copy.deepcopy(_student_history_cache)


def write_student_history(data: dict) -> None:
    """Persist full student_history root to disk and refresh the in-memory cache."""
    global _student_history_cache
    path = os.path.join("data", _STUDENT_HISTORY_FILENAME)
    if not isinstance(data, dict):
        data = {}
    snapshot = copy.deepcopy(data)
    with _student_history_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        _student_history_cache = snapshot
