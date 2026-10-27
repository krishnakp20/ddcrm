import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, SessionLocal, ensure_columns, engine
from .routers import agent, auth, campaign_data, campaigns, clients, dashboard, departments, dialer_ids, forms, plans, profile, public, roles, users, tickets, reports, dialer, dialer_lists, intake, alerts as alerts_router, webhooks, settings as settings_router
from .seed import ensure_admin
from .services import alerts as alert_service


def _scan() -> None:
    with SessionLocal() as db:
        alert_service.scan_sla(db)


async def _sla_loop() -> None:
    """Once a minute: alert about tickets that are about to miss, or missed, their SLA."""
    await asyncio.sleep(20)
    while True:
        try:
            await asyncio.to_thread(_scan)
        except Exception:  # noqa: BLE001
            logging.getLogger("alerts").exception("SLA check failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Creates any missing tables. Switch to Alembic migrations once the schema settles.
    Base.metadata.create_all(bind=engine)
    ensure_columns()
    ensure_admin()
    task = asyncio.create_task(_sla_loop())
    yield
    task.cancel()


app = FastAPI(title="DialDesk CRM API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, public, clients, plans, users, roles, departments, forms, campaigns, campaign_data, dialer_ids, tickets, reports, dialer, dialer_lists, intake, alerts_router, webhooks, agent, profile, dashboard, settings_router):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}

