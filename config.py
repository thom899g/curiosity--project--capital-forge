"""
Configuration and environment management for Sentinel.
Implements rigorous validation with fallbacks for all critical variables.
"""
import os
import logging
from typing import Optional
from pydantic import BaseSettings, validator
from dotenv import load_dotenv

# Load .env file if exists
load_dotenv()

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Validated configuration with environment fallbacks"""
    
    # Discord Configuration
    DISCORD_TOKEN: str
    DISCORD_CLIENT_ID: str
    DISCORD_GUILD_IDS: Optional[str] = None  # Comma-separated for dev
    
    # Firebase Configuration
    FIREBASE_CREDENTIALS_PATH: str = "./firebase-credentials.json"
    FIREBASE_PROJECT_ID: str
    
    # Moralis Configuration
    MORALIS_API_KEY: str
    MORALIS_API_URL: str = "https://deep-index.moralis.io/api/v2"
    MORALIS_RATE_LIMIT: int = 10  # Requests per second
    MORALIS_CIRCUIT_BREAKER: int = 5  # Failures before opening circuit
    
    # Stripe Configuration
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_PRICE_PRO: str = "price_pro_monthly"
    STRIPE_PRICE_API: str = "price_api_monthly"
    
    # Application Configuration
    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"
    FLY_REGION: Optional[str] = None
    
    # Rate Limiting
    FREE_USER_RATE_LIMIT: int = 3  # queries per day
    PRO_USER_RATE_LIMIT: int = 1000  # effectively unlimited
    COMMAND_TIMEOUT: int = 30  # seconds
    
    # Alert Configuration
    ALERT_CHECK_INTERVAL: int = 30  # seconds
    ALERT_MAX_QUEUE: int = 1000
    
    # Web Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    @validator("DISCORD_TOKEN")
    def discord_token_not_empty(cls, v):
        if not v or v == "YOUR_DISCORD_TOKEN":
            logger.critical("DISCORD_TOKEN is not set!")
            raise ValueError("DISCORD_TOKEN is required")
        return v
    
    @validator("STRIPE_SECRET_KEY")
    def stripe_key_valid(cls, v):
        if v.startswith("sk_live_"):
            logger.warning("Using LIVE Stripe key in %s environment", os.getenv("ENVIRONMENT", "unknown"))
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
try:
    settings = Settings()
    logger.info(f"Configuration loaded for environment: {settings.ENVIRONMENT}")
except Exception as e:
    logger.critical(f"Failed to load configuration: {e}")
    # Provide minimal defaults for emergency startup
    settings = Settings(
        DISCORD_TOKEN=os.getenv("DISCORD_TOKEN", ""),
        DISCORD_CLIENT_ID=os.getenv("DISCORD_CLIENT_ID", ""),
        FIREBASE_PROJECT_ID=os.getenv("FIREBASE_PROJECT_ID", ""),
        MORALIS_API_KEY=os.getenv("MORALIS_API_KEY", ""),
        STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY", ""),
        STRIPE_WEBHOOK_SECRET=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
    )