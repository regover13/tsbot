#!/usr/bin/env python3
"""
FastAPI Web-Interface für den TS-Bot.

Starten:
    uvicorn api.main:app --host 0.0.0.0 --port 8080

Oder via systemd (tsbot-api.service).
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
import secrets

from bot.session_manager import SessionManager
from api.routes import session, status as status_route, files, agenda

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Auth ──────────────────────────────────────────────────────
_API_USER   = os.environ.get("API_USER", "admin")
_API_SECRET = os.environ.get("API_SECRET", "changeme")
_security   = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(_security)):
    """HTTP Basic Auth Dependency."""
    user_ok = secrets.compare_digest(
        credentials.username.encode(), _API_USER.encode()
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode(), _API_SECRET.encode()
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Anmeldedaten",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── App Lifecycle ─────────────────────────────────────────────
manager = SessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.manager = manager
    logger.info("TSBot API gestartet.")
    yield
    logger.info("TSBot API wird beendet.")


# ── FastAPI App ───────────────────────────────────────────────
app = FastAPI(
    title="TSBot API",
    description="Steuerung des TeamSpeak Aufnahme-Bots",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router einbinden
app.include_router(
    session.router,
    prefix="/session",
    dependencies=[Depends(require_auth)],
)
app.include_router(
    status_route.router,
    dependencies=[Depends(require_auth)],
)
app.include_router(
    files.router,
    prefix="/protocols",
    dependencies=[Depends(require_auth)],
)
app.include_router(
    agenda.router,
    dependencies=[Depends(require_auth)],
)

# Statische Dateien
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    """Liefert das Web-Dashboard."""
    index = os.path.join(_static_dir, "index.html")
    with open(index, "r", encoding="utf-8") as f:
        return f.read()
