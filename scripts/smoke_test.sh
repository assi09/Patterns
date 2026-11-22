#!/usr/bin/env bash
# Smoke test of a deployed Patterns: is the API up and wired, and does the web app load and
# point at it? No sign-in, no data, no model calls, so it costs nothing and touches no one's
# records. Run by .github/workflows/deploy-smoke.yml after each Railway deploy, or by hand:
#
#   scripts/smoke_test.sh https://<api> https://<web>
set -uo pipefail

API="${1:?usage: smoke_test.sh <api-url> <web-url>}"
WEB="${2:?usage: smoke_test.sh <api-url> <web-url>}"
API="${API%/}"
WEB="${WEB%/}"
failures=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

# A deploy that just switched over can take a moment to answer: retry the health check.
health=""
for _ in $(seq 1 18); do
  health=$(curl -s --max-time 10 "$API/health") && [ "$health" = '{"status":"ok"}' ] && break
  sleep 10
done
[ "$health" = '{"status":"ok"}' ] && pass "API /health answers ok" || fail "API /health: '$health'"

status=$(curl -s -o "$tmp/me" -w '%{http_code}' --max-time 10 "$API/auth/me")
if [ "$status" = 401 ] && grep -q '"code":"signed_out"' "$tmp/me"; then
  pass "a call without a session is refused with the API's error shape"
else
  fail "GET /auth/me without a token: $status $(head -c 200 "$tmp/me")"
fi

status=$(curl -s -o "$tmp/login" -w '%{http_code}' --max-time 10 -X POST "$API/auth/login" \
  -H 'content-type: application/json' -d '{"email": 1}')
if [ "$status" = 422 ] && grep -q '"code":"invalid_request"' "$tmp/login"; then
  pass "an invalid body is rejected as invalid_request"
else
  fail "POST /auth/login with a bad body: $status $(head -c 200 "$tmp/login")"
fi

status=$(curl -s -o "$tmp/openapi" -w '%{http_code}' --max-time 10 "$API/openapi.json")
if [ "$status" = 200 ] && grep -q '"/chat"' "$tmp/openapi"; then
  pass "the API schema lists the chat route"
else
  fail "GET /openapi.json: $status"
fi

status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$API/metrics")
case "$status" in
  401 | 404) pass "/metrics is not open without its token ($status)" ;;
  *) fail "GET /metrics without a token answered $status" ;;
esac

allowed=$(curl -s -o /dev/null -D - --max-time 10 -X OPTIONS "$API/auth/login" \
  -H "Origin: $WEB" -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type' |
  tr -d '\r' | awk -F': ' 'tolower($1) == "access-control-allow-origin" {print $2}')
[ "$allowed" = "$WEB" ] && pass "the API allows the web app's origin" \
  || fail "CORS preflight from $WEB allowed '$allowed'"

status=$(curl -s -o "$tmp/web" -w '%{http_code}' --max-time 15 "$WEB/")
if [ "$status" = 200 ] && grep -q '<title>Patterns' "$tmp/web"; then
  pass "the web app loads"
else
  fail "GET $WEB/: $status"
fi

status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$WEB/settings")
[ "$status" = 200 ] && pass "an app route loads directly (/settings)" || fail "GET $WEB/settings: $status"

# The API address is built into the web bundle: it must be this API's.
api_host="${API#https://}"
found=0
for script in $(grep -o 'src="/_expo/static/js/web/[^"]*"' "$tmp/web" | sed 's/^src="//; s/"$//'); do
  curl -s --max-time 30 -o "$tmp/bundle" "$WEB$script"
  if grep -q "$api_host" "$tmp/bundle"; then found=1; fi
done
[ "$found" = 1 ] && pass "the web bundle points at $api_host" \
  || fail "no web bundle mentions $api_host"

if [ "$failures" -gt 0 ]; then
  printf '\n%s check(s) failed\n' "$failures"
  exit 1
fi
printf '\nall checks passed\n'
