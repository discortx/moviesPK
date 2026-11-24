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


# --- RFC 9309 matching, independent of the Python version (CI runs 3.12) ---


def _policy(body: str, ua: str = UA) -> RobotsPolicy:
    return RobotsPolicy.from_response(ua, 200, body)


@pytest.mark.parametrize(
    "body",
    [
        "User-agent: *\nDisallow: /booking/\nAllow: /booking/showtimes\n",
        "User-agent: *\nAllow: /booking/showtimes\nDisallow: /booking/\n",
    ],
)
def test_longest_match_wins_regardless_of_order(body: str) -> None:
    policy = _policy(body)
    assert policy.can_fetch("https://e.com/booking/showtimes")
    assert not policy.can_fetch("https://e.com/booking/123")


def test_allow_wins_a_tie() -> None:
    policy = _policy("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert policy.can_fetch("https://e.com/page")


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/api/x.json", False),
        ("/api/x.json?y=1", True),  # $ anchors the end
        ("/a/b/private/c", False),  # * matches any sequence
        ("/search?q=1", False),  # query string is part of the match
        ("/search", True),
    ],
)
def test_wildcards_and_end_anchor(path: str, allowed: bool) -> None:
    body = "User-agent: *\nDisallow: /*.json$\nDisallow: /*/private/\nDisallow: /search?\n"
    assert _policy(body).can_fetch(f"https://e.com{path}") is allowed


def test_empty_disallow_allows_everything() -> None:
    assert _policy("User-agent: *\nDisallow:\n").can_fetch("https://e.com/anything")


def test_agent_match_is_case_insensitive_and_groups_merge() -> None:
    body = (
        "User-agent: moviespkbot\nDisallow: /a/\n\n"
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: MOVIESPKBOT\nDisallow: /b/\n"
    )
    policy = _policy(body)
    assert policy.can_fetch("https://e.com/c")
    assert not policy.can_fetch("https://e.com/a/1")
    assert not policy.can_fetch("https://e.com/b/1")


def test_multiple_agents_share_one_group_and_comments_are_ignored() -> None:
    body = "User-agent: OtherBot\nUser-agent: MoviesPKBot  # us\nDisallow: /x  # no\n"
    assert not _policy(body).can_fetch("https://e.com/x/1")


def test_no_matching_group_allows_all() -> None:
    assert _policy("User-agent: BadBot\nDisallow: /\n").can_fetch("https://e.com/")


def test_robots_txt_itself_is_always_allowed() -> None:
    assert _policy("User-agent: *\nDisallow: /\n").can_fetch("https://e.com/robots.txt")
