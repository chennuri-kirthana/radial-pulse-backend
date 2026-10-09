"""Write (or check) the OpenAPI document without starting a server.

    uv run python -m app.openapi_export openapi/openapi.json            # write   (make openapi)
    uv run python -m app.openapi_export --check openapi/openapi.json    # verify  (make contract-check)

openapi/openapi.json is THE contract with the frontend. It is committed, reviewed in every
pull request, and attached to each GitHub Release (vX.Y.Z) for the frontend's `api:sync`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app


def render() -> str:
    # Fixed settings so the document is identical on every machine (no env, no git SHA).
    app = create_app(Settings(app_env="local", docs_enabled=True, service_version="contract", _env_file=None))
    schema: dict[str, Any] = app.openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def export(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")


def check(path: Path) -> bool:
    return path.is_file() and path.read_text(encoding="utf-8") == render()


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--check"]
    target = Path(args[0] if args else "openapi/openapi.json")
    if "--check" in argv:
        if check(target):
            sys.stderr.write(f"{target} is up to date\n")
            return 0
        sys.stderr.write(
            f"{target} is out of date. Run `make openapi`, bump CONTRACT_VERSION if needed, "
            "add a line to openapi/CHANGELOG.md and commit.\n"
        )
        return 1
    export(target)
    sys.stderr.write(f"OpenAPI written to {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
