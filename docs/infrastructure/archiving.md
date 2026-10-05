# Archiving old data to S3

Owner: Person 1 (code, done) + Person 3 (AWS setup, below) · Sep 2026

## 1. Why

Two tables grow forever:

| Table | What | Grows by |
|---|---|---|
| `metric_snapshots` | followers, reviews, views… over time | every data pull, every clinic |
| `audit_events` | the log of every action | every click that changes something |

After a year or two, big tables make the database slower and more expensive. So once a
month, old rows are **copied to S3 and then removed from the database**. Nothing is lost:
the archive in S3 can still be searched (with Athena) and restored.

| Table | Kept in the database | Older rows go to |
|---|---|---|
| `metric_snapshots` | last **180 days** | S3 archive |
| `audit_events` | last **365 days** | S3 archive |

(Change with `ARCHIVE_METRICS_AFTER_DAYS` / `ARCHIVE_AUDIT_AFTER_DAYS`.)

## 2. What is already built (Person 1)

```
python -m app.cli archive-old-data            # do it
python -m app.cli archive-old-data --dry-run  # only count what would move
make archive-old-data              # same, through Nx
```

How one run works, per table, in batches of 5,000 rows:

```
select old rows ──► write gzip file to S3 ──► delete exactly those rows ──► commit
                         │
                         └── S3 fails? ──► rollback: NOTHING is deleted
```

- **Files:** `s3://<bucket>/<env>/<table>/year=2026/month=03/<run-id>-0000.jsonl.gz`
  (one JSON object per line, gzip; one folder per month of the row's own date).
- **Audit log safety:** `audit_events` is append-only. Migration 0009 allows deletes **only**
  when the transaction sets `app.archiving = on`, and the app's own database login has no
  DELETE permission on it at all. So only this archive task (owner login) can remove audit
  rows, and only right after copying them.
- **Locally** (no `ARCHIVE_BUCKET`), files go to the `.archive/` folder instead.
- Tests: `tests/api/test_weak_spots.py` (moves only old rows, dry run, S3 failure deletes
  nothing) and `tests/integration/test_rls.py` (app login cannot delete audit rows).

## 3. What Person 3 needs to set up in AWS

### Step 1: An archive bucket per environment

Separate from the assets bucket (different access and lifecycle). Suggested name:
`radial-pulse-<env>-archive`.

```hcl
resource "aws_s3_bucket" "archive" {
  bucket = "${var.name_prefix}-archive"
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn   # the same key as the assets bucket
    }
    bucket_key_enabled = true
  }
}

# Cheaper storage as files get older. Retention = a business decision (see step 6).
resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    id     = "age-out"
    status = "Enabled"
    filter {}
    transition {
      days          = 90
      storage_class = "GLACIER_IR"   # Glacier Instant Retrieval: cheap, still readable by Athena
    }
    expiration { days = 2555 }       # 7 years
  }
}
```

Also add the same **TLS-only bucket policy** the assets bucket uses (`aws:SecureTransport`).

### Step 2: A task role that can only WRITE to the archive

```hcl
resource "aws_iam_role" "archive" {
  name               = "${var.name_prefix}-archive-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "archive" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${var.archive_bucket_arn}/${var.environment["APP_ENV"]}/*"]
  }
  statement {
    actions   = ["kms:GenerateDataKey", "kms:Encrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "archive" {
  role   = aws_iam_role.archive.id
  policy = data.aws_iam_policy_document.archive.json
}
```

No read and no delete on S3: the task can add archive files, never change or remove them.

### Step 3: An ECS task definition (copy of `migrate`)

Same image, same database **owner** secret as the `migrate` task (in `modules/compute/main.tf`),
a different command and the new task role:

```hcl
resource "aws_ecs_task_definition" "archive" {
  family                   = "${var.name_prefix}-archive"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.archive.arn

  container_definitions = jsonencode([{
    name      = "archive"
    image     = local.image
    essential = true
    command   = ["python", "-m", "app.cli", "archive-old-data"]
    environment = [for k, v in merge(local.db_env, {
      APP_ENV        = var.environment["APP_ENV"]
      ARCHIVE_BUCKET = var.archive_bucket_name
      S3_KMS_KEY_ID  = var.kms_key_arn
      AWS_REGION     = var.aws_region
    }) : { name = k, value = v }]
    secrets = [
      { name = "DB_USER", valueFrom = "${var.db_secret_arn}:username::" },
      { name = "DB_PASSWORD", valueFrom = "${var.db_secret_arn}:password::" },
    ]
    logConfiguration = local.log_config
  }])
}
```

The execution role must be allowed to read the master secret for this task too (it already is
for `migrate`).

### Step 4: Run it once a month

EventBridge Scheduler, 1st of every month at 03:00 IST, in the app subnets with the tasks
security group:

```hcl
resource "aws_scheduler_schedule" "archive" {
  name                         = "${var.name_prefix}-archive-monthly"
  schedule_expression          = "cron(0 3 1 * ? *)"
  schedule_expression_timezone = "Asia/Kolkata"
  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn   # allowed: ecs:RunTask + iam:PassRole (execution + archive roles)
    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.archive.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = var.app_subnet_ids
        security_groups  = [aws_security_group.tasks.id]
        assign_public_ip = false
      }
    }
    retry_policy { maximum_retry_attempts = 2 }
  }
}
```

### Step 5: An alarm if a run fails

An EventBridge rule on "ECS Task State Change" with `lastStatus = STOPPED`, group
`family:<prefix>-archive` and a non-zero `exitCode`, sent to the existing alarms SNS topic.

### Step 6: Decide retention (team + mentor)

Suggested: keep archive files for **7 years**, then S3 deletes them automatically. For the audit
log you can also turn on **S3 Object Lock** (compliance mode) so nobody, not even an admin, can
delete archive files early. This is a legal/business decision, so confirm before PROD.

### Step 7: First run

1. `--dry-run` in DEV, and check the counts in CloudWatch Logs.
2. A real run in DEV, then check the files appear in S3.
3. Enable the PROD schedule.

## 4. Reading the archive (Athena)

```sql
CREATE EXTERNAL TABLE archive_audit_events (
  id string, occurred_at string, actor_user_id string, actor_type string,
  action string, resource_type string, resource_id string, clinic_id string,
  request_id string, details string
)
PARTITIONED BY (year string, month string)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://radial-pulse-prod-archive/prod/audit_events/';

MSCK REPAIR TABLE archive_audit_events;   -- picks up new year=/month= folders

SELECT DISTINCT id, occurred_at, action, clinic_id   -- DISTINCT: a rare re-run can copy a row twice
FROM archive_audit_events
WHERE year = '2026' AND clinic_id = '…';
```

## 5. Restoring rows (rare)

Download the month's files, unzip, and insert the rows back with a small script as the owner
login (for `audit_events`, inside a transaction). Do it on DEV first.
