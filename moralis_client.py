"""
Moralis API client with circuit breaker pattern, fallback sources, and data enrichment.
Implements robust error handling and graceful degradation.
"""
import logging
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum
import aiohttp
import time

from config import settings

logger = logging.getLogger(__name__)


class DataSource(Enum):
    MORALIS = "moralis"
    SIMPLEHASH = "simplehash"
    RESERVOIR = "reservoir"
    CACHED = "cached"


class CircuitBreaker:
    """Circuit breaker pattern for API failures"""
    
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    def record_failure(self):
        """Record an API failure"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker OPENED after {self.failure_count} failures")
    
    def record_success(self):
        """Reset circuit breaker on success"""
        self.failure_count = 0
        self.state = "CLOSED"
        logger.debug