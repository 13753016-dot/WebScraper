import time
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import List, Any, Dict, Optional
import httpx
from fake_useragent import UserAgent
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.exceptions import ScrapeFailed, RateLimitExceeded

logger = logging.getLogger("scraper.base")


class BaseScraper(ABC):
    def __init__(
        self,
        platform: str,
        concurrency: int = 1,
        min_interval: float = 1.0,
        max_retries: int = 3,
        timeout_seconds: float = 15.0
    ):
        self.platform = platform
        self.sem = asyncio.Semaphore(concurrency)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        
        self.backoff_min = 2.0
        self.backoff_max = 10.0
        self.last_request_time = 0.0
        self.client: Optional[httpx.AsyncClient] = None
        self.ua = UserAgent()

    def get_default_headers(self) -> Dict[str, str]:
        """產生正常瀏覽器的 headers"""
        return {
            "User-Agent": self.ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="115", "Chromium";v="115"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

    async def get_client(self) -> httpx.AsyncClient:
        """懶載入獲取 HTTPX Client 實例"""
        if self.client is None or self.client.is_closed:
            limits = httpx.Limits(
                max_connections=10, 
                max_keepalive_connections=5,
                keepalive_expiry=30.0
            )
            self.client = httpx.AsyncClient(
                limits=limits,
                headers=self.get_default_headers(),
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=True
            )
        return self.client

    async def _rate_limit(self):
        """控制 QPS：確保兩次請求間至少間隔 min_interval 秒"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            await asyncio.sleep(wait_time)
        self.last_request_time = time.time()

    async def request(
        self, 
        url: str, 
        method: str = "GET", 
        headers: Dict[str, str] = None, 
        **kwargs
    ) -> httpx.Response:
        """執行具備併發控制、限速、指數退避重試的 HTTP 請求"""
        client = await self.get_client()
        req_headers = self.get_default_headers()
        if headers:
            req_headers.update(headers)

        async with self.sem:
            # 指數退避重試機制
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self.max_retries),
                    wait=wait_exponential(multiplier=1, min=self.backoff_min, max=self.backoff_max),
                    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectTimeout, httpx.ConnectError)),
                    reraise=True
                ):
                    with attempt:
                        # 在每一次重試嘗試前皆觸發 Rate Limiter，以防止重試時流量過載
                        await self._rate_limit()
                        
                        logger.debug(f"[{self.platform}] Requesting {method} {url}")
                        response = await client.request(method, url, headers=req_headers, **kwargs)
                        
                        # 若為 429 則拋出 StatusError 以觸發 tenacity 重試
                        if response.status_code == 429:
                            logger.warning(f"[{self.platform}] Rate limit hit (429). Retrying...")
                            raise httpx.HTTPStatusError(
                                message="Rate Limit (429)", 
                                request=response.request, 
                                response=response
                            )
                            
                        response.raise_for_status()
                        return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RateLimitExceeded(f"平台 {self.platform} 連續 429 限速，停止爬取", platform=self.platform)
                raise ScrapeFailed(f"HTTP 錯誤: {e.response.status_code}", platform=self.platform)
            except Exception as e:
                raise ScrapeFailed(f"連線異常: {str(e)}", platform=self.platform)

        # 這裡不應該被執行到，主要是作為防禦性回退
        raise ScrapeFailed("未知請求錯誤", platform=self.platform)

    async def close(self):
        """關閉 Client"""
        if self.client and not self.client.is_closed:
            await self.client.aclose()

    @abstractmethod
    async def scrape(
        self, 
        category: str, 
        keyword: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[Any]:
        """子類別必須實作的爬取解析進入點，需回傳 Pydantic models (ProductSchema/NewsSchema)"""
        pass
