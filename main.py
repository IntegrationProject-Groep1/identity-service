import logging
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from uuid import UUID
from database import get_db, init_db
from models import UserRegistry
import services
from rabbitmq_service import declare_exchange, get_rabbitmq_connection

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Identity Service",
    description="Central Master UUID management service",
    version="1.0.0",
)


# ============================================================
# Schemas
# ============================================================
class UserCreateRequest(BaseModel):
    email: EmailStr
    source_system: str


class UserResponse(BaseModel):
    master_uuid: str
    email: str
    created_by: str
    created_at: str

    class Config:
        from_attributes = True


# ============================================================
# Lifecycle Events
# ============================================================
@app.on_event("startup")
async def startup_event():
    """Initialize database and RabbitMQ on startup."""
    logger.info("Starting Identity Service...")

    # Initialize database tables
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    # Declare RabbitMQ exchange
    try:
        connection = get_rabbitmq_connection()
        declare_exchange(connection)
        connection.close()
        logger.info("RabbitMQ exchange declared successfully")
    except Exception as e:
        logger.error(f"Failed to declare RabbitMQ exchange: {e}")
        # Don't fail startup if RabbitMQ is unavailable initially
        # Services will retry


# ============================================================
# Endpoints
# ============================================================
@app.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreateRequest, db: Session = Depends(get_db)
) -> UserResponse:
    """
    Create a new user and assign a Master UUID.
    Idempotent: if email already exists, return existing UUID.

    **Request body:**
    - `email` (string): User's email address
    - `source_system` (string): Name of the system creating the user

    **Response:**
    - `master_uuid` (string): Unique UUID v7 identifier
    - `email` (string): User's email
    - `created_by` (string): Source system
    - `created_at` (string): ISO 8601 timestamp
    """
    try:
        user = services.create_user(request.email, request.source_system, db)
        return UserResponse(
            master_uuid=str(user.master_uuid),
            email=user.email,
            created_by=user.created_by,
            created_at=user.created_at.isoformat(),
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )


@app.get("/users/{master_uuid}", response_model=UserResponse)
async def get_user(
    master_uuid: str, db: Session = Depends(get_db)
) -> UserResponse:
    """
    Retrieve a user by Master UUID.

    **Path parameters:**
    - `master_uuid` (string): UUID to look up

    **Response:**
    - User details if found, 404 otherwise
    """
    try:
        uuid_obj = UUID(master_uuid)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid UUID format",
        )

    user = services.get_user_by_uuid(uuid_obj, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        master_uuid=str(user.master_uuid),
        email=user.email,
        created_by=user.created_by,
        created_at=user.created_at.isoformat(),
    )


@app.get("/users/by-email/{email}", response_model=UserResponse)
async def get_user_by_email(
    email: str, db: Session = Depends(get_db)
) -> UserResponse:
    """
    Retrieve a user by email address.

    **Path parameters:**
    - `email` (string): Email to look up

    **Response:**
    - User details if found, 404 otherwise
    """
    user = services.get_user_by_email(email, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        master_uuid=str(user.master_uuid),
        email=user.email,
        created_by=user.created_by,
        created_at=user.created_at.isoformat(),
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
