"""Offline mode: serve HTTP from a saved fixture directory (plan P1-04 ``--offline``).

A fixture directory (written by the P1-05 capture tool) holds ``manifest.json``::

    {
      "cinema_id": "cinepax-packages-mall",
      "captured_at": "2026-11-26T05:00:00Z",
      "responses": [
        {"url": "https://web.cinepax.com/robots.txt", "status": 404,
         "headers": {"content-type": "text/html"}, "body": "000-robots.txt"},
        {"url": "https://web.cinepax.com/api/movies?cinemaId=0000000014", "status": 200,
         "headers": {"content-type": "application/json"}, "body": "001-movies.json"}
      ]
    }

``body`` names a file next to the manifest. URLs match exactly, query string included.
Nothing ever reaches the network: an unrecorded ``/robots.txt`` answers 404 (allow all, as
if the site had none) and any other unrecorded URL raises :class:`FixtureMissingError`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

MANIFEST = "manifest.json"


class FixtureMissingError(LookupError):
    pass


@dataclass(frozen=True)
class FixtureResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def load_fixtures(directory: Path) -> dict[str, FixtureResponse]:
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no {MANIFEST} in fixture directory {directory}")
    manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    responses: dict[str, FixtureResponse] = {}
    for entry in manifest.get("responses", []):
        body_path = (directory / entry["body"]).resolve()
        if directory.resolve() not in body_path.parents:
            raise ValueError(f"fixture body outside the fixture directory: {entry['body']}")
        responses[entry["url"]] = FixtureResponse(
            status=int(entry["status"]),
            headers={str(k): str(v) for k, v in entry.get("headers", {}).items()},
            body=body_path.read_bytes(),
        )
    return responses


class FixtureTransport(httpx.BaseTransport):
    """An httpx transport that answers only from recorded fixtures."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.responses = load_fixtures(directory)
        self.requested: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        recorded = self.responses.get(url)
        if recorded is None:
            if request.url.path == "/robots.txt":
                return httpx.Response(404, request=request)
            raise FixtureMissingError(f"no fixture for {request.url.path} in {self.directory}")
        return httpx.Response(
            recorded.status, headers=recorded.headers, content=recorded.body, request=request
        )
