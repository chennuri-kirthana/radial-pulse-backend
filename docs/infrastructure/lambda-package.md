# AWS Lambda ZIP package

How to build the API as a ZIP for AWS Lambda (Python 3.12 runtime + AWS Lambda Web Adapter).
This only builds the file. Creating the function, API Gateway and the database is separate.

The app is not changed for Lambda. The Lambda Web Adapter starts the same uvicorn server as
the Dockerfile and passes each API Gateway request to it as plain HTTP.

## Build

You need [uv](https://docs.astral.sh/uv/) (0.8 or newer). Docker is not needed. The same
command works on Windows, macOS and Linux.

```bash
uv run python scripts/lambda/build_zip.py              # x86_64 Lambda
uv run python scripts/lambda/build_zip.py --arch arm64 # arm64 (Graviton) Lambda
make lambda-zip                                        # same as the first line

# Central DEV release: same build, fixed name, then check the file
uv run python scripts/lambda/build_zip.py --output dist/deployment/radial-pulse-api-dev-x86_64.zip
uv run python scripts/lambda/verify_zip.py dist/deployment/radial-pulse-api-dev-x86_64.zip
```

`verify_zip.py` reads the finished ZIP and fails if `run.sh` is missing or wrong (mode, line
endings, start command), if tests / docs / migrations or a `.env` file, private key or AWS key id
got in, if a compiled library is not a Linux build for the CPU and Python 3.12, if the size is over
the limit, or if the SHA-256 does not match the `.sha256` file.

What the script does:

1. Exports the runtime dependencies from `uv.lock`. These are exact versions with hashes, and
   no dev tools.
2. Installs them as **Linux wheels** for Python 3.12 on glibc 2.34 (Amazon Linux 2023, the
   Lambda python3.12 OS). It never uses the packages of the machine that runs the build.
3. Adds `app/` and `run.sh`. It leaves out tests, docs, `alembic/`, `.git`, `.venv`, caches and
   `.env` files.
4. Fails if any compiled dependency is not a Linux build for the chosen CPU. It also fails if
   `psycopg_binary`, `cryptography` or `pydantic_core` is missing.
5. Precompiles bytecode. Lambda's disk is read-only, so Python cannot cache it there.
6. Writes the ZIP with a fixed file order, dates and modes. The same inputs give the same
   SHA-256.

The script stages files in the system temp folder, not in the checkout, and deletes them when
it finishes.

Output:

```
dist/lambda/radial-pulse-api-x86_64.zip          upload this
dist/lambda/radial-pulse-api-x86_64.zip.sha256
```

ZIP contents (`/var/task` on Lambda):

```
run.sh                  the function handler (start script, mode 755)
app/                    the API
fastapi/ starlette/ uvicorn/ sqlalchemy/ psycopg/ psycopg_binary/ pydantic/ pydantic_core/
cryptography/ boto3/ botocore/ jwt/ httpx/ …   runtime dependencies (+ *.dist-info)
**/__pycache__/*.pyc    precompiled bytecode
```

Size on 2026-10-10 (x86_64, v15 code): 51,558,646 bytes zipped (49.2 MiB), 124.6 MiB unzipped.
That is only about 0.8 MiB under the direct-upload limit, so **upload through S3** (it always works,
and a new dependency can push the file over the limit).

- AWS allows 50 MB for a direct upload. Above that, upload the ZIP to S3 and point the function
  at it.
- AWS allows 250 MB unzipped, including layers. The script stops if the package plus about
  10 MB for the adapter layer goes over that.

## Lambda settings that must match the package

| Setting | Value |
|---|---|
| Runtime | `python3.12` |
| Architecture | the `--arch` you built (`x86_64` by default) |
| Handler | `run.sh` |
| Layer | AWS Lambda Web Adapter, **same architecture**. Take the ARN for `ap-south-1` from the adapter's releases page and confirm it is allowed. |
| `AWS_LAMBDA_EXEC_WRAPPER` | `/opt/bootstrap` |
| `AWS_LWA_PORT` | `8000` (`run.sh` listens on this port) |
| `AWS_LWA_READINESS_CHECK_PATH` | `/health` (does not need the database) |

The app settings (`APP_ENV`, `COGNITO_*`, `DB_*`, …) are Lambda environment variables. None
are in the package. In `dev`, the API does not start without `COGNITO_REGION`,
`COGNITO_USER_POOL_ID` and `COGNITO_APP_CLIENT_IDS`. On Lambda set `DB_POOL_SIZE=1` and
`DB_MAX_OVERFLOW=0`: each instance serves one request at a time.

## Check a build locally (optional, needs Docker)

This runs the package in AWS's own Python 3.12 Lambda image (same OS as Lambda), read-only
and as a non-root user:

```bash
mkdir -p /tmp/rp-task && unzip -q -o dist/lambda/radial-pulse-api-x86_64.zip -d /tmp/rp-task
docker run --rm --read-only --tmpfs /tmp --user 993:990 -v /tmp/rp-task:/var/task:ro \
  -e APP_ENV=local --entrypoint /bin/sh public.ecr.aws/lambda/python:3.12 -c \
  '/var/task/run.sh & sleep 5; python -c "import urllib.request as u; print(u.urlopen(\"http://127.0.0.1:8000/health\").read())"'
```

Expected: `b'{"status":"ok",…}'`. Without database settings, `/ready` and every `/api/v1` route
answer 500. Those routes need PostgreSQL.

## Notes

- `run.sh` uses the same uvicorn flags as the Dockerfile. It listens on `127.0.0.1`, because only
  the adapter talks to it.
- Packaged libraries come before the copies built into the Lambda runtime, so boto3 is the
  locked version.
- The Dockerfile and CI are not changed. The container image path still works as before.
