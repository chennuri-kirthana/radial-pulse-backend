"""Build the AWS Lambda ZIP package for the API (Python 3.12 runtime + AWS Lambda Web Adapter).

    uv run python scripts/lambda/build_zip.py                 # x86_64 (default)
    uv run python scripts/lambda/build_zip.py --arch arm64

Works the same on Windows, macOS and Linux. Dependencies come from ``uv.lock`` (exact versions
and hashes, no dev tools) as **Linux wheels** for the Lambda Python 3.12 runtime (Amazon Linux
2023, glibc 2.34), never from the machine that runs the build. Output:

    dist/lambda/radial-pulse-api-<arch>.zip       the package (upload this)
    dist/lambda/radial-pulse-api-<arch>.zip.sha256

Files are staged in the system temp folder (not in the checkout, which may sit in a synced
folder such as OneDrive) and removed afterwards.

The same inputs give a byte-identical ZIP: fixed file order, dates and modes, and hash-based
``.pyc`` files compiled with a fixed hash seed. The package holds only ``app/``, ``run.sh`` and
the runtime dependencies. Settings and secrets come from the Lambda environment at run time.
See docs/infrastructure/lambda-package.md.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import py_compile
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = ROOT / "dist" / "lambda"
RUN_SCRIPT = Path(__file__).resolve().parent / "run.sh"

PYTHON_VERSION = (3, 12)
# Lambda python3.12 runs on Amazon Linux 2023 (glibc 2.34): accept wheels built for glibc <= 2.34.
PLATFORMS = {"x86_64": "x86_64-manylinux_2_34", "arm64": "aarch64-manylinux_2_34"}
WHEEL_ARCH = {"x86_64": "x86_64", "arm64": "aarch64"}
# Dependencies with compiled code that the API cannot start without. The build fails if any of
# them is missing or not a Linux build.
REQUIRED_NATIVE = ("psycopg_binary", "cryptography", "pydantic_core")

LAMBDA_TASK_ROOT = "/var/task"
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
FILE_MODE = 0o100644
EXEC_MODE = 0o100755
# AWS limits: 50 MB zipped for a direct upload (else upload through S3); 250 MB unzipped
# for the function plus all its layers. Keep room for the Lambda Web Adapter layer.
DIRECT_UPLOAD_LIMIT = 50 * 1024 * 1024
UNZIPPED_LIMIT = 250 * 1024 * 1024
LAYER_ALLOWANCE = 10 * 1024 * 1024
FOREIGN_BINARIES = (".pyd", ".dll", ".exe", ".dylib")
# C/Cython sources some wheels ship next to their compiled module. Only used to build the
# wheel, never imported.
BUILD_ONLY_SOURCES = (".c", ".pyx", ".pxd", ".pxi")


def say(message: str) -> None:
    sys.stdout.write(message + "\n")
    sys.stdout.flush()


def run(cmd: list[str]) -> None:
    # Fixed argument list, no shell: nothing from outside is interpolated.
    subprocess.run(cmd, check=True, cwd=ROOT)  # noqa: S603


def find_uv() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise SystemExit("uv not found. Install it (https://docs.astral.sh/uv/) or set UV=<path to uv>.")
    return uv


def remove_tree(path: Path) -> None:
    """Delete the staging folder. Windows refuses to delete read-only files: clear the flag, retry."""

    def retry_writable(func: object, failed_path: str, _exc: BaseException) -> None:
        Path(failed_path).chmod(stat.S_IWRITE)
        func(failed_path)  # type: ignore[operator]

    shutil.rmtree(path, onexc=retry_writable)


def install_dependencies(uv: str, arch: str, work: Path, site: Path) -> None:
    requirements = work / "requirements.txt"
    # Runtime dependencies only (no dev tools, not the project itself), pinned with hashes.
    run(
        [
            uv, "export", "--quiet", "--locked", "--no-dev", "--no-emit-project",
            "--format", "requirements-txt", "--output-file", str(requirements),
        ]
    )  # fmt: skip
    run(
        [
            uv, "pip", "install", "--quiet",
            "--requirements", str(requirements),
            "--target", str(site),
            "--python-platform", PLATFORMS[arch],
            "--python-version", ".".join(map(str, PYTHON_VERSION)),
            "--only-binary", ":all:",
            "--no-deps",  # the export is already the complete, locked set
            "--link-mode", "copy",
        ]
    )  # fmt: skip
    # Console scripts point at the build machine's Python; run.sh uses `python -m` instead.
    shutil.rmtree(site / "bin", ignore_errors=True)
    for path in [p for p in site.rglob("*") if p.suffix in BUILD_ONLY_SOURCES and p.is_file()]:
        path.unlink()


def add_application(site: Path) -> None:
    shutil.copytree(ROOT / "app", site / "app", ignore=shutil.ignore_patterns("__pycache__", "*.py[co]"))
    # LF line endings even if the checkout converted them (a CRLF shebang does not run on Linux).
    (site / "run.sh").write_bytes(RUN_SCRIPT.read_bytes().replace(b"\r\n", b"\n"))


def compile_bytecode(site: Path) -> int:
    """Precompile everything: Lambda's file system is read-only, so Python cannot cache .pyc there.

    Hash-based (no timestamps) and with Lambda paths in tracebacks, so the result does not
    depend on the build machine. Returns the number of files that did not compile (some
    libraries ship files for other Python versions; those stay as source only).
    """
    failed = 0
    for source in sorted(site.rglob("*.py")):
        relative = source.relative_to(site).as_posix()
        try:
            py_compile.compile(
                str(source),
                cfile=importlib.util.cache_from_source(str(source)),
                dfile=f"{LAMBDA_TASK_ROOT}/{relative}",
                doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
            )
        except py_compile.PyCompileError:
            failed += 1
    return failed


def check_platform(site: Path, arch: str) -> list[str]:
    """Fail unless every compiled dependency is a Linux build for this CPU and Python 3.12."""
    machine = WHEEL_ARCH[arch]
    cpython = "cp{}{}".format(*PYTHON_VERSION)
    native: list[str] = []
    problems: list[str] = []
    for wheel_file in sorted(site.glob("*.dist-info/WHEEL")):
        name = wheel_file.parent.name.removesuffix(".dist-info")
        lines = wheel_file.read_text().splitlines()
        tags = [line.split(":", 1)[1].strip() for line in lines if line.startswith("Tag:")]
        platforms = {tag.split("-")[2] for tag in tags}
        if platforms == {"any"}:
            continue
        native.append(name)
        ok = any(
            "linux" in tag.split("-")[2]
            and machine in tag.split("-")[2]
            and (tag.split("-")[0] == cpython or tag.split("-")[1] == "abi3")
            for tag in tags
        )
        if not ok:
            problems.append(f"{name}: {', '.join(tags)}")
    foreign = [p for p in site.rglob("*") if p.suffix.lower() in FOREIGN_BINARIES]
    problems += [f"non-Linux binary: {p.relative_to(site).as_posix()}" for p in foreign]
    present = {name.split("-")[0].lower() for name in native}
    problems += [f"missing native dependency: {dep}" for dep in REQUIRED_NATIVE if dep not in present]
    if problems:
        raise SystemExit("Package is not a valid Linux build:\n  " + "\n  ".join(problems))
    return native


def write_zip(site: Path, target: Path) -> int:
    """Deterministic ZIP: sorted entries, fixed date, Unix modes (run.sh executable)."""
    files = sorted((p for p in site.rglob("*") if p.is_file()), key=lambda p: p.relative_to(site).as_posix())
    unzipped = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        for path in files:
            name = path.relative_to(site).as_posix()
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 3  # Unix, so Lambda honours the file modes below
            info.external_attr = (EXEC_MODE if name == "run.sh" else FILE_MODE) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            data = path.read_bytes()
            unzipped += len(data)
            archive.writestr(info, data, compresslevel=9)
    return unzipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--arch", choices=sorted(PLATFORMS), default="x86_64", help="Lambda architecture")
    args = parser.parse_args(argv)

    if sys.version_info[:2] != PYTHON_VERSION:
        raise SystemExit("Run with Python 3.12 (the Lambda runtime version): `uv run python ...`.")
    if os.environ.get("PYTHONHASHSEED") != "0":
        # A fixed hash seed makes the compiled .pyc files byte-identical between builds.
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        return subprocess.run([sys.executable, __file__, *sys.argv[1:]], env=env, check=False).returncode  # noqa: S603

    uv = find_uv()
    work = Path(tempfile.mkdtemp(prefix="radial-pulse-lambda-"))
    try:
        return build(uv, args.arch, work)
    finally:
        remove_tree(work)


def build(uv: str, arch: str, work: Path) -> int:
    site = work / "package"
    site.mkdir()

    say(f"1/5 Linux dependencies from uv.lock ({PLATFORMS[arch]}, Python 3.12)")
    install_dependencies(uv, arch, work, site)
    say("2/5 Application code + run.sh")
    add_application(site)
    say("3/5 Checking compiled dependencies")
    native = check_platform(site, arch)
    say(f"    Linux builds: {', '.join(native)}")
    say("4/5 Precompiling bytecode")
    failed = compile_bytecode(site)
    if failed:
        say(f"    {failed} library file(s) left as source (not valid Python 3.12; never imported)")
    say("5/5 Writing the ZIP")
    target = DIST_DIR / f"radial-pulse-api-{arch}.zip"
    unzipped = write_zip(site, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n")

    zipped = target.stat().st_size
    say(f"\n{target.relative_to(ROOT).as_posix()}")
    say(f"  sha256    {digest}")
    say(f"  zipped    {zipped / 1_048_576:.1f} MB")
    say(f"  unzipped  {unzipped / 1_048_576:.1f} MB (limit 250 MB with layers)")
    if unzipped + LAYER_ALLOWANCE > UNZIPPED_LIMIT:
        raise SystemExit("Too big: the package plus the adapter layer is over Lambda's 250 MB limit.")
    if zipped > DIRECT_UPLOAD_LIMIT:
        say("  Over 50 MB zipped: upload it to S3 first and create/update the function from there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
