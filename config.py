import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if not ENV_PATH.exists():
    ENV_PATH = BASE_DIR.parent / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

class Config:
    ENV_LOADED_PATH = str(ENV_PATH) if ENV_PATH.exists() else "Not Found"
    
    DB_HOST = os.getenv("DB_HOST") or os.getenv("MYSQL_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT") or os.getenv("MYSQL_PORT", "3306"))
    DB_USER = os.getenv("DB_USER") or os.getenv("MYSQL_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("MYSQL_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME") or os.getenv("MYSQL_DB", "manhwa_tracker")
    
    MANHWA_FOLDER = os.getenv("MANHWA_FOLDER", "")
    
    raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    try:
        TELEGRAM_API_ID = int(raw_api_id) if raw_api_id else None
    except ValueError:
        TELEGRAM_API_ID = None
        
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
    TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "").strip()
    
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback_secret_key")
    FLASK_ENV = os.getenv("FLASK_ENV", "production")
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t")

    @classmethod
    def telegram_configured(cls):
        return bool(cls.TELEGRAM_API_ID and cls.TELEGRAM_API_HASH)
        
    # Asura Configuration
    ASURA_ENABLED = os.environ.get('ASURA_ENABLED', 'true').lower() == 'true'
    ASURA_BASE_URL = os.environ.get('ASURA_BASE_URL', 'https://asurascans.com')
    ASURA_URL_TEMPLATE = os.environ.get('ASURA_URL_TEMPLATE', 'https://asurascans.com/comics/{slug}')

    # Source Discovery
    SEARCH_ENABLED = os.environ.get('SEARCH_ENABLED', 'true').lower() == 'true'
    SEARCH_PROVIDER = os.environ.get('SEARCH_PROVIDER', 'serpapi_google_light')
    SERPAPI_API_KEY = os.environ.get('SERPAPI_API_KEY', '')
    SERPAPI_ENGINE = os.environ.get('SERPAPI_ENGINE', 'google_light')

    # Provider Registry
    import json
    raw_providers = os.environ.get('LATEST_CHAPTER_PROVIDERS_JSON', '')
    if raw_providers:
        try:
            LATEST_CHAPTER_PROVIDERS = json.loads(raw_providers)
        except json.JSONDecodeError:
            LATEST_CHAPTER_PROVIDERS = []
    else:
        LATEST_CHAPTER_PROVIDERS = [
            {"name": "asura", "domain": "asurascans.com", "enabled": True, "type": "asura"},
            {"name": "generic", "domain": "*", "enabled": True, "type": "generic_metadata"}
        ]

print("Using database config:")
print(f"host={Config.DB_HOST}")
print(f"port={Config.DB_PORT}")
print(f"user={Config.DB_USER}")
print(f"database={Config.DB_NAME}")
print("password=set" if Config.DB_PASSWORD else "password=not set")
