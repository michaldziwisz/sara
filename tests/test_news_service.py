from sara.news_service import NewsService, load_news_service, save_news_service


def test_save_and_load_news_service(tmp_path):
    path = tmp_path / "service.saranews"
    service = NewsService(title="Morning", markdown="# Hello", output_device="dev-1", line_length=40)

    save_news_service(path, service)
    loaded = load_news_service(path)

    assert loaded.title == service.title
    assert loaded.markdown == service.markdown
    assert loaded.output_device == service.output_device
    assert loaded.line_length == service.line_length
