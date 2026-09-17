from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.baseline import router as baseline_router
from app.api.edges import router as edges_router
from app.api.line_models import router as line_models_router
from app.api.measurements import router as measurements_router
from app.api.monitors import router as monitors_router
from app.api.networks import router as networks_router
from app.api.topology import router as topology_router
from app.db.base import Base
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Fault Location Network Initialization API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(networks_router)
app.include_router(topology_router)
app.include_router(line_models_router)
app.include_router(edges_router)
app.include_router(monitors_router)
app.include_router(measurements_router)
app.include_router(baseline_router)
