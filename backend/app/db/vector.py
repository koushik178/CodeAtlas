"""Shared pgvector SQLAlchemy type for future embedding columns.

This module intentionally does not create the PostgreSQL `vector` extension.
That extension must be enabled separately by a database administrator.
"""

from pgvector.sqlalchemy import Vector

__all__ = ["Vector"]
