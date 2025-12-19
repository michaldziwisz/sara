"""Logic for enumerating files/directories used by FileSelectionDialog."""

from __future__ import annotations

import ctypes
import fnmatch
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal


FileEntryKind = Literal["file", "dir", "drive", "parent"]


@dataclass(frozen=True, slots=True)
class FileEntry:
    """Represents a single row displayed in the file selection dialog."""

    name: str
    path: Path
    kind: FileEntryKind
    size_label: str = ""


def _default_drive_paths() -> list[Path]:
    entries: list[Path] = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        mask = 0
    if mask:
        for offset, letter in enumerate(string.ascii_uppercase):
            if mask & (1 << offset):
                entries.append(Path(f"{letter}:\\"))
    if not entries:
        for letter in string.ascii_uppercase:
            candidate = Path(f"{letter}:\\")
            if candidate.exists():
                entries.append(candidate)
    return entries


class FileBrowser:
    """Stateful helper tracking current path and available entries."""

    def __init__(
        self,
        start_path: Path | None = None,
        *,
        drive_provider: Callable[[], list[Path]] | None = None,
    ) -> None:
        self._drive_provider = drive_provider or _default_drive_paths
        self._current_path = self._initial_path(start_path)

    def _initial_path(self, candidate: Path | None) -> Path | None:
        if candidate and candidate.exists():
            return candidate
        try:
            cwd = Path.cwd()
            if cwd.exists():
                return cwd
        except Exception:
            pass
        home = Path.home()
        return home if home.exists() else None

    def current_path(self) -> Path | None:
        return self._current_path

    def set_current_path(self, path: Path | None) -> None:
        self._current_path = path

    def go_up(self) -> None:
        if self._current_path is None:
            return
        parent = self._current_path.parent
        if parent == self._current_path:
            self._current_path = None
        else:
            self._current_path = parent

    def list_entries(self, patterns: Iterable[str]) -> list[FileEntry]:
        entries: list[FileEntry] = []
        if self._current_path is None:
            drives = self._drive_provider()
            for drive in drives:
                label = drive.drive if hasattr(drive, "drive") else str(drive)
                entries.append(FileEntry(name=label, path=drive, kind="drive"))
            return entries

        current = self._current_path
        parent = current.parent
        if parent != current:
            entries.append(FileEntry(name="..", path=parent, kind="parent"))
        try:
            children = sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except (OSError, PermissionError):
            children = []
        for child in children:
            if child.is_dir():
                entries.append(FileEntry(name=child.name, path=child, kind="dir"))
        for child in children:
            if child.is_file() and self._matches_filter(child.name, patterns):
                try:
                    size = child.stat().st_size if child.exists() else 0
                except OSError:
                    size = 0
                entries.append(
                    FileEntry(
                        name=child.name,
                        path=child,
                        kind="file",
                        size_label=self._format_size(size),
                    )
                )
        return entries

    @staticmethod
    def _matches_filter(filename: str, patterns: Iterable[str]) -> bool:
        lowered = filename.lower()
        for pattern in patterns:
            if fnmatch.fnmatch(lowered, pattern.lower()):
                return True
        return False

    @staticmethod
    def _format_size(size: int) -> str:
        if size <= 0:
            return ""
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.0f} {unit}"
            value /= 1024
        return f"{size} B"


__all__ = [
    "FileBrowser",
    "FileEntry",
    "FileEntryKind",
]

