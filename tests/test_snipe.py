from datetime import datetime, timezone

from biwenger import snipe, state
from biwenger.models import MarketListing


def test_add_and_due_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    now = int(datetime.now(timezone.utc).timestamp())
    snipe.add(10, "Crack", 1_000_000, now + 60, None)
    ready = snipe.due(now)
    assert len(ready) == 1
    assert ready[0]["name"] == "Crack"


def test_not_due_if_far(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    now = 1_700_000_000
    snipe.add(11, "Lejos", 1_000_000, now + 3600, None)
    assert snipe.due(now) == []


def test_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state, "_path", lambda: tmp_path / "state.json")
    snipe.add(12, "X", 1, 9_999_999_999, None)
    assert snipe.cancel(12) is True
    assert snipe.pending() == []


def test_visible_bids_flag() -> None:
    item = MarketListing(
        player_id=1,
        price=100,
        until=datetime.now(timezone.utc),
        bid_count=2,
    )
    assert item.has_visible_bids is True
