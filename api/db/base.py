"""SQLAlchemy 2.x async declarative base.

`Base.metadata` is the import target for Alembic's `env.py`.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
