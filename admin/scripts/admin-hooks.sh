#!/usr/bin/env bash
# Claude Code hooks for admin/ frontend development
# These are called by Claude Code's PostToolUse hook system.
#
# File: admin/scripts/admin-hooks.sh
# Usage in .claude/settings.json hooks configuration:
#   "command": "admin/scripts/admin-hooks.sh tsc \"$FILE_PATH\""
#   "command": "admin/scripts/admin-hooks.sh console-log \"$FILE_PATH\""

set -euo pipefail

ACTION="${1:-}"
FILE_PATH="${2:-}"
ADMIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"

case "$ACTION" in
    tsc)
        # Only check TypeScript files in admin/frontend
        case "$FILE_PATH" in
            */admin/frontend/src/*.ts|*/admin/frontend/src/*.tsx)
                cd "$ADMIN_DIR/frontend"
                ERRORS=$(npx tsc --noEmit --pretty false 2>&1 || true)
                if [ -n "$ERRORS" ]; then
                    echo "[Hook] TypeScript errors after editing $FILE_PATH:"
                    echo "$ERRORS" | head -20
                    exit 2
                fi
                ;;
        esac
        ;;

    console-log)
        case "$FILE_PATH" in
            */admin/frontend/src/*.ts|*/admin/frontend/src/*.tsx)
                if grep -q "console\.log" "$FILE_PATH" 2>/dev/null; then
                    LINES=$(grep -n "console\.log" "$FILE_PATH" | head -5)
                    echo "[Hook] BLOCKED: console.log found in $FILE_PATH"
                    echo "$LINES"
                    echo "[Hook] Use proper logging or remove before committing"
                    exit 2
                fi
                ;;
        esac
        ;;

    i18n-sync)
        # Check if both en.ts and zh.ts were modified together
        EN_TS="$ADMIN_DIR/frontend/src/i18n/en.ts"
        ZH_TS="$ADMIN_DIR/frontend/src/i18n/zh.ts"
        case "$FILE_PATH" in
            */i18n/en.ts)
                if ! git diff --name-only HEAD 2>/dev/null | grep -q "zh.ts"; then
                    echo "[Hook] WARNING: en.ts modified but zh.ts not updated"
                    echo "[Hook] Ensure i18n keys are synced in both files"
                fi
                ;;
            */i18n/zh.ts)
                if ! git diff --name-only HEAD 2>/dev/null | grep -q "en.ts"; then
                    echo "[Hook] WARNING: zh.ts modified but en.ts not updated"
                    echo "[Hook] Ensure i18n keys are synced in both files"
                fi
                ;;
        esac
        ;;

    auth-pattern)
        case "$FILE_PATH" in
            */admin/backend/*.py)
                if grep -q "==.*ADMIN_KEY\|ADMIN_KEY.*==" "$FILE_PATH" 2>/dev/null; then
                    if ! grep -q "compare_digest" "$FILE_PATH" 2>/dev/null; then
                        echo "[Hook] BLOCKED: Timing-unsafe admin key comparison"
                        echo "[Hook] Use hmac.compare_digest() instead of =="
                        exit 2
                    fi
                fi
                ;;
        esac
        ;;

    *)
        echo "[Hook] Unknown action: $ACTION"
        exit 1
        ;;
esac
