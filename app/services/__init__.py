"""Business logic. Services:

* receive an authenticated ``Principal`` (or ``ClinicContext``) — never a raw request
* call repositories for data, never build SQL themselves
* write an audit event for every state-changing action, in the SAME transaction
* raise ``app.core.errors`` exceptions — never FastAPI's HTTPException
* commit exactly once at the end of a successful unit of work
"""
