"""Check a built Lambda ZIP before it is uploaded. Reads the ZIP only; changes nothing.

    uv run python scripts/lambda/verify_zip.py dist/deployment/radial-pulse-api-dev-x86_64.zip
    uv run python scripts/lambda/verify_zip.py <zip> --arch arm64

Fails (exit 1) if any of these is wrong:

* layout: ``run.sh`` at the root (mode 755, LF line endings, starts uvicorn with ``app.main:app``),
  ``app/main.py`` present, no tests / docs / migrations / git / virtualenv folders
* secrets: no ``.env`` file, no private key, no AWS access key id
* platform: every compiled dependency is a Linux build for the CPU and Python 3.12;
  no Windows or macOS binaries; ``psycopg_binary``, ``cryptography``, ``pydantic_core`` present
* size: unzipped package + about 10 MB for the adapter layer fits Lambda's 250 MB limit
* checksum: matches the ``.sha256`` file next to the ZIP (when that file exists)

Prints a warning (not a failure) when the ZIP is over 50 MB: then it must go through S3.
See docs/infrastructure/lambda-package.md.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

PYTHON_TAG = "cp312"
WHEEL_ARCH = {"x86_64": "x86_64", "arm64": "aarch64"}
REQUIRED_NATIVE = ("psycopg_binary", "cryptography", "pydantic_core")
DIRECT_UPLOAD_LIMIT = 50 * 1024 * 1024
UNZIPPED_LIMIT = 250 * 1024 * 1024
LAYER_ALLOWANCE = 10 * 1024 * 1024
FOREIGN_BINARIES = (".pyd", ".dll", ".exe", ".dylib")
# Top-level entries that must never be in the package. (``alembic/`` itself is the Alembic LIBRARY,
# a runtime dependency; the repo's migrations would show up as ``alembic/versions/``.)
FORBIDDEN_TOP = {
    "tests",
    "docs",
    "db",
    "infra",
    "sdk",
    "scripts",
    ".git",
    ".venv",
    "venv",
    "dist",
    "alembic.ini",
}
FORBIDDEN_PREFIXES = ("alembic/versions/", "alembic/env.py")
# Public CA bundles that libraries ship on purpose (certificates, not keys).
CA_BUNDLES = re.compile(r"^(certifi|botocore)/cacert\.pem$")
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
AWS_KEY_ID = re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
# AWS documentation placeholders (botocore's API examples), not real keys: they end in EXAMPLE.
AWS_EXAMPLE_KEY_ID = re.compile(rb"^(?:AKIA|ASIA)[0-9A-Z]{4,12}EXAMPLE$")
# Library files that hold a private-key HEADER on purpose: botocore's IAM API example (a sample
# server certificate upload) and cryptography's OpenSSH key parser (the header as a constant).
KEY_HEADER_EXPECTED = re.compile(
    r"^(botocore/data/iam/[0-9-]+/examples-1\.json"
    r"|cryptography/hazmat/primitives/serialization/(__pycache__/)?ssh(\.cpython-312\.pyc|\.py))$"
)


def check_layout(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
    problems: list[str] = []
    if "run.sh" not in names:
        return ["run.sh is not at the ZIP root"]
    info = archive.getinfo("run.sh")
    mode = (info.external_attr >> 16) & 0o777
    if mode != 0o755:
        problems.append(f"run.sh mode is {oct(mode)}, expected 0o755")
    script = archive.read("run.sh")
    if b"\r\n" in script:
        problems.append("run.sh has CRLF line endings (will not run on Linux)")
    if not script.startswith(b"#!/bin/sh"):
        problems.append("run.sh does not start with #!/bin/sh")
    if b"uvicorn app.main:app" not in script:
        problems.append("run.sh does not start uvicorn with app.main:app")
    for required in ("app/__init__.py", "app/main.py", "app/core/config.py"):
        if required not in names:
            problems.append(f"missing {required}")
    if "app/__pycache__/main.cpython-312.pyc" not in names:
        problems.append("app is not precompiled for Python 3.12 (app/__pycache__/main.cpython-312.pyc)")
    tops = {name.split("/", 1)[0] for name in names}
    problems += [f"must not be packaged: {top}" for top in sorted(tops & FORBIDDEN_TOP)]
    problems += [f"must not be packaged: {n}" for n in names if n.startswith(FORBIDDEN_PREFIXES)]
    if ".lock" in names:
        problems.append("stray .lock file at the ZIP root")
    return problems


def check_secrets(archive: zipfile.ZipFile, names: list[str]) -> list[str]:
    problems: list[str] = []
    for name in names:
        base = name.rsplit("/", 1)[-1]
        if base == ".env" or base.startswith(".env."):
            problems.append(f"environment file: {name}")
        if base.endswith((".pem", ".key", ".p12", ".pfx")) and not CA_BUNDLES.match(name):
            problems.append(f"key/certificate file: {name}")
        data = archive.read(name)
        if PRIVATE_KEY.search(data) and not KEY_HEADER_EXPECTED.match(name):
            problems.append(f"private key inside: {name}")
        for key_id in set(AWS_KEY_ID.findall(data)):
            if not AWS_EXAMPLE_KEY_ID.match(key_id):
                problems.append(f"AWS access key id {key_id[:4].decode()}... inside: {name}")
    return problems


def check_platform(archive: zipfile.ZipFile, names: list[str], arch: str) -> tuple[list[str], list[str]]:
    machine = WHEEL_ARCH[arch]
    native: list[str] = []
    problems: list[str] = []
    for name in names:
        if not name.endswith(".dist-info/WHEEL"):
            continue
        dist = name.split("/", 1)[0].removesuffix(".dist-info")
        tags = [
            line.split(":", 1)[1].strip()
            for line in archive.read(name).decode().splitlines()
            if line.startswith("Tag:")
        ]
        if {tag.split("-")[2] for tag in tags} == {"any"}:
            continue
        native.append(dist)
        if not any(
            "linux" in tag.split("-")[2]
            and machine in tag.split("-")[2]
            and (tag.split("-")[0] == PYTHON_TAG or tag.split("-")[1] == "abi3")
            for tag in tags
        ):
            problems.append(f"not a Linux {machine} Python 3.12 build: {dist} ({', '.join(tags)})")
    problems += [f"non-Linux binary: {n}" for n in names if n.lower().endswith(FOREIGN_BINARIES)]
    present = {dist.split("-")[0].lower() for dist in native}
    problems += [f"missing native dependency: {dep}" for dep in REQUIRED_NATIVE if dep not in present]
    return native, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("zip", type=Path)
    parser.add_argument("--arch", choices=sorted(WHEEL_ARCH), default="x86_64")
    args = parser.parse_args(argv)

    path: Path = args.zip
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    problems: list[str] = []
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            problems.append(f"corrupt entry: {bad}")
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
        unzipped = sum(i.file_size for i in archive.infolist())
        problems += check_layout(archive, names)
        problems += check_secrets(archive, names)
        native, platform_problems = check_platform(archive, names, args.arch)
        problems += platform_problems

    checksum_file = path.with_name(path.name + ".sha256")
    if checksum_file.is_file():
        expected = checksum_file.read_text().split()[0]
        if expected != digest:
            problems.append(f"SHA-256 differs from {checksum_file.name}")
    if unzipped + LAYER_ALLOWANCE > UNZIPPED_LIMIT:
        problems.append("package + adapter layer is over Lambda's 250 MB unzipped limit")

    out = sys.stdout
    out.write(f"{path.as_posix()}\n")
    out.write(f"  files     {len(names)}\n")
    out.write(f"  zipped    {len(data)} bytes ({len(data) / 1_048_576:.1f} MiB)\n")
    out.write(f"  unzipped  {unzipped} bytes ({unzipped / 1_048_576:.1f} MiB)\n")
    out.write(f"  sha256    {digest}\n")
    out.write(f"  native    {', '.join(native)}\n")
    if len(data) > DIRECT_UPLOAD_LIMIT:
        out.write("  WARNING   over 50 MB zipped: upload to S3, then update the function from S3\n")
    if problems:
        out.write("FAILED\n  " + "\n  ".join(problems) + "\n")
        return 1
    out.write("OK: layout, secrets, platform, size and checksum checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
