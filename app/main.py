from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from fastapi.responses import JSONResponse

# ✅ Importiere den transaction_router
from app.api.endpoints import router as api_router
from app.core.backend_crypto_tracker.api.routes import transaction_routes
from app.core.config import Settings, get_settings
from app.core.database import init_db
from .routes.custom_analysis_routes import router as custom_analysis_router

app.include_router(custom_analysis_router)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI application."""
    settings = get_settings()
    init_db()
    logger.info(f"Starting {settings.PROJECT_NAME}")
    yield
    logger.info(f"Shutting down {settings.PROJECT_NAME}")

app = FastAPI(
    title="Social Media & Blockchain Analysis",
    description="Enterprise-grade social media and blockchain analysis system",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ✅ Registriere die Router
app.include_router(api_router, prefix="/api/v1", tags=["API"])
app.include_router(api_router, prefix="/api")  # Optional: Legacy-Route
app.include_router(transaction_routes.router, prefix="/api")  # ✅ Zugriff auf .router

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Application root endpoint."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "services": {
            "social_analysis": "active",
            "blockchain_tracking": "active"
        }
    }

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc) if app.debug else "An unexpected error occurred"
        }
    )
