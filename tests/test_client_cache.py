from biwenger.client import cache_ttl


def test_news_and_roster_live_longer_than_market() -> None:
    assert cache_ttl("https://biwenger.as.com/api/v2/league/1/news") >= 600
    assert cache_ttl("https://biwenger.as.com/api/v2/user/123") >= 600
    assert cache_ttl("https://biwenger.as.com/api/v2/market") <= 120
    assert cache_ttl("https://biwenger.as.com/api/v2/user") <= 120
