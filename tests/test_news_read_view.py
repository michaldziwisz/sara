from sara.news.markdown import parse_news_blocks
from sara.news.read_view import build_read_view


def test_build_read_view_tracks_headings_and_audio():
    blocks = parse_news_blocks(
        """
# Headline
Paragraph text
- list item
[[audio:C:/clip.mp3]]
"""
    )
    model = build_read_view(blocks, line_length=20)
    assert model.heading_lines == [0]
    assert model.audio_markers == [(len(model.lines) - 1, "C:/clip.mp3")]
    assert model.audio_paths == ["C:/clip.mp3"]
    assert any("Audio clip" in line for line in model.lines)
