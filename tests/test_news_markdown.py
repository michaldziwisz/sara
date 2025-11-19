from sara.news.markdown import parse_news_blocks, wrap_news_text


def test_parse_blocks_detects_headings_lists_and_audio():
    blocks = parse_news_blocks(
        """
# Heading 1
Some text
- bullet
[[audio:C:/clip.mp3]]
"""
    )

    assert [block.kind for block in blocks] == ["heading", "paragraph", "list", "audio"]
    heading = blocks[0]
    assert heading.level == 1
    assert heading.text == "Heading 1"
    assert blocks[-1].path == "C:/clip.mp3"


def test_wrap_text_respects_word_boundaries():
    wrapped = wrap_news_text("longword example text", line_length=10)
    assert wrapped == ["longword", "example", "text"]
