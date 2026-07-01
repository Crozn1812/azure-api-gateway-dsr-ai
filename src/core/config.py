import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()

class Settings:
    environment: str = os.getenv("ENVIRONMENT", "local")
    partner_api_key: str = os.getenv("PARTNER_API_KEY", "demo-partner-key")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.5")

    require_apim_secret: bool = os.getenv("REQUIRE_APIM_SECRET", "false").lower() == "true"
    backend_internal_secret: str = os.getenv("BACKEND_INTERNAL_SECRET", "")

@lru_cache
def get_settings() -> Settings:
    return Settings()