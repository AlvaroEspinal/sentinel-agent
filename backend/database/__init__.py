"""
Parcl Intelligence Database Module

PostgreSQL (asyncpg) with automatic SQLite fallback for demo/development.
"""

try:
    from database.postgres import DatabasePool, db, get_db
except ImportError:
    from .postgres import DatabasePool, db, get_db

__all__ = ["DatabasePool", "db", "get_db"]
