import re
import random
import logging
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession, RequestsError
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.scrapers.base import BaseScraper
from app.schemas.product import NewsSchema
from app.exceptions import ScrapeFailed

logger = logging.getLogger("scraper.mobile01")


class Mobile01Scraper(BaseScraper):
    CATEGORY_TO_CID = {
        "phone": 16,
        "laptop": 19,
        "computer": 17,
        "apple": 30,
        "camera": 20
    }

    def get_default_headers(self) -> Dict[str, str]:
        """覆寫基類以對齊 curl-cffi 瀏覽器指紋，防止 UA 與 Sec-Ch-Ua 衝突引發 WAF 阻擋"""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.mobile01.com/"
        }

    def __init__(self, **kwargs):
        # 限制併發數為 2，並維持至少 1.0 秒請求間隔以示友善
        super().__init__(platform="mobile01", concurrency=2, min_interval=1.0, **kwargs)
        self.session: Optional[AsyncSession] = None

    async def get_session(self) -> AsyncSession:
        """獲取或懶載入初始化 curl_cffi AsyncSession 實例"""
        if self.session is None:
            self.session = AsyncSession(
                timeout=self.timeout_seconds,
                proxies={"http": None, "https": None}
            )
        return self.session

    async def close(self):
        """關閉與釋放 Session"""
        if self.session:
            await self.session.close()
            self.session = None
        await super().close()

    async def request_cf(self, url: str, **kwargs) -> str:
        """使用 curl-cffi 模擬 Chrome 繞過 Cloudflare 阻擋"""
        session = await self.get_session()
        headers = self.get_default_headers()
        
        custom_headers = kwargs.pop("headers", None)
        if custom_headers:
            headers.update(custom_headers)
        
        async with self.sem:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self.max_retries),
                    wait=wait_exponential(multiplier=1, min=self.backoff_min, max=self.backoff_max),
                    retry=retry_if_exception_type(RequestsError),
                    reraise=True
                ):
                    with attempt:
                        await self._rate_limit()
                        logger.debug(f"[mobile01] 正在請求 (impersonate='chrome110'): {url}")
                        response = await session.get(url, headers=headers, impersonate="chrome110", **kwargs)
                        
                        if response.status_code == 429:
                            logger.warning("[mobile01] 觸發 429 限速。退避重試中...")
                            raise RequestsError("Rate Limit (429)")
                            
                        if response.status_code != 200:
                            raise ScrapeFailed(f"HTTP 狀態碼錯誤: {response.status_code}", platform=self.platform)
                            
                        return response.content.decode('utf-8', errors='ignore')
            except RequestsError as e:
                raise ScrapeFailed(f"Cloudflare 繞過失敗或連線逾時: {str(e)}", platform=self.platform)
            except Exception as e:
                raise ScrapeFailed(f"連線異常: {str(e)}", platform=self.platform)

    async def _fetch_post_summary(self, forum_id: int, topic_id: str) -> Dict[str, str]:
        """點入貼文詳細頁，抓取一樓前 300 個字做為內容摘要，並順便解析文章所屬版塊來源"""
        await asyncio.sleep(random.uniform(1.0, 2.2))
        
        result = {"summary": "", "source_board": ""}
        url = f"https://www.mobile01.com/topicdetail.php?f={forum_id}&t={topic_id}"
        ref_url = f"https://www.mobile01.com/topiclist.php?f={forum_id}" if forum_id else "https://www.mobile01.com/"
        try:
            html = await self.request_cf(url, headers={"Referer": ref_url}, timeout=10.0)
            soup = BeautifulSoup(html, "lxml")
            
            # 1. 抓取內文摘要
            content_elem = soup.select_one(".c-articleCard__content") or soup.select_one("article") or soup.select_one("[itemprop='articleBody']")
            if content_elem:
                text = content_elem.get_text(strip=True)
                text = re.sub(r"\s+", " ", text)
                result["summary"] = text[:300]
                
            # 2. 解析麵包屑來源 (例: 首頁 -> 蘋果 -> iPhone)
            bc_items = soup.select(".c-breadCrumb .c-breadCrumb__item")
            if len(bc_items) >= 3:
                cat_name = bc_items[1].get_text(strip=True)
                forum_name = bc_items[2].get_text(strip=True)
                result["source_board"] = f"Mobile01 - {forum_name} ({cat_name})"
                
        except Exception as e:
            logger.warning(f"擷取貼文內文與麵包屑失敗 (t={topic_id}): {str(e)}")
        return result

    async def scrape(
        self,
        category: str,
        keyword: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[NewsSchema]:
        logger.info(f"mobile01 爬取開始: 分類='{category}', 關鍵字='{keyword}', 目標數量={limit if limit is not None else '無限制'}")
        
        c_id = self.CATEGORY_TO_CID.get(category)
        if not c_id:
            logger.warning(f"mobile01 分類 '{category}' 未在綜合討論區映射表中註冊，結束爬取。")
            return []
            
        logger.info(f"Mobile01 綜合討論區啟用：使用大分類 c={c_id} 抓取...")
        posts: List[NewsSchema] = []
        consecutive_failures = 0
        circuit_broken = False
        
        # 設定爬取目標上限，預設抓前兩頁共 50 則貼文
        target_limit = limit if limit is not None else 50
        import math
        pages_needed = min(math.ceil(target_limit / 30), 2)  # 最大抓取 2 頁 (共 60 則)，防範 WAF
        
        for page in range(1, pages_needed + 1):
            if len(posts) >= target_limit:
                break
            
            # 每個分頁請求前重置 Session 連線以防 WAF 追蹤
            await self.close()
            
            if page == 1:
                url = f"https://www.mobile01.com/forumtopic.php?c={c_id}"
            else:
                url = f"https://www.mobile01.com/forumtopic.php?c={c_id}&p={page}"
                
            logger.info(f"[mobile01] 正在爬取大分類綜合區第 {page} 頁: {url}")
            try:
                html = await self.request_cf(url)
                soup = BeautifulSoup(html, "lxml")
                
                rows = soup.select(".l-listTable__tr")
                if len(rows) <= 1:
                    logger.warning(f"[mobile01] 綜合區第 {page} 頁貼文列表為空，疑似遭遇 CF WAF 挑戰")
                    circuit_broken = True
                    
                for row in rows[1:]:
                    if len(posts) >= target_limit:
                        break
                        
                    # A. 標題與連結
                    title_a = row.select_one(".c-listTableTd__title a.c-link")
                    if not title_a:
                        continue
                    title = title_a.get_text(strip=True)
                    href = title_a.get("href", "")
                    
                    if "topicdetail.php" not in href:
                        continue
                        
                    # 關鍵字過濾
                    if keyword and keyword.lower() not in title.lower():
                        continue
                        
                    # B. 發文時間
                    published_at = datetime.utcnow()
                    time_elem = row.select_one(".l-listTable__td--time .o-fNotes")
                    if time_elem:
                        time_str = time_elem.get_text(strip=True)
                        try:
                            published_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                        except Exception:
                            pass
                            
                    # C. 回覆數
                    reply_count = "0"
                    reply_elem = row.select_one(".l-listTable__td--count .o-fMini")
                    if reply_elem:
                        reply_count = reply_elem.get_text(strip=True)
                        
                    t_match = re.search(r"t=(\d+)", href)
                    topic_id = t_match.group(1) if t_match else ""
                    
                    f_id = "0"
                    if "f=" in href:
                        f_match = re.search(r"f=(\d+)", href)
                        f_id = f_match.group(1) if f_match else "0"
                    full_url = f"https://www.mobile01.com/topicdetail.php?f={f_id}&t={topic_id}"
                    
                    # D. 點入第一樓抓取前 300 字摘要 (50 則內文都抓詳情頁)
                    content_summary = ""
                    source_board = ""
                    if topic_id and not circuit_broken:
                        detail_info = await self._fetch_post_summary(int(f_id), topic_id)
                        content_summary = detail_info["summary"]
                        source_board = detail_info["source_board"]
                        
                    if topic_id and not circuit_broken:
                        if not content_summary:
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0
                            
                    if consecutive_failures >= 3:
                        logger.warning("[mobile01] 檢測到連續 3 次詳情頁抓取失敗，疑似觸發 Cloudflare WAF 限速。已主動熔斷並啟用「快速滑行模式」。")
                        circuit_broken = True
                        consecutive_failures = 0
                        
                    post = NewsSchema(
                        source=source_board or f"Mobile01 - {category.capitalize()} 綜合區",
                        title=title,
                        url=full_url,
                        published_at=published_at,
                        content_summary=content_summary or title,
                        promotions=[f"回覆: {reply_count}"],
                        scraped_at=datetime.utcnow()
                    )
                    posts.append(post)
                    
            except Exception as e:
                logger.warning(f"爬取 Mobile01 綜合區第 {page} 頁異常: {str(e)}")
                
            await asyncio.sleep(random.uniform(1.5, 3.0))
            
        logger.info(f"mobile01 綜合區爬取結束，共獲取 {len(posts)} 筆貼文")
        return posts[:limit] if limit is not None else posts
