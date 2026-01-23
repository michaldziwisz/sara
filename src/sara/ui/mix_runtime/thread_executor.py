"""Thread-based executor for native mix triggers.

This module is intentionally wx-free so it can be imported in headless tests.
The executor is designed to remove `wx.CallAfter` latency from the critical
mix-trigger path by handling the native callback on a dedicated worker thread.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from sara.core.i18n import gettext as _
from sara.core.playlist import PlaylistItem, PlaylistItemStatus, PlaylistKind, PlaylistModel


logger = logging.getLogger(__name__)


def _call_after_if_app(func, *args) -> None:
    """Schedule via wx.CallAfter when wx.App exists, otherwise call directly.

    Implemented with a lazy import to keep this module wx-free for unit tests.
    """

    try:  # pragma: no cover - wx availability depends on runtime environment
        import wx

        app = wx.GetApp()
        if app:
            wx.CallAfter(func, *args)
            return
    except Exception:
        pass
    func(*args)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _compute_effective_override_from_player(ctx: Any, *, base_cue: float) -> float | None:
    if not ctx:
        return None
    getter = getattr(ctx.player, "get_length_seconds", None)
    if not callable(getter):
        return None
    try:
        total_len = float(getter())
    except Exception:
        return None
    if total_len <= 0.0:
        return None
    return max(0.0, total_len - float(base_cue))


def _build_on_progress(frame, playlist_id: str) -> Callable[[str, float], None]:
    def _on_progress(progress_item_id: str, seconds: float) -> None:
        _call_after_if_app(frame._handle_playback_progress, playlist_id, progress_item_id, seconds)

    return _on_progress


def _build_on_finished(frame, playlist_id: str) -> Callable[[str], None]:
    def _on_finished(finished_item_id: str) -> None:
        _call_after_if_app(frame._handle_playback_finished, playlist_id, finished_item_id)

    return _on_finished


def _schedule_selection_refresh(frame, playlist_id: str) -> None:
    refresher = getattr(frame, "_refresh_selection_display", None)
    if callable(refresher):
        _call_after_if_app(refresher, playlist_id)


def _schedule_announce(frame, category: str, message: str) -> None:
    announcer = getattr(frame, "_announce_event", None)
    if callable(announcer):
        _call_after_if_app(announcer, category, message)


def _resolve_next_item_for_automix(frame, playlist: PlaylistModel) -> tuple[int, PlaylistItem] | None:
    total = len(playlist.items)
    if total == 0:
        return None

    current_ctx = None
    getter = getattr(frame, "_get_playback_context", None)
    if callable(getter):
        try:
            current_ctx = getter(playlist.id)
        except Exception:
            current_ctx = None
    if current_ctx:
        current_id = current_ctx[0][1]
        current_idx = playlist.index_of(current_id)
        current_idx = current_idx if current_idx >= 0 else None
    else:
        current_idx = None

    if total == 1:
        if current_ctx:
            return None
        next_idx = 0
    elif current_idx is not None:
        next_idx = (current_idx + 1) % total
    else:
        tracker = getattr(frame, "_auto_mix_tracker", None)
        if tracker is None:
            next_idx = 0
        else:
            next_idx = int(tracker.next_index(playlist, break_resume_index=playlist.break_resume_index))

    playlist.break_resume_index = None

    try:
        tracker = getattr(frame, "_auto_mix_tracker", None)
        if tracker is not None:
            tracker.stage_next(playlist.id, playlist.items[next_idx].id)
    except Exception:
        pass

    # Avoid restarting the currently playing item when overlap is active and contexts overlap.
    if current_ctx and current_ctx[0][1] == playlist.items[next_idx].id and playlist.items[next_idx].status is PlaylistItemStatus.PLAYING:
        next_idx = (next_idx + 1) % total
        if playlist.items[next_idx].status is PlaylistItemStatus.PLAYING:
            return None

    return next_idx, playlist.items[next_idx]


def _resolve_next_item_for_queue(playlist: PlaylistModel) -> PlaylistItem | None:
    selected_id = playlist.next_selected_item_id()
    if not selected_id:
        return None
    return playlist.get_item(selected_id)


def _resolve_mix_schedule_for_item(frame, playlist: PlaylistModel, item: PlaylistItem) -> tuple[float | None, float, float, float]:
    base_cue: float = item.cue_in_seconds or 0.0
    effective_duration: float = item.effective_duration_seconds

    if playlist.kind is PlaylistKind.MUSIC and item.break_after:
        return None, 0.0, base_cue, effective_duration

    ctx = frame._playback.contexts.get((playlist.id, item.id))
    effective_override = _compute_effective_override_from_player(ctx, base_cue=base_cue)
    return frame._resolve_mix_timing(item, effective_duration_override=effective_override)


def _start_next_item_for_mix(
    frame,
    playlist: PlaylistModel,
    item: PlaylistItem,
    *,
    enqueue_mix_trigger: Callable[[str, str], None],
    restart_if_playing: bool,
) -> bool:
    if not item.path.exists():
        item.status = PlaylistItemStatus.PENDING
        _schedule_announce(frame, "playback_errors", _("File %s does not exist") % item.path)
        return False

    start_seconds = item.cue_in_seconds or 0.0
    mix_trigger_seconds, fade_seconds, base_cue, effective_duration = _resolve_mix_schedule_for_item(frame, playlist, item)
    on_mix_trigger: Callable[[], None] | None = None
    if mix_trigger_seconds is not None and not item.break_after:
        on_mix_trigger = lambda pl_id=playlist.id, it_id=item.id: enqueue_mix_trigger(pl_id, it_id)

    result = frame._playback.start_item(
        playlist,
        item,
        start_seconds=start_seconds,
        on_finished=_build_on_finished(frame, playlist.id),
        on_progress=_build_on_progress(frame, playlist.id),
        restart_if_playing=restart_if_playing,
        mix_trigger_seconds=mix_trigger_seconds,
        on_mix_trigger=on_mix_trigger,
    )
    if result is None:
        item.status = PlaylistItemStatus.PENDING
        return False

    played_tracks_logger = getattr(frame, "_played_tracks_logger", None)
    if played_tracks_logger:
        try:
            played_tracks_logger.on_started(playlist, item)
        except Exception:
            pass
    now_playing_writer = getattr(frame, "_now_playing_writer", None)
    if now_playing_writer:
        try:
            now_playing_writer.on_started(playlist, item)
        except Exception:
            pass

    native_trigger = False
    try:
        native_trigger = bool(getattr(frame, "_supports_mix_trigger", lambda _p: False)(result.player))
    except Exception:
        native_trigger = False

    frame._register_mix_plan(
        playlist.id,
        item.id,
        mix_at=mix_trigger_seconds,
        fade_seconds=fade_seconds,
        base_cue=base_cue,
        effective_duration=effective_duration,
        native_trigger=native_trigger,
    )

    item.status = PlaylistItemStatus.PLAYING

    if item.is_selected:
        playlist.clear_selection(item.id)
        _schedule_selection_refresh(frame, playlist.id)

    # Best-effort: if the backend reports a different length, re-apply mix trigger using the real duration.
    try:
        from sara.ui.mix_runtime.triggers import apply_mix_trigger_to_playback, sync_loop_mix_trigger

        def _enqueue_call_after(_func, *args):
            if len(args) >= 2:
                enqueue_mix_trigger(str(args[0]), str(args[1]))
                return None
            return _func(*args)

        getter = getattr(result.player, "get_length_seconds", None)
        if callable(getter):
            length_seconds = _safe_float(getter())
        else:
            length_seconds = None
        if length_seconds is not None and length_seconds > 0.0:
            cue = item.cue_in_seconds or 0.0
            effective_actual = max(0.0, float(length_seconds) - float(cue))
            effective_meta = float(item.effective_duration_seconds or 0.0)
            if abs(effective_actual - effective_meta) > 0.5:
                item.duration_seconds = cue + effective_actual
                item.current_position = min(float(item.current_position or 0.0), effective_actual)
                apply_mix_trigger_to_playback(
                    frame,
                    playlist_id=playlist.id,
                    item=item,
                    panel=None,
                    call_after=_enqueue_call_after,
                )
        sync_loop_mix_trigger(
            frame,
            panel=None,
            playlist=playlist,
            item=item,
            context=result,
            call_after=_enqueue_call_after,
        )
    except Exception:
        pass

    # Preload after starting; does not affect the critical path.
    if getattr(frame, "_auto_mix_enabled", False) and playlist.kind is PlaylistKind.MUSIC:
        try:
            frame._playback.schedule_next_preload(playlist, current_item_id=item.id)
        except Exception:
            pass

    return True


def handle_native_mix_trigger(
    frame,
    *,
    playlist_id: str,
    item_id: str,
    enqueue_mix_trigger: Callable[[str, str], None],
) -> None:
    """Execute a native mix trigger without calling wx/UI code on the worker thread."""

    playlist: PlaylistModel | None = None
    getter = getattr(frame, "_get_playlist_model", None)
    if callable(getter):
        playlist = getter(playlist_id)
    if not playlist:
        return
    item = playlist.get_item(item_id)
    if not item:
        return

    key = (playlist.id, item.id)
    plan = getattr(frame, "_mix_plans", {}).get(key)
    if plan and getattr(plan, "triggered", False):
        return

    queued_selection = False
    try:
        queued_selection = bool(getattr(frame, "_playlist_has_selection", lambda _pid: False)(playlist.id))
    except Exception:
        queued_selection = False

    if not getattr(frame, "_auto_mix_enabled", False) and not queued_selection:
        return
    if frame._playback.auto_mix_state.get(key):
        return

    if item.break_after or getattr(frame, "_active_break_item", {}).get(playlist.id) == item.id:
        frame._playback.auto_mix_state[key] = "break_halt"
        logger.debug("THREAD: auto_mix ignored due to break playlist=%s item=%s", playlist.id, item.id)
        return

    # Guard against early native triggers (fallback to progress-based trigger).
    base_cue = plan.base_cue if plan else (item.cue_in_seconds or 0.0)
    ctx = frame._playback.contexts.get(key)
    length_seconds = None
    if ctx:
        length_seconds = _safe_float(getattr(ctx.player, "get_length_seconds", lambda: None)())
    if length_seconds is None and plan:
        length_seconds = base_cue + plan.effective_duration
    max_mix_point = None
    if length_seconds and length_seconds > 0.0:
        max_mix_point = max(0.0, float(length_seconds) - 0.01)

    expected_mix = plan.mix_at if plan else getattr(frame, "_mix_trigger_points", {}).get(key)
    if expected_mix is None:
        mix_trigger, fade_seconds, base_cue, eff = frame._resolve_mix_timing(item)
        native_trigger = False
        try:
            native_trigger = bool(getattr(frame, "_supports_mix_trigger", lambda _p: False)(ctx.player if ctx else None))
        except Exception:
            native_trigger = False
        frame._register_mix_plan(
            playlist.id,
            item.id,
            mix_at=mix_trigger,
            fade_seconds=fade_seconds,
            base_cue=base_cue,
            effective_duration=eff,
            native_trigger=native_trigger,
        )
        expected_mix = mix_trigger
        plan = getattr(frame, "_mix_plans", {}).get(key)

    if expected_mix is not None and max_mix_point is not None:
        clamped_expected = min(float(expected_mix), float(max_mix_point))
        if clamped_expected != float(expected_mix):
            frame._register_mix_plan(
                playlist.id,
                item.id,
                mix_at=clamped_expected,
                fade_seconds=plan.fade_seconds if plan else float(getattr(frame, "_fade_duration", 0.0) or 0.0),
                base_cue=base_cue,
                effective_duration=plan.effective_duration if plan else float(item.effective_duration_seconds),
                native_trigger=False,
            )
            expected_mix = clamped_expected
            plan = getattr(frame, "_mix_plans", {}).get(key)

    if expected_mix is not None:
        current_abs = float(base_cue) + float(item.current_position or 0.0)
        tolerance = 0.75
        if current_abs < float(expected_mix) - tolerance:
            effective_override = max(0.0, float(length_seconds) - float(base_cue)) if length_seconds is not None else None
            rescheduled, _fade, _base_cue, _eff = frame._resolve_mix_timing(item, effective_duration_override=effective_override)
            if rescheduled is not None and max_mix_point is not None:
                rescheduled = min(float(rescheduled), float(max_mix_point))
            fallback_mix = rescheduled if rescheduled is not None else float(expected_mix)
            fallback_fade = _fade if rescheduled is not None else (plan.fade_seconds if plan else float(getattr(frame, "_fade_duration", 0.0) or 0.0))
            fallback_base = _base_cue if rescheduled is not None else float(base_cue)
            fallback_eff = _eff if rescheduled is not None else (plan.effective_duration if plan else float(item.effective_duration_seconds))
            if ctx and getattr(frame, "_supports_mix_trigger", lambda _p: False)(ctx.player):
                try:
                    frame._playback.update_mix_trigger(
                        playlist.id,
                        item.id,
                        mix_trigger_seconds=None,
                        on_mix_trigger=None,
                    )
                except Exception:
                    pass
            frame._register_mix_plan(
                playlist.id,
                item.id,
                mix_at=fallback_mix,
                fade_seconds=fallback_fade,
                base_cue=fallback_base,
                effective_duration=fallback_eff,
                native_trigger=False,
            )
            logger.debug(
                "THREAD: backend fired early -> fallback to progress trigger playlist=%s item=%s current=%.3f expected=%.3f",
                playlist.id,
                item.id,
                current_abs,
                float(fallback_mix) if fallback_mix is not None else -1.0,
            )
            return

    token = object()
    existing = frame._playback.auto_mix_state.setdefault(key, token)
    if existing is not token:
        return
    frame._playback.auto_mix_state[key] = True
    try:
        frame._mark_mix_triggered(playlist.id, item.id)
    except Exception:
        pass

    effective_total = (
        max(0.0, float(length_seconds) - float(base_cue))
        if length_seconds is not None
        else (plan.effective_duration if plan else float(item.effective_duration_seconds))
    )
    remaining = max(0.0, float(effective_total) - float(item.current_position or 0.0))

    started = False
    try:
        if getattr(frame, "_auto_mix_enabled", False) and playlist.kind is PlaylistKind.MUSIC:
            next_choice = _resolve_next_item_for_automix(frame, playlist)
            if next_choice:
                _idx, next_item = next_choice
                next_item.is_selected = False
                next_item.status = PlaylistItemStatus.PENDING
                next_item.current_position = 0.0
                started = _start_next_item_for_mix(
                    frame,
                    playlist,
                    next_item,
                    enqueue_mix_trigger=enqueue_mix_trigger,
                    restart_if_playing=True,
                )
                if started:
                    frame._last_started_item_id[playlist.id] = next_item.id
                    try:
                        frame._auto_mix_tracker.set_last_started(playlist.id, next_item.id)
                    except Exception:
                        pass
        elif queued_selection and playlist.kind is PlaylistKind.MUSIC:
            next_item = _resolve_next_item_for_queue(playlist)
            if next_item:
                # Use begin_next_item to mimic manual queue consumption semantics.
                picked = playlist.begin_next_item(next_item.id)
                if picked:
                    started = _start_next_item_for_mix(
                        frame,
                        playlist,
                        picked,
                        enqueue_mix_trigger=enqueue_mix_trigger,
                        restart_if_playing=False,
                    )
                    if started:
                        frame._last_started_item_id[playlist.id] = picked.id
    except Exception:
        logger.exception("THREAD: failed to start next item playlist=%s item=%s", playlist.id, item.id)
        started = False

    if started and float(getattr(frame, "_fade_duration", 0.0) or 0.0) > 0.0:
        fade_target = plan.fade_seconds if plan else float(getattr(frame, "_fade_duration", 0.0) or 0.0)
        fade_duration = min(float(fade_target), float(remaining))
        if fade_duration > 0.0 and ctx:
            try:
                ctx.player.fade_out(float(fade_duration))
            except Exception:
                pass
    else:
        # If start failed, clear state so progress fallback can attempt again.
        plan_obj = getattr(frame, "_mix_plans", {}).get(key)
        if plan_obj:
            try:
                plan_obj.triggered = False
            except Exception:
                pass
        frame._playback.auto_mix_state.pop(key, None)

    # Best-effort metric: callback -> executor delay.
    try:
        mix_event = getattr(ctx.player, "_last_mix_trigger_event", None) if ctx else None
        if isinstance(mix_event, dict) and not mix_event.get("reported"):
            fired_pos = mix_event.get("fired_pos")
            target = mix_event.get("target")
            requested = mix_event.get("requested")
            source = mix_event.get("source")
            trigger_ts = mix_event.get("perf_ts")
            now_ts = time.perf_counter()
            delay_ms = (now_ts - float(trigger_ts)) * 1000.0 if trigger_ts is not None else None
            logger.info(
                "MIX_METRIC native executor=thread playlist=%s item=%s started=%s delay_ms=%s fired_pos=%s target=%s requested=%s via=%s",
                playlist.id,
                item.id,
                started,
                f"{delay_ms:.2f}" if delay_ms is not None else "?",
                f"{float(fired_pos):.3f}" if fired_pos is not None else "?",
                f"{float(target):.3f}" if target is not None else "?",
                f"{float(requested):.3f}" if requested is not None else "?",
                source or "?",
            )
            mix_event["reported"] = True
    except Exception:  # pragma: no cover - metrics are best-effort
        pass


@dataclass(frozen=True)
class _MixWorkItem:
    playlist_id: str
    item_id: str


class ThreadMixExecutor:
    """Single-thread worker processing native mix triggers."""

    def __init__(self, frame) -> None:
        self._frame = frame
        self._queue: queue.Queue[_MixWorkItem | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="sara-mix-executor", daemon=True)
        self._thread.start()

    def enqueue(self, playlist_id: str, item_id: str) -> None:
        self._queue.put(_MixWorkItem(str(playlist_id), str(item_id)))

    def shutdown(self, *, timeout: float = 1.0) -> None:
        try:
            self._queue.put(None)
        except Exception:
            return
        try:
            self._thread.join(timeout=max(0.0, float(timeout)))
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                handle_native_mix_trigger(
                    self._frame,
                    playlist_id=item.playlist_id,
                    item_id=item.item_id,
                    enqueue_mix_trigger=self.enqueue,
                )
            except Exception:
                logger.exception(
                    "THREAD: unhandled error while processing mix trigger playlist=%s item=%s",
                    item.playlist_id,
                    item.item_id,
                )
