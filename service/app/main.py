from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import Base, engine
from app.routers import datasets

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fine for a single-service project. Swap for Alembic once the schema starts changing.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Time-Series Insights API",
    description="Upload a CSV, get validated storage plus summary statistics and outlier detection.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(datasets.router)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz", tags=["meta"])
def healthz():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    page = STATIC_DIR / "index.html"
    if page.is_file():
        return FileResponse(page)
    return {"docs": "/docs", "health": "/healthz"}
