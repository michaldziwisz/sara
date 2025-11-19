import os
import pytest
import wx

from sara.ui.file_selection_dialog import FileSelectionDialog


pytestmark = pytest.mark.skipif(
    os.environ.get("WX_RUN_GUI_TESTS") != "1" or not wx.App.IsDisplayAvailable(),
    reason="wx display required (set WX_RUN_GUI_TESTS=1)",
)


def setup_module(module):  # noqa: D401  # pylint: disable=unused-argument
    if not wx.App.IsMainLoopRunning():
        module._app = wx.App()  # type: ignore[attr-defined]


def test_file_dialog_filters_files(tmp_path):
    keep = tmp_path / "keep.mp3"
    keep.write_bytes(b"fake")
    (tmp_path / "skip.wav").write_bytes(b"fake")
    (tmp_path / "folder").mkdir()

    FileSelectionDialog._last_path = tmp_path  # type: ignore[attr-defined]
    dialog = FileSelectionDialog(
        None,
        title="Test",
        wildcard="MP3 (*.mp3)|*.mp3|All files|*.*",
        style=wx.FD_OPEN,
    )
    try:
        files = [entry.name for entry in dialog._entries if entry.kind == "file"]  # type: ignore[attr-defined]
        assert files == [keep.name]
    finally:
        dialog.Destroy()


def test_file_dialog_remembers_last_directory(tmp_path):
    keep = tmp_path / "track.mp3"
    keep.write_bytes(b"fake")
    FileSelectionDialog._last_path = tmp_path  # type: ignore[attr-defined]
    dialog = FileSelectionDialog(None, title="Test", wildcard="All|*.*", style=wx.FD_OPEN)
    try:
        assert dialog._browser.current_path() == tmp_path  # type: ignore[attr-defined]
        dialog._selected_paths = [str(keep)]  # type: ignore[attr-defined]
        dialog.EndModal = lambda *_args, **_kwargs: None  # type: ignore[assignment]
        dialog._confirm_selection()  # type: ignore[attr-defined]
        assert FileSelectionDialog._last_path == tmp_path  # type: ignore[attr-defined]
    finally:
        dialog.Destroy()
