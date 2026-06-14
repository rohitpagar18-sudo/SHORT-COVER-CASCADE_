"""FastAPI application entry point.

Single-port mode (production / `run_ui.bat`): also serves the built
React app from frontend/web/dist at "/". In dev (`npm run dev`), Vite
serves the SPA on 5173 and proxies /api to this server on 8000.

The ONLY file the API writes is config/config.yaml (via config router).
Never writes to logs/ or data/.
"""
from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .paths import WEB_DIST_DIR, PROJECT_ROOT
from .routers import overview as overview_router
from .routers import botstatus as botstatus_router
from .routers import health as health_router
from .routers import config as config_router
from .routers import positions as positions_router
from .routers import trades as trades_router
from .routers import paper as paper_router
from .routers import reports as reports_router
from .routers import conditions as conditions_router
from .routers import risk as risk_router


def create_app() -> FastAPI:
    app = FastAPI(title="Short Cover Cascade — Frontend API", version="0.1.0")

    # CORS: dev Vite on 5173, plus the same-origin production case.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router, prefix="/api")
    app.include_router(overview_router.router, prefix="/api")
    app.include_router(botstatus_router.router, prefix="/api")
    app.include_router(config_router.router, prefix="/api")
    app.include_router(positions_router.router, prefix="/api")
    app.include_router(trades_router.router, prefix="/api")
    app.include_router(paper_router.router, prefix="/api")
    app.include_router(reports_router.router, prefix="/api")
    app.include_router(conditions_router.router, prefix="/api")
    app.include_router(risk_router.router, prefix="/api")

    # Serve the built SPA (single-port mode). In dev (Vite), this dir
    # may be empty and that's fine — Vite is on 5173.
    if WEB_DIST_DIR.exists() and (WEB_DIST_DIR / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIST_DIR / "assets")), name="assets")

        @app.get("/")
        def _root_index():
            return FileResponse(str(WEB_DIST_DIR / "index.html"))

        @app.get("/{full_path:path}")
        def _spa_fallback(full_path: str):
            # API routes are handled before this matcher runs.
            if full_path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            target = WEB_DIST_DIR / full_path
            if target.is_file():
                return FileResponse(str(target))
            return FileResponse(str(WEB_DIST_DIR / "index.html"))
    else:
        @app.get("/")
        def _root_dev():
            return {
                "message": "API is running. Build the web app or run `npm run dev` for the UI.",
                "web_dist": str(WEB_DIST_DIR),
                "project_root": str(PROJECT_ROOT),
            }

    return app


app = create_app()


def main():  # pragma: no cover — entry point used by run_ui.bat
    import uvicorn
    port = int(os.environ.get("SCC_UI_PORT", "8000"))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
