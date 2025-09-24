
"""Shortcut registry for SARA commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

def _key(scope: str, action: str) -> str:
    return f"{scope}:{action}"

@dataclass
class ShortcutDescriptor:
    scope: str
    action: str
    label: str
    default: str

    @property
    def registry_key(self) -> str:
        return _key(self.scope, self.action)

_SHORTCUTS: Dict[str, ShortcutDescriptor] = {}


def register_shortcut(scope: str, action: str, *, label: str, default: str) -> None:
    descriptor = ShortcutDescriptor(scope=scope, action=action, label=label, default=default)
    _SHORTCUTS[descriptor.registry_key] = descriptor


def get_shortcut(scope: str, action: str) -> ShortcutDescriptor | None:
    return _SHORTCUTS.get(_key(scope, action))


def iter_shortcuts() -> List[ShortcutDescriptor]:
    return list(_SHORTCUTS.values())


def ensure_defaults(default_registry: Dict[str, Dict[str, str]]) -> None:
    for descriptor in _SHORTCUTS.values():
        default_registry.setdefault(descriptor.scope, {})[descriptor.action] = descriptor.default


def _register_defaults() -> None:
    register_shortcut(
        "global",
        "play_next",
        label="Play next track",
        default="SPACE",
    )
    register_shortcut(
        "global",
        "auto_mix_toggle",
        label="Toggle auto mix",
        default="CTRL+SHIFT+M",
    )
    register_shortcut(
        "global",
        "marker_mode_toggle",
        label="Toggle marker mode",
        default="CTRL+SHIFT+ENTER",
    )
    register_shortcut(
        "global",
        "loop_playback_toggle",
        label="Toggle track looping",
        default="CTRL+SHIFT+L",
    )
    register_shortcut(
        "global",
        "loop_info",
        label="Track loop information",
        default="CTRL+ALT+SHIFT+L",
    )

    register_shortcut("playlist", "play", label="Playlist: play", default="F1")
    register_shortcut("playlist", "pause", label="Playlist: pause", default="F2")
    register_shortcut("playlist", "stop", label="Playlist: stop", default="F3")
    register_shortcut("playlist", "fade", label="Playlist: fade out", default="F4")
    register_shortcut("playlist_menu", "new", label="Playlist menu: new playlist", default="CTRL+N")
    register_shortcut(
        "playlist_menu",
        "add_tracks",
        label="Playlist menu: add tracks",
        default="CTRL+D",
    )
    register_shortcut(
        "playlist_menu",
        "assign_device",
        label="Playlist menu: assign device",
        default="CTRL+SHIFT+D",
    )
    register_shortcut(
        "playlist_menu",
        "import",
        label="Playlist menu: import playlist",
        default="CTRL+O",
    )
    register_shortcut(
        "playlist_menu",
        "export",
        label="Playlist menu: export playlist",
        default="CTRL+S",
    )
    register_shortcut(
        "playlist_menu",
        "exit",
        label="Playlist menu: exit",
        default="ALT+F4",
    )

    register_shortcut("edit", "undo", label="Undo", default="CTRL+Z")
    register_shortcut("edit", "redo", label="Redo", default="CTRL+SHIFT+Z")
    register_shortcut("edit", "cut", label="Cut", default="CTRL+X")
    register_shortcut("edit", "copy", label="Copy", default="CTRL+C")
    register_shortcut("edit", "paste", label="Paste", default="CTRL+V")
    register_shortcut("edit", "delete", label="Delete", default="DELETE")
    register_shortcut("edit", "move_up", label="Move up", default="ALT+UP")
    register_shortcut("edit", "move_down", label="Move down", default="ALT+DOWN")


_register_defaults()
