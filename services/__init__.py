"""Business-logic services for JobTracker.

Everything in this package is intentionally free of Flask and SQLAlchemy
imports so it can be unit-tested with plain dicts. The only inputs are job
dictionaries (or model instances duck-typed to the same fields) and the
candidate profile.
"""
