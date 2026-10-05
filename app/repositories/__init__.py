"""Database access. The ONLY layer that builds SQL queries.

Rule: every method that reads a clinic-scoped row takes ``clinic_id`` and filters
on it, so an id from another clinic simply returns nothing (-> 404). Never add a
``get(id)`` for clinic-scoped data without the ``clinic_id`` filter.
"""
