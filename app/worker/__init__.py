"""Background worker: `python -m app.worker`. Same image as the API, separate process/service.

Runs as a SERVICE identity (its own ECS task role and DB login), never as a user.
See docs/architecture/background-jobs.md.
"""
