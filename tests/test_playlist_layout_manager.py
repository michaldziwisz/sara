from sara.ui.playlist_layout import PlaylistLayoutManager, PlaylistLayoutState


def test_add_and_cycle_playlists():
    manager = PlaylistLayoutManager()
    manager.add_playlist("a")
    manager.add_playlist("b")
    assert manager.state.order == ["a", "b"]
    assert manager.state.current_id == "a"
    assert manager.cycle() == "b"
    assert manager.cycle(backwards=True) == "a"


def test_apply_order_and_remove_updates_state():
    state = PlaylistLayoutState(order=["a", "b", "c"], current_id="b")
    manager = PlaylistLayoutManager(state)
    manager.apply_order(["c", "a"])
    assert manager.state.order == ["c", "a", "b"]
    manager.remove_playlist("c")
    assert manager.state.order == ["a", "b"]
    assert manager.state.current_id == "b"
