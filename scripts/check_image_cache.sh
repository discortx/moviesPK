#!/usr/bin/env bash
# Workers Caching check for the poster Worker (plan P1-21). Prints one Markdown table row
# per request for docs/performance.md and exits non-zero if an expectation fails.
#
#   scripts/check_image_cache.sh https://moviespk-img-dev.moviespk.workers.dev \
#       movies/<movieId>/poster-<hash8>-w342.webp
#
# Expectations (plan §11.3.2-§11.3.3):
#   poster ×2         → 200 image/webp, immutable 1-year Cache-Control, same ETag, 2nd HIT
#   missing key ×2    → 404, Cache-Control max-age=60, 2nd HIT (U-CF7)
#   rejected path     → 404;  query string → 404;  POST → 405
set -uo pipefail
base="${1:?usage: $0 <worker-url> <object-key>}"
key="${2:?usage: $0 <worker-url> <object-key>}"
poster="$base/img/$key"
missing="$base/img/movies/000000000000000000000000/poster-00000000-w342.webp"
fail=0

row() { # row <label> <want-status> <want-cache-status or -> <curl args...>
  local label=$1 want=$2 want_cache=$3
  shift 3
  local line status ctype cache cc etag
  line=$(curl -s -o /dev/null -m 30 \
    -w '%{http_code}|%{content_type}|%header{cf-cache-status}|%header{cache-control}|%header{etag}' "$@")
  # '|', not a tab: bash merges consecutive whitespace separators, which drops empty fields.
  IFS='|' read -r status ctype cache cc etag <<<"$line"
  local verdict=ok
  [ "$status" = "$want" ] || verdict="FAIL (want $want)"
  if [ "$want_cache" != "-" ] && [ "$cache" != "$want_cache" ]; then verdict="FAIL (want $want_cache)"; fi
  [ "$verdict" = ok ] || fail=1
  printf '| %s | %s | %s | %s | %s | %s | %s |\n' "$label" "$status" "${ctype:--}" "${cache:--}" "${cc:--}" "${etag:--}" "$verdict"
}

echo "| Request | Status | Content-Type | Cf-Cache-Status | Cache-Control | ETag | Verdict |"
echo "|---|---|---|---|---|---|---|"
row "poster, 1st" 200 - "$poster"
row "poster, 2nd" 200 HIT "$poster"
row "missing key, 1st" 404 - "$missing"
row "missing key, 2nd" 404 HIT "$missing"
row "rejected path" 404 - "$base/img/movies/"
row "query string" 404 - "$poster?v=2"
row "POST" 405 - -X POST "$poster"
exit "$fail"
