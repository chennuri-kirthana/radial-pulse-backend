"""Adapters to external systems (AWS, Cognito, later: Google APIs).

Each adapter has a small Protocol so services depend on the interface, and tests
can substitute an in-memory implementation. No real third-party accounts are
connected during scaffolding.
"""
