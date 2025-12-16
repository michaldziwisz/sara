"""Models and serialization helpers for SARA jingle sets (.sarajingles)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SARA_JINGLES_EXTENSION = ".sarajingles"


@dataclass
class JingleSlot:
    path: Path | None = None
    label: str | None = None


@dataclass
class JinglePage:
    name: str | None = None
    slots: list[JingleSlot] | None = None

    def normalized_slots(self) -> list[JingleSlot]:
        slots = list(self.slots or [])
        while len(slots) < 10:
            slots.append(JingleSlot())
        return slots[:10]


@dataclass
class JingleSet:
    name: str = "Jingles"
    pages: list[JinglePage] | None = None

    def normalized_pages(self) -> list[JinglePage]:
        pages = list(self.pages or [])
        if not pages:
            pages = [JinglePage()]
        return pages


def _coerce_path(value: Any, *, base_dir: Path) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


def load_jingle_set(path: Path) -> JingleSet:
    """Load a jingle set from JSON (creates an empty default if missing)."""

    if not path.exists():
        return JingleSet()

    text = path.read_text(encoding="utf-8")
    try:
        payload: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        # Not our format; fall back to an empty set.
        return JingleSet()

    name = str(payload.get("name") or "Jingles")
    pages_raw = payload.get("pages") or []
    pages: list[JinglePage] = []
    base_dir = path.parent

    if isinstance(pages_raw, list):
        for page_entry in pages_raw:
            if not isinstance(page_entry, dict):
                continue
            page_name = page_entry.get("name")
            page_name = str(page_name) if isinstance(page_name, (str, int)) else None
            slots_raw = page_entry.get("slots") or []
            slots: list[JingleSlot] = []
            if isinstance(slots_raw, list):
                for slot_entry in slots_raw:
                    if slot_entry is None:
                        slots.append(JingleSlot())
                        continue
                    if not isinstance(slot_entry, dict):
                        slots.append(JingleSlot())
                        continue
                    slot_path = _coerce_path(slot_entry.get("path"), base_dir=base_dir)
                    slot_label = slot_entry.get("label")
                    slot_label = str(slot_label) if isinstance(slot_label, (str, int)) else None
                    slots.append(JingleSlot(path=slot_path, label=slot_label))
            pages.append(JinglePage(name=page_name, slots=slots))

    return JingleSet(name=name, pages=pages)


def _path_for_save(slot_path: Path, *, base_dir: Path) -> str:
    try:
        rel = slot_path.relative_to(base_dir)
    except ValueError:
        return str(slot_path)
    return str(rel)


def save_jingle_set(path: Path, jingle_set: JingleSet) -> None:
    """Save a jingle set to JSON."""

    if path.suffix.lower() != SARA_JINGLES_EXTENSION:
        path = path.with_suffix(SARA_JINGLES_EXTENSION)

    base_dir = path.parent
    pages_payload: list[dict[str, Any]] = []
    for page in jingle_set.normalized_pages():
        slots_payload: list[dict[str, Any] | None] = []
        for slot in page.normalized_slots():
            if not slot.path:
                slots_payload.append(None)
                continue
            slots_payload.append(
                {
                    "path": _path_for_save(slot.path, base_dir=base_dir),
                    "label": slot.label,
                }
            )
        pages_payload.append({"name": page.name, "slots": slots_payload})

    payload = {
        "version": 1,
        "name": jingle_set.name,
        "pages": pages_payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_page_count(jingle_set: JingleSet, minimum_pages: int) -> None:
    """Ensure the set has at least N pages (mutates)."""

    if minimum_pages <= 0:
        return
    pages = jingle_set.normalized_pages()
    while len(pages) < minimum_pages:
        pages.append(JinglePage())
    jingle_set.pages = pages


def iter_page_labels(jingle_set: JingleSet) -> Iterable[str]:
    pages = jingle_set.normalized_pages()
    for idx, page in enumerate(pages, start=1):
        if page.name:
            yield str(page.name)
        else:
            yield f"Page {idx}"

