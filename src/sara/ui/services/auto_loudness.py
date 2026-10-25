"""Kolejka pomiarów EBU R128 i bezpieczne przekazanie wyników do playlist."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread

import wx

from sara.core import loudness
from sara.core.media_metadata import save_replay_gain_metadata
from sara.core.playlist import PlaylistKind

logger = logging.getLogger(__name__)


def path_key(path: Path) -> str:
    # Bez resolve/stat w GUI: plik może leżeć na wolnym udziale sieciowym.
    return os.path.normcase(os.path.abspath(path))


class _TrackedPreloadExecutor:
    """Przezroczysty adapter: obserwuje zadania, nie zmienia pracy preloadu."""

    def __init__(self, executor) -> None:
        self._executor = executor
        self._lock = Lock()
        self._pending = set()
        # Obejmuje także zadania wysłane przed podłączeniem obserwatora.
        self.submit(lambda: None)

    def submit(self, fn, *args, **kwargs):
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._pending.add(future)
        future.add_done_callback(self._finished)
        return future

    def _finished(self, future) -> None:
        with self._lock:
            self._pending.discard(future)

    def busy(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def __getattr__(self, name):
        return getattr(self._executor, name)


class AutoLoudnessService:
    """Model i kolejka należą do GUI; jedyny worker wykonuje pomiary."""

    def __init__(self, frame, *, call_after=None) -> None:
        self.frame = frame
        self._call_after = call_after or wx.CallAfter
        self._queue = Queue()
        self._stop = Event()
        self._enabled = Event()
        self._worker = None
        self._available = None
        self._seen: set[str] = set()
        self._observed: set[str] = set()
        self._write_failed: set[str] = set()
        self._results: dict[str, tuple[float, str]] = {}
        self._pending: dict[str, tuple[Path, float | None, str | None]] = {}
        self._track_preload()

    def _track_preload(self):
        playback = self.frame._playback
        executor = getattr(playback, "_preload_executor", None)
        if executor is not None and not isinstance(executor, _TrackedPreloadExecutor):
            executor = _TrackedPreloadExecutor(executor)
            playback._preload_executor = executor
        return executor

    def poll(self) -> None:
        if self._stop.is_set():
            return
        if self.frame._settings.get_auto_loudness():
            self._enabled.set()
            self._discover()
        else:
            self._enabled.clear()
        self._flush_pending()

    def _discover(self) -> None:
        for playlist in self.frame._state.playlists.values():
            if playlist.kind is not PlaylistKind.MUSIC:
                continue
            for item in playlist.items:
                key = path_key(item.path)
                if key in self._results:
                    gain, marker = self._results[key]
                    if item.id not in self._observed and not item.sara_loudness and key in self._write_failed:
                        self._pending[key] = (item.path, gain, marker)
                    item.replay_gain_db = gain
                    item.sara_loudness = marker
                self._observed.add(item.id)
                if item.sara_loudness:  # LOUDNESS_MARKER
                    continue
                if key in self._seen:
                    continue
                if self._available is None:
                    self._available = loudness.find_bs1770gain() is not None
                    if not self._available:
                        logger.warning("Automatyczne wyrównywanie głośności wyłączone: brak bs1770gain")
                if not self._available:
                    return
                self._seen.add(key)
                self._queue.put((key, item.path))
                if self._worker is None:
                    self._worker = Thread(target=self._run, name="sara-loudness", daemon=True)
                    self._worker.start()  # LOUDNESS_BACKGROUND

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._queue.get()
            if job is None:
                return
            key, path = job
            if not self._enabled.is_set():
                self._call_after(self._cancelled, key)
                continue
            try:
                result = loudness.measure_normalization(path, standard=loudness.LoudnessStandard.EBU)
            except Exception as exc:
                logger.warning("Nie udało się zmierzyć głośności %s: %s", path, exc)
                continue
            if not self._stop.is_set():
                self._call_after(self._finished, key, path, result)

    def _cancelled(self, key: str) -> None:
        self._seen.discard(key)

    def _finished(self, key: str, path: Path, result: loudness.NormalizationResult) -> None:
        if self._stop.is_set():
            return
        if not self.frame._settings.get_auto_loudness():
            self._seen.discard(key)
            return
        # Ręczny pomiar wykonany w międzyczasie ma pierwszeństwo.
        if key in self._results:
            return
        self.apply(path, result.gain_db, result.marker)

    def apply(self, path: Path, gain: float | None, marker: str | None) -> None:
        """Zmienia wyłącznie model, nigdy głośność już otwartego playera."""
        if self._stop.is_set():
            return
        key = path_key(path)
        self._seen.add(key)
        if gain is not None and marker:
            self._results[key] = (gain, marker)
        else:
            self._results.pop(key, None)
        for playlist in self.frame._state.playlists.values():
            for item in playlist.items:
                if path_key(item.path) == key:
                    item.replay_gain_db = gain  # LOUDNESS_MODEL_ONLY
                    item.sara_loudness = marker
        self._pending[key] = (path, gain, marker)
        self._flush_pending()

    def _flush_pending(self) -> None:
        if not self._pending or self._stop.is_set():
            return
        # Sprawdź także trwające i oczekujące zadania, których ścieżka nie
        # pojawiła się jeszcze w player._preloaded_path. Sam koniec wcześniejszej
        # bariery nie wystarcza: za nią mógł zostać wysłany następny preload.
        executor = self._track_preload()
        if executor is not None and executor.busy():
            return
        for key, (path, gain, marker) in list(self._pending.items()):
            if self._path_in_use(key):
                continue
            # Sprawdzenie i zapis w tej samej turze GUI: start/stop utworu nie
            # może wcisnąć się pomiędzy sprawdzenie kontekstu i zmianę tagów.
            del self._pending[key]
            try:
                saved = save_replay_gain_metadata(path, gain, sara_loudness=marker)
            except Exception as exc:
                self._write_failed.add(key)
                logger.warning("Nie udało się zapisać ReplayGain dla %s: %s", path, exc)
            else:
                if not saved:
                    self._write_failed.add(key)
                    logger.warning("Nie udało się zapisać ReplayGain dla %s; wynik pozostaje w pamięci", path)
                else:
                    self._write_failed.discard(key)
            # Nie opróżniaj całej odroczonej kolejki w jednej turze GUI.
            break

    def _path_in_use(self, key: str) -> bool:
        playback = self.frame._playback
        contexts = list(playback.contexts.values())
        if any(path_key(context.path) == key for context in contexts):
            return True
        # Odsłuch miksu może mieć dwa pliki, w tym czekający na start B.
        if playback.preview_context is not None:
            return True
        preloaded_paths = getattr(playback, "preloaded_paths", lambda: [])
        if any(path_key(path) == key for path in preloaded_paths()):
            return True
        known_players = {id(context.player) for context in contexts}
        players = getattr(self.frame._audio_engine, "_players", {}).values()
        for player in players:
            preloaded = getattr(player, "_preloaded_path", None)
            if preloaded is not None and path_key(preloaded) == key:
                return True
            # Kontekst bywa usunięty przed końcem fade. Brak jawnej ścieżki
            # otwartego strumienia BASS wymaga wtedy odłożenia wszystkich zapisów.
            if id(player) not in known_players and getattr(player, "_stream", 0):
                return True
        return False

    def close(self) -> None:
        self._stop.set()
        self._enabled.clear()
        self._pending.clear()
        self._queue.put(None)
        # Bez join: nawet niedostępny dysk lub CLI nie opóźni zamknięcia okna.


def start_auto_loudness(frame) -> None:
    service = AutoLoudnessService(frame)
    frame._auto_loudness = service
    timer = wx.Timer(frame)
    frame._auto_loudness_timer = timer
    frame.Bind(wx.EVT_TIMER, lambda _event: service.poll(), timer)
    frame.Bind(wx.EVT_WINDOW_DESTROY, lambda event: _on_destroy(frame, event))
    timer.Start(500)
    service.poll()


def _on_destroy(frame, event) -> None:
    if event.GetEventObject() is frame:
        stop_auto_loudness(frame)
    event.Skip()


def stop_auto_loudness(frame) -> None:
    timer = getattr(frame, "_auto_loudness_timer", None)
    if timer is not None:
        timer.Stop()
    service = getattr(frame, "_auto_loudness", None)
    if service is not None:
        service.close()
