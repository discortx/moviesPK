import pytest

from moviespk_scraper import __version__
from moviespk_scraper.__main__ import build_parser, main


def test_version() -> None:
    assert __version__


def test_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_unknown_job_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["nope"])
