"""
Vercel Serverless Entry Point — Parcl Intelligence API

Vercel Python runtime detects FastAPI/ASGI apps automatically.
This file imports the FastAPI `app` from the backend package and
re-exports it for Vercel's serverless function handler.

The ASGI app handles all /api/* routes as a single serverless function.
"""
import sys
from pathlib import Path

# Add the backend directory to the Python path so imports work
backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app  # noqa: E402 — must come after sys.path fix
