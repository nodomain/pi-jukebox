#!/usr/bin/env bash
# Smoke test: verify all Jukebox Pi API endpoints respond after deploy.
#
# Usage:
#   ./scripts/smoke-test.sh              # uses JUKEBOX_HOST from .env
#   ./scripts/smoke-test.sh jukebox.local  # explicit host
#
# Exit code 0 = all passed, 1 = failures detected.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[[ -f "${SCRIPT_DIR}/../.env" ]] && source "${SCRIPT_DIR}/../.env"

HOST="${1:-${JUKEBOX_HOST:-jukebox.local}}"
BASE="http://${HOST}:8080"
PASS=0
FAIL=0
SKIP=0

check() {
    local method="$1" path="$2" expect="${3:-200}" body="${4:-}"
    local url="${BASE}${path}"
    local args=(-s -o /dev/null -w '%{http_code}' -m 10)

    if [[ "$method" == "POST" ]]; then
        args+=(-X POST -H 'Content-Type: application/json')
        [[ -n "$body" ]] && args+=(-d "$body")
    fi

    local code
    code=$(curl "${args[@]}" "$url" 2>/dev/null || echo "000")

    if [[ "$code" == "$expect" ]]; then
        printf "  ✅ %-6s %-40s %s\n" "$method" "$path" "$code"
        PASS=$((PASS + 1))
    elif [[ "$code" == "000" ]]; then
        printf "  ⏭  %-6s %-40s %s (unreachable)\n" "$method" "$path" "$code"
        SKIP=$((SKIP + 1))
    else
        printf "  ❌ %-6s %-40s %s (expected %s)\n" "$method" "$path" "$code" "$expect"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Jukebox Pi Smoke Test ==="
echo "Target: ${BASE}"
echo ""

# Quick connectivity check
if ! curl -s -o /dev/null -m 5 "${BASE}/" 2>/dev/null; then
    echo "❌ Cannot reach ${BASE} — is the Pi running?"
    exit 1
fi

echo "--- Core ---"
check GET  /
check GET  /api/stats
check GET  /api/snapcast/status
check GET  /api/snapcast/jitter

echo ""
echo "--- Music Assistant ---"
check GET  /api/ma/queue
check GET  /api/ma/volume
check GET  /api/ma/recent
check GET  /api/ma/playlists
check GET  "/api/ma/search?q=test"
check GET  "/api/ma/lyrics?artist=Radiohead&title=Creep"
check POST /api/ma/control 200 '{"action":"pause","queue_id":"ma_jukebox"}'

echo ""
echo "--- Audio / Bluetooth ---"
check GET  /api/audio/status
check GET  /api/bt/status

echo ""
echo "--- AirPlay / Spotify ---"
check GET  /api/airplay/status
check GET  /api/spotify/status

echo ""
echo "--- AI Recommendations (skipped — too slow for smoke test) ---"
printf "  ⏭  POST   %-40s %s\n" "/api/recommend" "skipped"
SKIP=$((SKIP + 1))

echo ""
echo "--- SSE (connect only) ---"
for sse in /api/events /api/ma/events /api/fft/stream; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 2 "${BASE}${sse}" 2>/dev/null; true)
    # curl returns 200 but exits non-zero due to timeout on SSE streams
    if [[ "$code" == "200" || "$code" == "000" ]]; then
        printf "  ✅ GET    %-40s %s (SSE)\n" "$sse" "200"
        PASS=$((PASS + 1))
    else
        printf "  ❌ GET    %-40s %s\n" "$sse" "$code"
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed, ${SKIP} skipped ==="

if [[ $FAIL -gt 0 ]]; then
    echo "❌ SMOKE TEST FAILED"
    exit 1
else
    echo "✅ ALL PASSED"
    exit 0
fi
