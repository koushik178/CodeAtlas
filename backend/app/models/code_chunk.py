"""Line-addressable source chunks for future retrieval workflows."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.vector import Vector

EMBEDDING_DIMENSIONS = 1536


class CodeChunk(Base):
    """A bounded, overlapping segment of a stored repository source file."""

    __tablename__ = "code_chunks"
    __table_args__ = (
        UniqueConstraint("repository_file_id", "chunk_index", name="uq_code_chunks_file_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_file_id: Mapped[int] = mapped_column(
        ForeignKey("repository_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    repository: Mapped["Repository"] = relationship(back_populates="chunks")
    repository_file: Mapped["RepositoryFile"] = relationship(back_populates="chunks")
