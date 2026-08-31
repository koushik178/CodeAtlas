import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import (
    get_boolean_environment,
    get_positive_integer_environment,
    load_environment,
)

load_environment()


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


class Base(DeclarativeBase):
    """Base class shared by all SQLAlchemy ORM models."""


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=get_boolean_environment("DATABASE_POOL_PRE_PING", True),
    pool_size=get_positive_integer_environment("DATABASE_POOL_SIZE", 5, minimum=1),
    max_overflow=get_positive_integer_environment("DATABASE_MAX_OVERFLOW", 10),
    pool_recycle=get_positive_integer_environment("DATABASE_POOL_RECYCLE_SECONDS", 1_800),
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Generator[Session, None, None]:
    """Yield one database session per request and close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
