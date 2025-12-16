from pathlib import Path

from sara.jingles import JinglePage, JingleSet, JingleSlot, load_jingle_set, save_jingle_set


def test_jingles_roundtrip_resolves_relative_paths(tmp_path: Path) -> None:
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"RIFF")
    set_path = tmp_path / "jingles.sarajingles"

    jingle_set = JingleSet(
        name="Jingles",
        pages=[
            JinglePage(
                name="Page A",
                slots=[
                    JingleSlot(path=audio, label="Test"),
                ],
            )
        ],
    )
    save_jingle_set(set_path, jingle_set)

    loaded = load_jingle_set(set_path)
    pages = loaded.normalized_pages()
    assert len(pages) == 1
    slots = pages[0].normalized_slots()
    assert slots[0].path == audio.resolve()
    assert slots[0].label == "Test"


def test_jingles_normalizes_to_ten_slots(tmp_path: Path) -> None:
    set_path = tmp_path / "jingles.sarajingles"
    save_jingle_set(set_path, JingleSet(pages=[JinglePage(slots=[JingleSlot()])]))
    loaded = load_jingle_set(set_path)
    slots = loaded.normalized_pages()[0].normalized_slots()
    assert len(slots) == 10

