#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATIONS_DIR="${ROOT}/db/migrations"
# Prefer Unix socket + peer auth (no password). TCP to localhost asks for a password on Ubuntu.
DATABASE_URL="${DATABASE_URL:-postgresql:///analytics}"


if ! command -v psql >/dev/null 2>&1; then
  echo "psql was not found. Install PostgreSQL client tools, then run this script again." >&2
  exit 1
fi

echo "Applying migrations to ${DATABASE_URL}"

psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

shopt -s nullglob
files=("${MIGRATIONS_DIR}"/*.sql)
if ((${#files[@]} == 0)); then
  echo "No migration files found in ${MIGRATIONS_DIR}"
  exit 0
fi

for file in "${files[@]}"; do
  filename="$(basename "${file}")"
  already="$(
    psql "${DATABASE_URL}" -Atqc \
      "SELECT 1 FROM schema_migrations WHERE filename = \$\$"${filename}"\$\$"
  )"
  if [[ "${already}" == "1" ]]; then
    echo "skip ${filename}"
    continue
  fi

  echo "apply ${filename}"
  psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -f "${file}"
  psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO schema_migrations (filename) VALUES (\$\$"${filename}"\$\$)"
done

echo "Migrations complete."
