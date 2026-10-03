# Shared helpers: a throwaway HOME / CLAUDE_CONFIG_DIR per test, and assertions.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "  assertion failed: $*" >&2; exit 1; }
eq() { [ "$1" = "$2" ] || fail "expected [$2], got [$1]${3:+ ($3)}"; }
