from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_boolean_environment, get_csv_environment, load_environment

load_environment()

from app.db.database import engine
from app.db.init_db import init_db
from app.routers.repositories import router as repositories_router
from app.routers.search import router as search_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="CodeAtlas API",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = get_csv_environment("CORS_ALLOW_ORIGINS", "http://localhost:3000")
cors_allow_credentials = get_boolean_environment("CORS_ALLOW_CREDENTIALS", True)
if "*" in cors_origins and cors_allow_credentials:
    raise RuntimeError("CORS_ALLOW_ORIGINS cannot include '*' when CORS_ALLOW_CREDENTIALS is enabled.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repositories_router)
app.include_router(search_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, error: RequestValidationError) -> JSONResponse:
    """Return consistent, safe validation feedback without internal exception data."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid request.",
            "errors": [
                {"location": list(item["loc"]), "message": item["msg"]}
                for item in error.errors()
            ],
        },
    )


@app.get("/")
def root():
    return {
        "message": "CodeAtlas backend is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "CodeAtlas API"
    }


@app.get("/db-health")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "healthy",
            "database": "PostgreSQL"
        }

    except Exception:
        return {
            "status": "unhealthy",
            "database": "unavailable",
        }


@app.get("/readyz")
def readiness_check():
    """Report ready only after the database accepts a minimal query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unready", "database": "unavailable"},
        )
    return {"status": "ready", "database": "PostgreSQL"}
