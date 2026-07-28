from __future__ import annotations

import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from server.config import load_kaggle_config, load_server_config
from server.db.database import Database
from server.db.migrations import ensure_default_sessions, migrate
from server.routes import dashboard, experiments, queue, sessions
from server.schemas import ApiResponse
from server.services.experiment_scanner import ExperimentScanner
from server.services.kaggle_runner import KaggleRunner
from server.services.local_runner import LocalRunner
from server.services.log_writer import EventWriter
from server.services.session_manager import SessionManager, WorkflowError


def create_app() -> FastAPI:
    server_config = load_server_config()
    kaggle_config = load_kaggle_config()
    db = Database(server_config.database_path)
    migrate(db)
    ensure_default_sessions(db)
    events = EventWriter(server_config.events_path)
    session_manager = SessionManager(db, events, kaggle_config)

    app = FastAPI(title="AutoMM Workflow Server", version="0.1.0")
    app.state.config = server_config
    app.state.db = db
    app.state.events = events
    app.state.sessions = session_manager
    app.state.scanner = ExperimentScanner(db, events, server_config.work_folder)
    app.state.local_runner = LocalRunner(db, session_manager)
    app.state.kaggle_runner = KaggleRunner(db, session_manager, kaggle_config)

    app.include_router(dashboard.router)
    app.include_router(experiments.router)
    app.include_router(queue.router)
    app.include_router(sessions.router)

    @app.get("/health", response_model=ApiResponse)
    def health() -> ApiResponse:
        return ApiResponse(
            ok=True,
            data={"server": "automm-workflow-server", "status": "online", "version": "0.1.0"},
        )

    @app.on_event("startup")
    def start_scanner_loop() -> None:
        stop_event = threading.Event()
        app.state.scanner_stop_event = stop_event

        def loop() -> None:
            while not stop_event.is_set():
                try:
                    app.state.scanner.scan()
                except Exception as exc:
                    app.state.events.write("SCANNER_ERROR", message=str(exc))
                stop_event.wait(server_config.scan_interval_seconds)

        thread = threading.Thread(target=loop, name="automm-scanner", daemon=True)
        thread.start()
        app.state.scanner_thread = thread

    @app.on_event("shutdown")
    def stop_scanner_loop() -> None:
        stop_event = getattr(app.state, "scanner_stop_event", None)
        if stop_event is not None:
            stop_event.set()

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(request: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ApiResponse(ok=False, error_code=exc.error_code, message=exc.message, data=exc.data).model_dump(),
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    config = load_server_config()
    uvicorn.run("server.app:app", host=config.host, port=config.port, reload=False)


if __name__ == "__main__":
    main()
