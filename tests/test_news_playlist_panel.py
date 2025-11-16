import os
from pathlib import Path

import pytest
import wx

from sara.ui.news_playlist_panel import NewsPlaylistPanel


pytestmark = pytest.mark.skipif(
    os.environ.get("WX_RUN_GUI_TESTS") != "1" or not wx.App.IsDisplayAvailable(),
    reason="requires wx display (set WX_RUN_GUI_TESTS=1)",
)


def _panel_with_text(text: str) -> NewsPlaylistPanel:
    class DummyModel:
        id = "news-1"
        name = "News"
        news_markdown = text
        output_device = None
        output_slots = []

    panel = NewsPlaylistPanel(
        None,
        model=DummyModel(),
        get_line_length=lambda: 30,
        get_audio_devices=lambda: [(None, "Default")],
        on_focus=lambda _id: None,
        on_play_audio=lambda _path, _device: None,
        on_device_change=lambda _model: None,
    )
    return panel


def test_parse_blocks_detects_headings_lists_and_audio():
    panel = _panel_with_text("""
# Heading 1
Some text
- bullet
[[audio:C:/clip.mp3]]
    """)

    blocks = panel._parse_blocks(panel.model.news_markdown)  # type: ignore[attr-defined]
    assert blocks[0]["type"] == "heading"
    assert blocks[1]["type"] == "paragraph"
    assert blocks[2]["type"] == "list"
    assert blocks[3]["type"] == "audio"


def test_wrap_text_respects_word_boundaries():
    panel = _panel_with_text("")
    wrapped = panel._wrap_text_lines("longword example text", line_length=10)  # type: ignore[attr-defined]
    assert wrapped[0] == "longword"
    assert wrapped[1] == "example"
    assert wrapped[2] == "text"
