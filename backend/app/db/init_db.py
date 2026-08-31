"""Database schema initialization helpers."""

from sqlalchemy import inspect, text

from app.db.database import Base, engine


def init_db() -> None:
    """Create tables and apply small, additive compatibility upgrades."""
    # Import models before create_all so their metadata is registered on Base.
    import app.models  # noqa: F401

    # Production databases must have pgvector available before embedding columns
    # can be created. Managed PostgreSQL roles need permission to create this
    # extension once; failing early keeps an unusable deployment from serving.
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.create_all(bind=engine)

    # ``create_all`` intentionally does not add columns to an existing table.
    # Stage 2 needs these nullable/defaulted metadata fields on installations
    # that created the Stage 1 repositories table already.
    columns = {column["name"] for column in inspect(engine).get_columns("repositories")}
    additions = {
        "owner": "VARCHAR(255)",
        "stars": "INTEGER NOT NULL DEFAULT 0",
        "forks": "INTEGER NOT NULL DEFAULT 0",
        "primary_language": "VARCHAR(255)",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(
                    text(f"ALTER TABLE repositories ADD COLUMN {name} {definition}")
                )
        # Do not make startup fail for a database which already contains old
        # duplicate rows. New imports are still guarded in the API; a future
        # data-cleanup migration can add this index in that exceptional case.
        duplicate_url = connection.execute(
            text(
                "SELECT github_url FROM repositories GROUP BY github_url "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).scalar_one_or_none()
        if duplicate_url is None:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_repositories_github_url_unique ON repositories (github_url)"
                )
            )

    # The Alembic migration is the durable schema record. This guarded upgrade
    # also keeps existing developer databases compatible on application start.
    chunk_columns = {column["name"] for column in inspect(engine).get_columns("code_chunks")}
    chunk_additions = {
        "embedding": "vector(1536)",
        "embedding_model": "VARCHAR(100)",
    }
    with engine.begin() as connection:
        for name, definition in chunk_additions.items():
            if name not in chunk_columns:
                connection.execute(text(f"ALTER TABLE code_chunks ADD COLUMN {name} {definition}"))
