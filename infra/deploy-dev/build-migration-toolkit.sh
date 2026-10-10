#!/usr/bin/env bash
# Build the OFFLINE migration toolkit (called by 1-deploy-network-and-db.sh; can also run alone).
#
#   bash infra/deploy-dev/build-migration-toolkit.sh <toolkit dir> <output tar.gz> [uv version]
#
# WHY: the network has no NAT gateway, so the CloudShell VPC environment that runs the migration
# (step 2) cannot download anything: no uv, no Python, no PyPI, no dnf. This script runs where
# there IS internet (the normal CloudShell) and packs everything step 2 needs:
#   <toolkit dir>/bin/uv            uv, pinned version
#   <toolkit dir>/python/           uv-managed CPython 3.12 (python-build-standalone, relocatable)
#   <toolkit dir>/venv/             the locked runtime dependencies (uv.lock, --no-dev)
#   <toolkit dir>/*.env             any files already in the folder (step 1 puts central-dev.env there)
#   <repo>/                         this source folder (without .git, dist, .venv, caches)
# Both CloudShell kinds run Amazon Linux 2023 on x86_64 with HOME=/home/cloudshell-user, so the
# toolkit works when it is extracted into the same home directory. Step 2 checks both.
set -euo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ $# -ge 2 ]] || fail "usage: build-migration-toolkit.sh <toolkit dir> <output tar.gz> [uv version]"
TOOLKIT_DIR="$1"
TOOLKIT_TAR="$2"
UV_VERSION="${3:-0.12.24}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -f "$REPO_DIR/uv.lock" && -f "$REPO_DIR/alembic.ini" ]] || fail "repo folder not found at $REPO_DIR"
[[ "$TOOLKIT_DIR" == "$HOME"/* ]] || fail "the toolkit dir must be inside \$HOME ($HOME): step 2 extracts it there."
[[ "$(uname -m)" == "x86_64" ]] || fail "build on x86_64 (same CPU as the CloudShell VPC environment); this is $(uname -m)."

mkdir -p "$TOOLKIT_DIR/bin"
echo "== uv $UV_VERSION -> $TOOLKIT_DIR/bin"
curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR="$TOOLKIT_DIR/bin" UV_NO_MODIFY_PATH=1 sh >/dev/null
export PATH="$TOOLKIT_DIR/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="$TOOLKIT_DIR/python" UV_PROJECT_ENVIRONMENT="$TOOLKIT_DIR/venv"
echo "== Python 3.12 -> $UV_PYTHON_INSTALL_DIR"
uv python install 3.12
echo "== Locked runtime dependencies -> $UV_PROJECT_ENVIRONMENT"
(cd "$REPO_DIR" && uv sync --locked --no-dev --python 3.12)
(cd "$REPO_DIR" && UV_OFFLINE=1 uv run --no-sync python -c "import alembic, psycopg, sqlalchemy; print('toolkit imports OK')")

echo "== Packing $TOOLKIT_TAR"
tar -czf "$TOOLKIT_TAR" \
  -C "$(dirname "$TOOLKIT_DIR")" "$(basename "$TOOLKIT_DIR")" \
  -C "$(dirname "$REPO_DIR")" --exclude=.git --exclude=dist --exclude=.venv --exclude=__pycache__ \
     --exclude=.pytest_cache --exclude=.mypy_cache --exclude=.ruff_cache "$(basename "$REPO_DIR")"
echo "   $(du -h "$TOOLKIT_TAR" | cut -f1)  $TOOLKIT_TAR"
