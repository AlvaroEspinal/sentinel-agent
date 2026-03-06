"""Sentinel Agent Configuration"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=True)  # project root .env
load_dotenv(override=True)  # local .env can override if present

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data_cache"
DATA_DIR.mkdir(exist_ok=True)

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
CESIUM_ION_ACCESS_TOKEN = os.getenv("CESIUM_ION_ACCESS_TOKEN", "")
PLANET_API_KEY = os.getenv("PLANET_API_KEY", "")
CAPELLA_API_KEY = os.getenv("CAPELLA_API_KEY", "")
WINDY_API_KEY = os.getenv("WINDY_API_KEY", "")
PLATE_RECOGNIZER_API_KEY = os.getenv("PLATE_RECOGNIZER_API_KEY", "")
OPEN_ALPR_API_KEY = os.getenv("OPEN_ALPR_API_KEY", "")

# Real Estate Data APIs
ATTOM_API_KEY = os.getenv("ATTOM_API_KEY", "")
FIRST_STREET_API_KEY = os.getenv("FIRST_STREET_API_KEY", "")
WALK_SCORE_API_KEY = os.getenv("WALK_SCORE_API_KEY", "")
GREATSCHOOLS_API_KEY = os.getenv("GREATSCHOOLS_API_KEY", "")
SHOVELS_API_KEY = os.getenv("SHOVELS_API_KEY", "")
REGRID_API_KEY = os.getenv("REGRID_API_KEY", "")
AIRDNA_API_KEY = os.getenv("AIRDNA_API_KEY", "")

# Sentinel Hub (Copernicus Data Space)
SENTINEL_HUB_CLIENT_ID = os.getenv("SENTINEL_HUB_CLIENT_ID", "")
SENTINEL_HUB_CLIENT_SECRET = os.getenv("SENTINEL_HUB_CLIENT_SECRET", "")

# OpenSky
OPENSKY_USERNAME = os.getenv("OPENSKY_USERNAME", "")
OPENSKY_PASSWORD = os.getenv("OPENSKY_PASSWORD", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentinel.db")

# PostgreSQL (Supabase / production)
POSTGRES_URL = os.getenv("POSTGRES_URL", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Vector Store
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_data"))

# Compliance
COMPLIANCE_LEDGER_SECRET = os.getenv("COMPLIANCE_LEDGER_SECRET", "dev-secret-change-in-production")

# Server
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Agent Configuration
CONSENSUS_THRESHOLD = 0.05  # 5% variance threshold for CV consensus
ALERT_MATERIALITY_R2 = 0.3  # Minimum R-squared for alert to fire
CONFIDENCE_HIGH = 0.95
CONFIDENCE_MEDIUM = 0.75
CONFIDENCE_LOW = 0.50

# Property Agent Configuration
PERMIT_SEARCH_RADIUS_KM = 1.0  # Default radius for nearby permit search
PROPERTY_AGENT_DEFAULT_INTERVAL = 300  # 5 minutes
NEIGHBORHOOD_AGENT_DEFAULT_INTERVAL = 3600  # 1 hour
PORTFOLIO_AGENT_DEFAULT_INTERVAL = 1800  # 30 minutes
MAX_AGENTS_PER_USER = 50

# Sensor Priority (fallback order)
SENSOR_PRIORITY = ["optical", "sar", "ais", "adsb", "cctv", "osm"]

# Asset Tracking
MAX_GEOFENCE_RADIUS_KM = 50
DEFAULT_REFRESH_INTERVAL_SEC = 300  # 5 minutes
ALERT_COOLDOWN_SEC = 3600  # 1 hour between same-type alerts

# Geocoding
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "parcl-intelligence/1.0")
GOOGLE_GEOCODING_API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY", "")

# Firecrawl (web scraping)
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

# OpenRouter (multi-model LLM gateway)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_DEFAULT_MODEL = os.getenv("OPENROUTER_DEFAULT_MODEL", "google/gemini-2.0-flash-001")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # "anthropic" | "openrouter"

# Feature flags
ENABLE_GEOSPATIAL_FEEDS = os.getenv("ENABLE_GEOSPATIAL_FEEDS", "false").lower() == "true"

# Target towns (affluent MA municipalities)
TARGET_TOWN_IDS = [
    "newton", "wellesley", "weston", "brookline", "needham",
    "dover", "sherborn", "natick", "wayland", "lincoln",
    "concord", "lexington",
]
