from pathlib import Path

from sara.ui.file_browser import FileBrowser


def test_file_browser_lists_directories_and_filtered_files(tmp_path):
    subdir = tmp_path / "Samples"
    subdir.mkdir()
    keep = tmp_path / "track.mp3"
    keep.write_bytes(b"x" * 2048)
    (tmp_path / "note.txt").write_text("skip me")

    browser = FileBrowser(start_path=tmp_path)
    entries = browser.list_entries(["*.mp3"])

    assert entries[0].kind == "parent"
    assert entries[1].kind == "dir"

    files = [entry for entry in entries if entry.kind == "file"]
    assert [entry.name for entry in files] == ["track.mp3"]
    assert files[0].size_label == "2 KB"


def test_file_browser_lists_drives_when_path_not_set(tmp_path):
    drives = [tmp_path / "DriveA", tmp_path / "DriveB"]
    browser = FileBrowser(start_path=None, drive_provider=lambda: drives)
    browser.set_current_path(None)
    entries = browser.list_entries(["*.*"])
    assert [entry.kind for entry in entries] == ["drive", "drive"]
    assert [entry.path for entry in entries] == drives


def test_file_browser_go_up_and_reset_to_computer(tmp_path):
    child = tmp_path / "nested"
    child.mkdir()
    browser = FileBrowser(start_path=child)

    browser.go_up()
    assert browser.current_path() == tmp_path

    # go up from tmp root to computer listing
    browser.set_current_path(tmp_path.anchor and Path(tmp_path.anchor) or tmp_path)
    browser.go_up()
    assert browser.current_path() is None
