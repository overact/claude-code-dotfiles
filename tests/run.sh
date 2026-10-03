#!/usr/bin/env bash
# Run every tests/test_*.sh; exit non-zero if any fails.
set -uo pipefail
cd "$(dirname "$0")"
fail=0
for t in test_*.sh; do
  if bash "$t"; then echo "ok    $t"; else echo "FAIL  $t"; fail=1; fi
done
exit $fail
