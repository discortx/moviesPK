"""Cross-language contract suite, Python side (plan §13).

Every valid fixture must pass both the JSON Schema and the Pydantic model; every invalid
fixture must fail both. Pydantic vocabularies must equal ``shared/constants``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from moviespk_scraper.models.contract import CONTRACT_MODELS
from moviespk_scraper.models.vocab import POSTER_KEY_PATTERN, POSTER_WIDTHS, VOCABULARIES

SHARED = Path(__file__).resolve().parents[3] / "shared"
SCHEMAS = SHARED / "schemas"
FIXTURES = SHARED / "fixtures" / "contract"
CONSTANTS = SHARED / "constants"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry() -> Registry:
    resources = []
    for path in SCHEMAS.glob("*.json"):
        schema = _load(path)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


REGISTRY = _registry()


def _validator(type_name: str) -> Draft202012Validator:
    schema = _load(SCHEMAS / f"{type_name}.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=REGISTRY)


def _cases(kind: str) -> list[Any]:
    return [
        pytest.param(p.parent.name, p, id=f"{p.parent.name}/{p.stem}")
        for p in sorted((FIXTURES / kind).glob("*/*.json"))
    ]


def test_every_schema_has_a_model_and_fixtures() -> None:
    types = {p.stem for p in SCHEMAS.glob("*.json")} - {"common"}
    assert types == set(CONTRACT_MODELS)
    for kind in ("valid", "invalid"):
        assert {p.name for p in (FIXTURES / kind).iterdir()} == types, kind


@pytest.mark.parametrize(("type_name", "path"), _cases("valid"))
def test_valid_fixture_passes_everywhere(type_name: str, path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    errors = [e.message for e in _validator(type_name).iter_errors(json.loads(raw))]
    assert errors == []
    CONTRACT_MODELS[type_name].model_validate_json(raw)


@pytest.mark.parametrize(("type_name", "path"), _cases("invalid"))
def test_invalid_fixture_fails_everywhere(type_name: str, path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    assert not _validator(type_name).is_valid(json.loads(raw)), "JSON Schema accepted it"
    with pytest.raises(ValidationError):
        CONTRACT_MODELS[type_name].model_validate_json(raw)


@pytest.mark.parametrize("name", sorted(VOCABULARIES))
def test_vocabulary_matches_shared_constants(name: str) -> None:
    assert list(VOCABULARIES[name]) == _load(CONSTANTS / f"{name}.json")


def test_every_vocabulary_file_is_covered() -> None:
    files = {p.stem for p in CONSTANTS.glob("*.json")} - {"cities", "images", "bounds"}
    assert files == set(VOCABULARIES)


def test_image_constants() -> None:
    images = _load(CONSTANTS / "images.json")
    assert tuple(images["posterWidths"]) == POSTER_WIDTHS
    assert images["posterKeyPattern"] == POSTER_KEY_PATTERN


def test_schema_enums_match_constants() -> None:
    common = _load(SCHEMAS / "common.json")["$defs"]
    assert common["Genre"]["enum"] == _load(CONSTANTS / "genres.json")
    assert common["Language"]["enum"] == _load(CONSTANTS / "languages.json")
    assert common["Format"]["enum"] == _load(CONSTANTS / "formats.json")
    assert common["CinemaHealth"]["properties"]["status"]["enum"] == _load(
        CONSTANTS / "health-statuses.json"
    )
    seat = _load(SCHEMAS / "SeatStatus.json")
    assert seat["properties"]["status"]["enum"] == _load(CONSTANTS / "seat-statuses.json")
