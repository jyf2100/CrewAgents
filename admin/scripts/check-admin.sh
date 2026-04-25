#!/usr/bin/env bash
# Admin Panel CI Checks
# Usage: ./scripts/check-admin.sh [--fix]
#   --fix: Attempt to auto-fix issues (i18n sync, formatting)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADMIN_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$ADMIN_DIR/frontend"
BACKEND_DIR="$ADMIN_DIR/backend"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { PASS=$((PASS+1)); echo -e "${GREEN}PASS${NC} $1"; }
fail() { FAIL=$((FAIL+1)); echo -e "${RED}FAIL${NC} $1"; }
warn() { WARN=$((WARN+1)); echo -e "${YELLOW}WARN${NC} $1"; }

# ─── 1. i18n Key Sync Check ───────────────────────────────────────
echo "=== i18n Key Sync ==="
EN_TMP=$(mktemp)
ZH_TMP=$(mktemp)
trap "rm -f $EN_TMP $ZH_TMP" EXIT
# Extract keys from value assignments (key: "value") not type annotations (key: string)
grep -P '^\s+[a-zA-Z_]\w*\s*:\s*["'"'"']' "$FRONTEND_DIR/src/i18n/en.ts" 2>/dev/null | grep -oP '^\s+\K[a-zA-Z_][a-zA-Z0-9_]*(?=\s*:)' | sort > "$EN_TMP"
grep -P '^\s+[a-zA-Z_]\w*\s*:\s*["'"'"']' "$FRONTEND_DIR/src/i18n/zh.ts" 2>/dev/null | grep -oP '^\s+\K[a-zA-Z_][a-zA-Z0-9_]*(?=\s*:)' | sort > "$ZH_TMP"

if [ ! -s "$EN_TMP" ] || [ ! -s "$ZH_TMP" ]; then
    warn "i18n: Could not extract keys from translation files"
else
    EN_COUNT=$(wc -l < "$EN_TMP")
    ZH_COUNT=$(wc -l < "$ZH_TMP")
    DIFF_OUTPUT=$(diff "$EN_TMP" "$ZH_TMP" || true)
    if [ -z "$DIFF_OUTPUT" ]; then
        pass "i18n: en.ts ($EN_COUNT keys) and zh.ts ($ZH_COUNT keys) are in sync"
    else
        EN_ONLY=$(grep "^<" <<< "$DIFF_OUTPUT" | sed 's/^< //' | tr '\n' ', ')
        ZH_ONLY=$(grep "^>" <<< "$DIFF_OUTPUT" | sed 's/^> //' | tr '\n' ', ')
        [ -n "$EN_ONLY" ] && fail "i18n: Keys only in en.ts: ${EN_ONLY%,}"
        [ -n "$ZH_ONLY" ] && fail "i18n: Keys only in zh.ts: ${ZH_ONLY%,}"
    fi
fi

# ─── 2. console.log Check ─────────────────────────────────────────
echo ""
echo "=== console.log Audit ==="
CONSOLE_LOGS=$(grep -rn "console\.log" "$FRONTEND_DIR/src/" --include="*.ts" --include="*.tsx" 2>/dev/null || true)
if [ -z "$CONSOLE_LOGS" ]; then
    pass "No console.log in frontend source"
else
    fail "console.log found in frontend source:"
    echo "$CONSOLE_LOGS" | head -20
fi

# ─── 3. TypeScript Compilation ────────────────────────────────────
echo ""
echo "=== TypeScript Check ==="
if command -v npx &>/dev/null; then
    TSC_OUTPUT=$(cd "$FRONTEND_DIR" && npx tsc --noEmit 2>&1 || true)
    if [ -z "$TSC_OUTPUT" ]; then
        pass "TypeScript: 0 errors"
    else
        fail "TypeScript errors:"
        echo "$TSC_OUTPUT" | head -20
    fi
else
    warn "npx not found — skipping TypeScript check"
fi

# ─── 4. Frontend Build ────────────────────────────────────────────
echo ""
echo "=== Build Check ==="
if command -v npx &>/dev/null; then
    BUILD_OUTPUT=$(cd "$FRONTEND_DIR" && npm run build 2>&1 || true)
    if echo "$BUILD_OUTPUT" | grep -qi "error"; then
        fail "Frontend build failed"
        echo "$BUILD_OUTPUT" | tail -10
    else
        pass "Frontend build succeeds"
    fi
else
    warn "npx not found — skipping build check"
fi

# ─── 5. Auth Pattern Check ────────────────────────────────────────
echo ""
echo "=== Auth Pattern Check ==="
# Check for == comparison with ADMIN_KEY or admin_key in Python files
BAD_AUTH=$(grep -rn "ADMIN_KEY\|admin_key" "$BACKEND_DIR/" --include="*.py" | grep -v "compare_digest" | grep "==" | grep -v "os\.path" | grep -v "len(" | grep -v "#" || true)
if [ -z "$BAD_AUTH" ]; then
    pass "No timing-unsafe key comparisons"
else
    fail "Timing-unsafe key comparison found (use hmac.compare_digest):"
    echo "$BAD_AUTH"
fi

# ─── 6. Bare except Check ─────────────────────────────────────────
echo ""
echo "=== Bare except Check ==="
BARE_EXCEPT=$(grep -rn "except:" "$BACKEND_DIR/" --include="*.py" | grep -v "except Exception" | grep -v "except HTTP" | grep -v "except ValueError" | grep -v "#" || true)
if [ -z "$BARE_EXCEPT" ]; then
    pass "No bare except clauses"
else
    warn "Bare except found (use specific exception types):"
    echo "$BARE_EXCEPT"
fi

# ─── 7. Hardcoded Secrets Check ───────────────────────────────────
echo ""
echo "=== Hardcoded Secrets Check ==="
SECRETS=$(grep -rn "sk-[a-zA-Z0-9]\{20,\}\|password\s*=\s*['\"][^'\"]\{8,\}\|api_key\s*=\s*['\"][^'\"]\{10,\}" "$BACKEND_DIR/" --include="*.py" | grep -v "os\.environ\|os\.getenv\|config\|test_\|\.example" || true)
if [ -z "$SECRETS" ]; then
    pass "No hardcoded secrets detected"
else
    fail "Possible hardcoded secrets:"
    echo "$SECRETS"
fi

# ─── 8. E2E Test Check ────────────────────────────────────────────
echo ""
echo "=== E2E Tests ==="
E2E_COUNT=$(find "$FRONTEND_DIR/e2e" -name "*.spec.ts" 2>/dev/null | wc -l)
if [ "$E2E_COUNT" -gt 0 ]; then
    pass "$E2E_COUNT E2E test files found"
else
    warn "No E2E test files found"
fi

# ─── Summary ──────────────────────────────────────────────────────
echo ""
echo "================================"
echo -e "Results: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}, ${YELLOW}$WARN warnings${NC}"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
