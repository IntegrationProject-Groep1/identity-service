import logging
import threading
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import engine, init_db
from rabbitmq_service import declare_infrastructure, get_rabbitmq_connection, start_rpc_server

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Identity Service",
    description="Central Master UUID management service (RabbitMQ XML communication)",
    version="1.0.0",
)


rpc_stop_event = threading.Event()
rpc_thread: threading.Thread | None = None
_startup_complete = False


# ============================================================
# Lifecycle Events
# ============================================================
@app.on_event("startup")
async def startup_event():
    """Initialize database and RabbitMQ on startup."""
    global _startup_complete
    logger.info("Starting Identity Service...")

    # Initialize database tables
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Declare RabbitMQ infrastructure
    try:
        connection = get_rabbitmq_connection()
        declare_infrastructure(connection)
        connection.close()
        logger.info("RabbitMQ infrastructure declared successfully")
    except Exception as e:
        logger.error(f"Failed to declare RabbitMQ infrastructure: {e}")

    # Start RabbitMQ XML RPC server thread
    global rpc_thread
    rpc_thread = threading.Thread(target=start_rpc_server, args=(rpc_stop_event,), daemon=True)
    rpc_thread.start()
    logger.info("RabbitMQ XML RPC server thread started")

    _startup_complete = True


@app.on_event("shutdown")
async def shutdown_event():
    """Stop RabbitMQ XML RPC server."""
    rpc_stop_event.set()
    if rpc_thread and rpc_thread.is_alive():
        rpc_thread.join(timeout=5)


@app.get("/live")
async def liveness_check():
    """Liveness probe: process is alive. Never returns 503 unless uvicorn itself is dead."""
    return JSONResponse(status_code=200, content={"status": "alive"})


@app.get("/health")
async def health_check():
    """Readiness probe: service is fully operational."""
    if not _startup_complete:
        return JSONResponse(status_code=503, content={"status": "starting"})

    issues = []

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        issues.append(f"db: {e}")

    if rpc_thread is None or not rpc_thread.is_alive():
        issues.append("rabbitmq: rpc thread not running")

    if issues:
        return JSONResponse(status_code=503, content={"status": "degraded", "issues": issues})

    return JSONResponse(status_code=200, content={"status": "ok"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
