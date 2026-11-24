from __future__ import annotations

import pytest

from moviespk_scraper.core.robots import (
    RobotsDisallowedError,
    RobotsPolicy,
    normalized_text_sha256,
    product_token,
    robots_url,
)

UA = "MoviesPKBot/1.0 (+https://github.com/example/moviespk; contact@example.com)"

SAMPLE = """
User-agent: *
Disallow: /admin/
Disallow: /booking/
Allow: /booking/showtimes
Crawl-delay: 1

User-agent: MoviesPKBot
Disallow: /private/
Crawl-delay: 5

User-agent: BadBot
Disallow: /
"""


def test_robots_url() -> None:
    assert robots_url("https://web.cinepax.com/api/x?y=1") == "https://web.cinepax.com/robots.txt"
    with pytest.raises(ValueError):
        robots_url("/relative")


def test_product_token() -> None:
    assert product_token(UA) == "MoviesPKBot"


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/", True),
        ("/movies", True),
        ("/private/data", False),
        # our own group applies, so the * group's /admin/ rule does not
        ("/admin/x", True),
    ],
)
def test_specific_group_verdicts(path: str, allowed: bool) -> None:
    policy = RobotsPolicy.from_response(UA, 200, SAMPLE)
    assert policy.can_fetch(f"https://example.com{path}") is allowed


@pytest.mark.parametrize(
    ("path", "allowed"),
    [("/admin/x", False), ("/booking/123", False), ("/booking/showtimes", True)],
)
def test_wildcard_group_for_other_agent(path: str, allowed: bool) -> None:
    policy = RobotsPolicy.from_response("OtherBot/2.0", 200, SAMPLE)
    assert policy.can_fetch(f"https://example.com{path}") is allowed


def test_disallowed_raises_before_request() -> None:
    policy = RobotsPolicy.from_response(UA, 200, SAMPLE)
    with pytest.raises(RobotsDisallowedError, match="/private/data"):
        policy.check("https://example.com/private/data")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
def test_4xx_allows_all(status: int) -> None:
    policy = RobotsPolicy.from_response(UA, status)
    assert policy.can_fetch("https://example.com/anything")
    assert not policy.blocked


@pytest.mark.parametrize("status", [500, 503, None])
def test_5xx_or_network_failure_blocks(status: int | None) -> None:
    policy = RobotsPolicy.from_response(UA, status)
    assert not policy.can_fetch("https://example.com/")
    assert policy.blocked


def test_crawl_delay_honoured_only_when_larger() -> None:
    policy = RobotsPolicy.from_response(UA, 200, SAMPLE)
    assert policy.crawl_delay_ms() == 5000
    assert policy.effective_delay_ms(1500) == 5000
    assert policy.effective_delay_ms(8000) == 8000
    assert RobotsPolicy.from_response(UA, 404).effective_delay_ms(1500) == 1500


def test_hash_is_stable_across_cosmetic_whitespace() -> None:
    a = "User-agent: *\nDisallow: /x\n"
    b = "User-agent:   *\r\n\r\n  Disallow: /x  \r\n\n"
    assert normalized_text_sha256(a) == normalized_text_sha256(b)
    assert normalized_text_sha256(a) != normalized_text_sha256("User-agent: *\nDisallow: /y\n")


def test_body_hash_only_when_parsed() -> None:
    assert RobotsPolicy.from_response(UA, 200, SAMPLE).body_sha256() == normalized_text_sha256(
        SAMPLE
    )
    assert RobotsPolicy.from_response(UA, 404).body_sha256() is None
