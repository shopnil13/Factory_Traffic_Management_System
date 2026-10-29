from contextlib import asynccontextmanager
import logging
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import AppAPIException
from app.api.routes_events import router as events_router
from app.api.routes_junctions import default_repo, router as junctions_router
from app.api.routes_simulator import router as simulator_router
from app.api.routes_stream import router as stream_router
from app.application.registry import registry
from app.application.runtime import JunctionRuntime
from app.domain.config import JunctionConfig, TimingConfig
from app.domain.inputs import ControllerAck
from app.domain.model import Direction
from app.infrastructure.controller.simulator import simulator_controller
from app.infrastructure.db.session import default_engine, default_session_maker, init_db
from app.infrastructure.sse import sse_broadcaster
from app.settings import TrafficProfile, settings

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

engine = default_engine
session_maker = default_session_maker


async def dispatch_simulated_ack(ack: ControllerAck) -> None:
    rt = registry.get(ack.junction_id)
    if rt:
        await rt.submit(ack)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db(engine)

    # Wire simulator controller ACK dispatcher
    simulator_controller.set_dispatcher(dispatch_simulated_ack)

    # Seed default Junction A if none exists
    existing = await default_repo.list_junctions()
    timing = (
        TimingConfig.demo_profile()
        if settings.PROFILE == TrafficProfile.DEMO
        else TimingConfig()
    )

    if not existing:
        logger.info("Seeding default Junction A (%s profile)...", settings.PROFILE.value)
        junction_a_config = JunctionConfig(
            junction_id="junction-a",
            name="Main Factory Crossroads (Junction A)",
            timing=timing,
            phases={
                "NORTH_SOUTH": [Direction.NORTH, Direction.SOUTH],
                "EAST_WEST": [Direction.EAST, Direction.WEST],
            },
        )
        await default_repo.save_junction(junction_a_config)

    # Start runtimes for all configured junctions
    all_junctions = await default_repo.list_junctions()
    for j in all_junctions:
        j_id = j["id"]
        conf = await default_repo.get_junction_config(j_id)
        if conf:
            rt = JunctionRuntime(
                config=conf,
                repository=default_repo,
                controller_port=simulator_controller,
                event_publisher=sse_broadcaster,
            )
            await rt.start()
            registry.register(rt)
            logger.info("Junction %s runtime active", j_id)

    yield

    logger.info("Shutting down junction runtimes...")
    for rt in registry.list_all():
        await rt.stop()
    await engine.dispose()


app = FastAPI(
    title="Factory Traffic Management System",
    description="Safety-critical multi-modal industrial intersection traffic controller",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Standardized error responses
@app.exception_handler(AppAPIException)
async def app_api_exception_handler(request: Request, exc: AppAPIException):
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request schema or malformed parameters",
                "details": exc.errors(),
            }
        },
    )


# Include Routers
app.include_router(junctions_router)
app.include_router(events_router)
app.include_router(simulator_router)
app.include_router(stream_router)

# Serve Frontend static build if present
dist_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if dist_path.exists() and dist_path.is_dir():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static_frontend")
