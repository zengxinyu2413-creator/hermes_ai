#!/usr/bin/env bash
# Usage: ./scripts/migrate.sh {apply|rollback|list|status|help} [yoyo-options...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MIGRATIONS_DIR="${PROJECT_ROOT}/src/hermes/data/migrations"
ENV_FILE="${PROJECT_ROOT}/infra/.env"

# ── guards ───────────────────────────────────────────────────────────────────

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: ${ENV_FILE} not found. Copy infra/.env.example to infra/.env." >&2
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

for var in TSDB_USER TSDB_PASSWORD TSDB_HOST TSDB_PORT TSDB_DB; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: ${var} is not set in ${ENV_FILE}." >&2
        exit 1
    fi
done

if ! timeout 3 bash -c "echo >/dev/tcp/${TSDB_HOST}/${TSDB_PORT}" 2>/dev/null; then
    echo "ERROR: Cannot reach ${TSDB_HOST}:${TSDB_PORT}. Is hermes-tsdb running?" >&2
    exit 1
fi

# ── dispatch ──────────────────────────────────────────────────────────────────

COMMAND="${1:-}"
shift || true

cd "${MIGRATIONS_DIR}"

case "${COMMAND}" in
    apply)
        yoyo apply "$@"
        ;;
    rollback)
        yoyo rollback "$@"
        ;;
    list|status)
        yoyo list "$@"
        ;;
    -h|--help|help)
        cat <<EOF
Usage: $(basename "$0") <command> [yoyo-options...]

Commands:
    apply           Apply pending migrations
    rollback        Rollback last migration (use -n N to rollback N steps)
    list, status    Show migration status
    help            Show this help

Database credentials are read from infra/.env (TSDB_* variables).
The database URL is interpolated into yoyo.ini at runtime — no credentials
appear in process arguments.
EOF
        exit 0
        ;;
    *)
        echo "Unknown command: ${COMMAND:-<empty>}. Run 'help' for usage." >&2
        exit 1
        ;;
esac
