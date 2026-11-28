"""P2-10 unit: purge window validation, orphan selection, the R2 usage alert."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from botocore.exceptions import ClientError

from moviespk_scraper.core import config
from moviespk_scraper.core.config import ConfigError, load_config, purge_window_problems
from moviespk_scraper.pipeline.maintenance import (
    R2_ALERT_BYTES,
    MaintenanceCounts,
    orphans,
    record_usage,
    usage_alert,
    variant_keys,
)
from moviespk_scraper.services.alerts import GitHubAlerter
from moviespk_scraper.services.r2 import R2Store, StoredObject

from .test_alerts import REPO, FakeGitHub

NOW = datetime(2026, 12, 1, 4, 23, tzinfo=UTC)
WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"


@pytest.fixture
def fake_github() -> Any:
    import respx

    fake = FakeGitHub()
    with respx.mock(assert_all_called=False) as router:
        fake.install(router)
        yield fake


# --- PURGE_AFTER_DAYS -----------------------------------------------------------------------


def test_purge_window_limits() -> None:
    assert purge_window_problems(90) == []
    assert purge_window_problems(112) == []  # 7 + 112 + 1 + 60 = 180
    assert "113 > 112" in purge_window_problems(113)[0]
    assert purge_window_problems(112, export_retention_days=61) != []
    assert any("never exceed 150" in p for p in purge_window_problems(151, 0))
    assert purge_window_problems(0) != []


def test_purge_after_113_fails_config_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    load_config()  # the shipped value (90) is valid
    monkeypatch.setattr(config, "PURGE_AFTER_DAYS", 113)
    with pytest.raises(ConfigError, match="PURGE_AFTER_DAYS 113"):
        load_config()


def test_export_workflow_keeps_the_retention_the_rule_assumes() -> None:
    data = yaml.safe_load((WORKFLOWS / "export.yml").read_text(encoding="utf-8"))
    steps = data["jobs"]["export"]["steps"]
    upload = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
    assert upload["with"]["retention-days"] == config.EXPORT_RETENTION_DAYS


# --- orphans --------------------------------------------------------------------------------


def obj(key: str, age_days: float, size: int = 10) -> StoredObject:
    return StoredObject(key, size, NOW - timedelta(days=age_days))


def test_orphan_selection() -> None:
    kept_stem = "movies/aaa/poster-11111111"
    objects = [
        *(obj(k, 30) for k in variant_keys(kept_stem)),  # referenced: kept
        obj("movies/bbb/poster-22222222-w342.webp", 8),  # orphan, 8 days: deleted
        obj("movies/ccc/poster-33333333-w342.webp", 1),  # orphan, 1 day: grace
        obj("movies/ddd/notes.txt", 30),  # not a variant, unreferenced: deleted
    ]
    found = [o.key for o in orphans(objects, {kept_stem}, NOW)]
    assert found == ["movies/bbb/poster-22222222-w342.webp", "movies/ddd/notes.txt"]


# --- R2 usage --------------------------------------------------------------------------------


class ListOnly:
    def __init__(self, sizes: list[int]) -> None:
        self.objects = [
            obj(f"movies/x/poster-{i:08d}-w780.webp", 1, s) for i, s in enumerate(sizes)
        ]
        self.deleted: list[str] = []

    def list(self, prefix: str) -> list[StoredObject]:
        return [o for o in self.objects if o.key.startswith(prefix)]

    def delete(self, key: str) -> None:
        self.deleted.append(key)


class UploadClient:
    def __init__(self) -> None:
        self.put: list[str] = []

    def head_object(self, **kw: Any) -> None:
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def put_object(self, **kw: Any) -> None:
        self.put.append(kw["Key"])


def test_usage_threshold() -> None:
    assert usage_alert(R2_ALERT_BYTES) is None
    alert = usage_alert(int(1.1 * 1024**3))
    assert alert is not None and alert.title == "[alert] r2: storage"
    assert alert.repeat_after is None and "uploads continue" in alert.summary


def test_simulated_1_1_gb_opens_exactly_one_issue_and_blocks_nothing(
    fake_github: FakeGitHub,
) -> None:
    half = int(0.55 * 1024**3)
    bucket = ListOnly([half, half])  # 1.1 GB
    for day in range(3):  # three daily canaries
        alerter = GitHubAlerter("token", REPO)
        counts = MaintenanceCounts()
        record_usage(bucket, counts, alerter, NOW + timedelta(days=day))
        alerter.close()
        assert counts.r2_bytes == 2 * half and counts.r2_objects == 2
    assert [i["title"] for i in fake_github.issues.values()] == ["[alert] r2: storage"]
    assert fake_github.comments[1] == []
    assert bucket.deleted == []

    client = UploadClient()  # uploads still go through (OD11: no automatic stop)
    assert R2Store(client, "moviespk-dev").ensure("movies/y/poster-1-w185.webp", b"x") is True
    assert client.put == ["movies/y/poster-1-w185.webp"]
