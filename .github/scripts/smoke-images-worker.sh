#!/usr/bin/env bash
# Smoke test a deployed poster Worker (plan P1-20): it answers, and enforces §11.3.2.
# Works with an empty bucket: a well-formed but missing poster must be a cacheable 404.
# Usage: smoke-images-worker.sh https://moviespk-img-dev.moviespk.workers.dev
set -euo pipefail
base="${1:?usage: $0 <worker base URL>}"
missing="$base/img/movies/000000000000000000000000/poster-00000000-w342.webp"
fail=0

check() { # check <label> <expected status> <expected header or -> <curl args...>
  local label=$1 want=$2 header=$3
  shift 3
  local out status header_ok
  # Right after the FIRST deploy of a workers.dev hostname, Cloudflare answers with its own
  # 404 (without our headers) until the Worker is attached. So retry until both the status
  # and the header match, for up to about 2 minutes (seen on 2026-11-28).
  for _ in $(seq 1 12); do
    out=$(curl -s -o /dev/null -D - --max-time 15 "$@" || true)
    status=$(printf '%s' "$out" | awk 'toupper($1) ~ /^HTTP/ {code=$2} END {print code}')
    header_ok=yes
    if [ "$header" != "-" ] && ! printf '%s' "$out" | tr -d '\r' | grep -qi "^$header"; then
      header_ok=no
    fi
    if [ "$status" = "$want" ] && [ "$header_ok" = yes ]; then break; fi
    sleep 10
  done
  if [ "$status" != "$want" ]; then
    echo "FAIL $label: got ${status:-no answer}, want $want"
    fail=1
    return
  fi
  if [ "$header_ok" != yes ]; then
    echo "FAIL $label: missing header '$header'"
    fail=1
    return
  fi
  echo "ok   $label ($status)"
}

check "missing poster is a cacheable 404" 404 "cache-control: public, max-age=60" "$missing"
check "rejected path is a 404" 404 - "$base/img/movies/"
check "query string is a 404" 404 - "$missing?v=2"
check "POST is a 405" 405 "allow: GET, HEAD" -X POST "$missing"
exit "$fail"
