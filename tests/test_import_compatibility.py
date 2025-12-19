"""Smoke tests ensuring legacy import paths keep working after refactors.

These tests are intentionally headless (no wx.App / no dialogs).
"""

from __future__ import annotations


def test_service_wrappers_reexport_service_implementations() -> None:
    from sara.ui.announcement_service import AnnouncementService as WrapperAnnouncementService
    from sara.ui.auto_mix_tracker import AutoMixTracker as WrapperAutoMixTracker
    from sara.ui.clipboard_service import ClipboardEntry as WrapperClipboardEntry
    from sara.ui.clipboard_service import PlaylistClipboard as WrapperPlaylistClipboard
    from sara.ui.nvda_sleep import SaraSleepRegistry as WrapperSaraSleepRegistry
    from sara.ui.nvda_sleep import ensure_nvda_sleep_mode as wrapper_ensure_nvda_sleep_mode
    from sara.ui.nvda_sleep import notify_nvda_play_next as wrapper_notify_nvda_play_next
    from sara.ui.undo import InsertOperation as WrapperInsertOperation
    from sara.ui.undo import MoveOperation as WrapperMoveOperation
    from sara.ui.undo import RemoveOperation as WrapperRemoveOperation
    from sara.ui.undo import UndoAction as WrapperUndoAction
    from sara.ui.undo_manager import UndoManager as WrapperUndoManager

    from sara.ui.services.announcement_service import AnnouncementService as ImplAnnouncementService
    from sara.ui.services.auto_mix_tracker import AutoMixTracker as ImplAutoMixTracker
    from sara.ui.services.clipboard_service import ClipboardEntry as ImplClipboardEntry
    from sara.ui.services.clipboard_service import PlaylistClipboard as ImplPlaylistClipboard
    from sara.ui.services.nvda_sleep import SaraSleepRegistry as ImplSaraSleepRegistry
    from sara.ui.services.nvda_sleep import ensure_nvda_sleep_mode as impl_ensure_nvda_sleep_mode
    from sara.ui.services.nvda_sleep import notify_nvda_play_next as impl_notify_nvda_play_next
    from sara.ui.services.undo import InsertOperation as ImplInsertOperation
    from sara.ui.services.undo import MoveOperation as ImplMoveOperation
    from sara.ui.services.undo import RemoveOperation as ImplRemoveOperation
    from sara.ui.services.undo import UndoAction as ImplUndoAction
    from sara.ui.services.undo_manager import UndoManager as ImplUndoManager

    assert WrapperAnnouncementService is ImplAnnouncementService
    assert WrapperAutoMixTracker is ImplAutoMixTracker
    assert WrapperClipboardEntry is ImplClipboardEntry
    assert WrapperPlaylistClipboard is ImplPlaylistClipboard
    assert WrapperSaraSleepRegistry is ImplSaraSleepRegistry
    assert wrapper_ensure_nvda_sleep_mode is impl_ensure_nvda_sleep_mode
    assert wrapper_notify_nvda_play_next is impl_notify_nvda_play_next
    assert WrapperInsertOperation is ImplInsertOperation
    assert WrapperMoveOperation is ImplMoveOperation
    assert WrapperRemoveOperation is ImplRemoveOperation
    assert WrapperUndoAction is ImplUndoAction
    assert WrapperUndoManager is ImplUndoManager


def test_playback_wrappers_reexport_playback_package() -> None:
    from sara.ui.playback_context import PlaybackContext as WrapperPlaybackContext
    from sara.ui.playback_controller import PlaybackController as WrapperPlaybackController
    from sara.ui.playback_controller import PreviewContext as WrapperPreviewContext
    from sara.ui.playback_device_selection import ensure_player as wrapper_ensure_player
    from sara.ui.playback_mixer_support import PlaybackMixerSupportMixin as WrapperPlaybackMixerSupportMixin
    from sara.ui.playback_preview import start_preview as wrapper_start_preview
    from sara.ui.playback_start_item import start_item_impl as wrapper_start_item_impl

    from sara.ui.playback.context import PlaybackContext as ImplPlaybackContext
    from sara.ui.playback.controller import PlaybackController as ImplPlaybackController
    from sara.ui.playback.preview import PreviewContext as ImplPreviewContext
    from sara.ui.playback.device_selection import ensure_player as impl_ensure_player
    from sara.ui.playback.mixer_support import PlaybackMixerSupportMixin as ImplPlaybackMixerSupportMixin
    from sara.ui.playback.preview import start_preview as impl_start_preview
    from sara.ui.playback.start_item import start_item_impl as impl_start_item_impl

    assert WrapperPlaybackContext is ImplPlaybackContext
    assert WrapperPlaybackController is ImplPlaybackController
    assert WrapperPreviewContext is ImplPreviewContext
    assert wrapper_ensure_player is impl_ensure_player
    assert WrapperPlaybackMixerSupportMixin is ImplPlaybackMixerSupportMixin
    assert wrapper_start_preview is impl_start_preview
    assert wrapper_start_item_impl is impl_start_item_impl


def test_file_and_layout_wrappers_reexport_packages() -> None:
    from sara.ui.file_browser import FileBrowser as WrapperFileBrowser
    from sara.ui.file_browser import FileEntry as WrapperFileEntry
    from sara.ui.playlist_layout import PlaylistLayoutManager as WrapperLayoutManager
    from sara.ui.playlist_layout import PlaylistLayoutState as WrapperLayoutState

    from sara.ui.files.browser import FileBrowser as ImplFileBrowser
    from sara.ui.files.browser import FileEntry as ImplFileEntry
    from sara.ui.layout.playlist_layout import PlaylistLayoutManager as ImplLayoutManager
    from sara.ui.layout.playlist_layout import PlaylistLayoutState as ImplLayoutState

    assert WrapperFileBrowser is ImplFileBrowser
    assert WrapperFileEntry is ImplFileEntry
    assert WrapperLayoutManager is ImplLayoutManager
    assert WrapperLayoutState is ImplLayoutState


def test_mix_preview_wrapper_reexports_controller_helpers() -> None:
    from sara.ui.mix_preview import measure_effective_duration as wrapper_measure_effective_duration
    from sara.ui.mix_preview import preview_mix_with_next as wrapper_preview_mix_with_next

    from sara.ui.controllers.mix.preview import measure_effective_duration as impl_measure_effective_duration
    from sara.ui.controllers.mix.preview import preview_mix_with_next as impl_preview_mix_with_next

    assert wrapper_measure_effective_duration is impl_measure_effective_duration
    assert wrapper_preview_mix_with_next is impl_preview_mix_with_next


def test_jingle_controller_wrapper_reexports_controller() -> None:
    from sara.ui.jingle_controller import JingleController as WrapperJingleController
    from sara.ui.jingle_controller import JingleState as WrapperJingleState

    from sara.ui.controllers.jingles.controller import JingleController as ImplJingleController
    from sara.ui.controllers.jingles.controller import JingleState as ImplJingleState

    assert WrapperJingleController is ImplJingleController
    assert WrapperJingleState is ImplJingleState

