"""HTTP layer only: parse input, call ONE service function, shape the response.

No SQL here. No business rules here. Every clinic-scoped route depends on
``clinic_access(<permission>)`` from ``app.dependencies.tenancy``.
"""
