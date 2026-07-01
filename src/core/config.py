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

    data_source: str = os.getenv("DATA_SOURCE", "mock").lower()

    azure_tenant_id: str = os.getenv("AZURE_TENANT_ID", "")
    graph_client_id: str = os.getenv("GRAPH_CLIENT_ID", "")
    graph_client_secret: str = os.getenv("GRAPH_CLIENT_SECRET", "")

    sharepoint_site_id: str = os.getenv("SHAREPOINT_SITE_ID", "")
    sharepoint_list_id: str = os.getenv("SHAREPOINT_LIST_ID", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()