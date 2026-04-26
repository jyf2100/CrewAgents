#!/usr/bin/env bash
# Pre-commit hook for admin panel
# Install: cp admin/scripts/pre-commit.sh .git/hooks/pre-commit
# Or use with Husky/pre-commit framework.
set -euo pipefail

STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM -- "admin/backend/*.py" 2>/dev/null || true)
STAGED_TS=$(git diff --cached --name-only --diff-filter=ACM -- "admin/frontend/src/*.ts" "admin/frontend/src/*.tsx" 2>/dev/null || true)
STAGED_I18N=$(git diff --cached --name-only --diff-filter=ACM -- "admin/frontend/src/i18n/*.ts" 2>/dev/null || true)

RET=0

# ─── Python: Security patterns ────────────────────────────────────
if [ -n "$STAGED_PY" ]; then
    # Check for timing-unsafe key comparison
    for f in $STAGED_PY; do
        if [ -f "$f" ]; then
            if grep -q "==.*ADMIN_KEY\|ADMIN_KEY.*==\|==.*admin_key\|admin_key.*==" "$f" 2>/dev/null; then
                if ! grep -q "compare_digest" "$f" 2>/dev/null; then
                    echo "FAIL: $f uses == for key comparison (use hmac.compare_digest)"
                    RET=1
                fi
            fi
            # Check for bare except
            if grep -Pq "^\s*except\s*:" "$f" 2>/dev/null; then
                echo "WARN: $f has bare 'except:' — use specific exception types"
            fi
            # Check for hardcoded secrets
            if grep -q "sk-[a-zA-Z0-9]\{20,\}\|password\s*=\s*['\"][^'\"]\{8,\}" "$f" 2>/dev/null; then
                echo "FAIL: $f may contain hardcoded secrets"
                RET=1
            fi
            # Check for print() statements
            PRINT_LINES=$(grep -n "print(" "$f" | grep -v "# " | head -3 || true)
            if [ -n "$PRINT_LINES" ]; then
                echo "WARN: $f has print() — use logging module instead"
                echo "$PRINT_LINES"
            fi
        fi
    done
fi

# ─── TypeScript: console.log ──────────────────────────────────────
if [ -n "$STAGED_TS" ]; then
    for f in $STAGED_TS; do
        if [ -f "$f" ]; then
            if grep -q "console\.log" "$f" 2>/dev/null; then
                echo "FAIL: $f contains console.log"
                grep -n "console\.log" "$f"
                RET=1
            fi
        fi
    done
fi

# ─── i18n: Key sync ───────────────────────────────────────────────
if [ -n "$STAGED_I18N" ]; then
    EN_CHANGED=$(echo "$STAGED_I18N" | grep "en.ts" || true)
    ZH_CHANGED=$(echo "$STAGED_I18N" | grep "zh.ts" || true)
    if [ -n "$EN_CHANGED" ] && [ -z "$ZH_CHANGED" ]; then
        echo "WARN: en.ts changed but zh.ts not updated — verify key sync"
    fi
    if [ -n "$ZH_CHANGED" ] && [ -z "$EN_CHANGED" ]; then
        echo "WARN: zh.ts changed but en.ts not updated — verify key sync"
    fi
fi

# ─── TypeScript: Compilation ──────────────────────────────────────
if [ -n "$STAGED_TS" ]; then
    TSC_OUTPUT=$(cd admin/frontend && npx tsc --noEmit --pretty false 2>&1 || true)
    if [ -n "$TSC_OUTPUT" ]; then
        echo "FAIL: TypeScript compilation errors:"
        echo "$TSC_OUTPUT" | head -15
        RET=1
    fi
fi

exit $RET
