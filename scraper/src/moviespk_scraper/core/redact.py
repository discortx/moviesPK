"""Strip cookies and credentials from captured payloads (fixtures, P1-05; debug artifacts,
§10.3 step 1). Deliberately narrow: ids such as ``sessionId`` (the show id) are data and
must survive."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlsplit

KEPT_HEADERS = frozenset({"content-type", "etag", "last-modified", "location"})
#: Keys whose string values are credentials.
SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|csrf|xsrf|api_?key|authori[sz]ation|cookie)$|^auth$", re.I
)
HIDDEN_TOKEN = re.compile(
    r'(<input[^>]*name="[^"]*(?:token|csrf|viewstate|eventvalidation)[^"]*"[^>]*value=")[^"]*(")',
    re.I,
)
REDACTED = "REDACTED"


def redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if SECRET_KEY.search(str(k)) and isinstance(v, str) else redact_json(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_json(v) for v in value]
    return value


def clean_body(content_type: str, body: bytes) -> tuple[bytes, str]:
    """The cleaned body and the file extension to store it under."""
    text = body.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return body, ".txt"
        cleaned = json.dumps(redact_json(data), indent=2, ensure_ascii=False) + "\n"
        return cleaned.encode(), ".json"
    if "html" in content_type:
        return HIDDEN_TOKEN.sub(rf"\g<1>{REDACTED}\g<2>", text).encode(), ".html"
    return body, ".txt"


def url_has_secret_params(url: str) -> bool:
    return any(
        SECRET_KEY.search(key) for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)
    )
