r"""Run a SQL file against PostgreSQL with psycopg (no psql needed).

    uv run --no-sync python scripts/db/run_sql.py infra/sql/create-app-login.sql

Why: the Central DEV migration runner (a CloudShell VPC environment) has no internet, so
`dnf install postgresql16` is not possible there. psycopg is already a locked dependency.

Connection settings come from the environment, never from arguments (they would show in `ps`):
DB_HOST, DB_PORT (5432), DB_NAME (radial_pulse), DB_USER, DB_PASSWORD, DB_SSLMODE (require).

The file is sent as ONE script, so `BEGIN; ... COMMIT;`, `SET LOCAL ...` and `DO $$ ... $$`
blocks behave exactly as under `psql -f`. psql meta-commands (lines starting with `\`, such as
`\set ON_ERROR_STOP 1`) are skipped: errors always stop this script. Rows returned by any
statement are printed as a table; the exit code is 1 on any error.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg


def read_sql(path: Path) -> str:
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("\\")
    ]
    return "\n".join(lines) + "\n"


def print_rows(cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
    if cursor.description is None:
        return
    names = [column.name for column in cursor.description]
    rows = [[("" if value is None else str(value)) for value in row] for row in cursor.fetchall()]
    widths = [
        max(len(name), *(len(row[i]) for row in rows)) if rows else len(name) for i, name in enumerate(names)
    ]
    out = sys.stdout
    out.write(" | ".join(name.ljust(widths[i]) for i, name in enumerate(names)) + "\n")
    out.write("-+-".join("-" * width for width in widths) + "\n")
    for row in rows:
        out.write(" | ".join(value.ljust(widths[i]) for i, value in enumerate(row)) + "\n")
    out.write(f"({len(rows)} rows)\n")


def main(argv: list[str]) -> int:
    scalar = len(argv) == 2 and argv[0] == "--scalar"
    if not (len(argv) == 1 or scalar):
        sys.stderr.write(
            'usage: run_sql.py <file.sql> | run_sql.py --scalar "<one SELECT>"\n'
            "(connection settings from DB_* environment variables)\n"
        )
        return 2
    missing = [name for name in ("DB_HOST", "DB_USER", "DB_PASSWORD") if not os.environ.get(name)]
    if missing:
        sys.stderr.write(f"missing environment variables: {', '.join(missing)}\n")
        return 2
    conninfo = psycopg.conninfo.make_conninfo(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "radial_pulse"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=10,
        application_name="run_sql",
    )
    try:
        # autocommit: the file controls its own transactions (BEGIN/COMMIT), like psql does.
        with psycopg.connect(conninfo, autocommit=True) as connection, connection.cursor() as cursor:
            if scalar:
                # One read-only query; prints the first column of the first row (for shell `if`s).
                cursor.execute(argv[1])
                row = cursor.fetchone()
                sys.stdout.write(f"{'' if row is None else row[0]}\n")
                return 0
            path = Path(argv[0])
            sys.stderr.write(f"running {path} as {os.environ['DB_USER']}@{os.environ['DB_HOST']}\n")
            cursor.execute(read_sql(path))  # the whole file, not a parametrised query
            while True:
                print_rows(cursor)
                if not cursor.nextset():
                    break
    except psycopg.Error as exc:
        # The message never includes the connection string or the password.
        sys.stderr.write(f"FAILED: {exc.__class__.__name__}: {str(exc).strip()}\n")
        return 1
    sys.stderr.write("done\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
