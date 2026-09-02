"""web — entrypoint for the FastAPI server."""
from .server import app, run

__all__ = ["app", "run"]
