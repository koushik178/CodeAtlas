"""Repository ORM model."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Repository(Base):
    """A GitHub repository tracked by CodeAtlas."""

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    github_url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    primary_language: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    files: Mapped[list["RepositoryFile"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
    )
