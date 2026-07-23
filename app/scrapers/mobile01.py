import logging
import re
import asyncio
import random
from datetime import datetime
from typing import List, Optional, Any, Dict
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.scrapers.base import BaseScraper
from app.schemas.product import NewsSchema
from app.exceptions import ScrapeFailed

logger = logging.getLogger("scraper.mobile01")


class Mobile01Scraper(BaseScraper):
    def __init__(self, **kwargs):
        # 由於論壇防爬機制嚴格，我們限制併發數為 2，並維持至少 1.0 秒請求間隔以示友善
        super().__init__(platform="mobile01", concurrency=2, min_interval=1.0, **kwargs)
        self.session: Optional[AsyncSession] = None

    async def get_session(self) -> AsyncSession:
        """獲取或懶載入初始化 curl_cffi AsyncSession 實例"""
        if self.session is None:
            self.session = AsyncSession(timeout=self.timeout_seconds)
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
        headers["Referer"] = "https://www.mobile01.com/"
        
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

    async def _get_forum_ids_by_category(self, category: str) -> List[Dict[str, Any]]:
        """解析 sitemap.php，動態尋找對應大分類下所有的子板塊 ID 與名稱"""
        url = "https://www.mobile01.com/sitemap.php"
        try:
            html = await self.request_cf(url)
            soup = BeautifulSoup(html, "lxml")
            
            sections = soup.select(".u-gapNextV--lg")
            forum_list = []
            
            for sec in sections:
                title_a = sec.select_one(".l-heading__title h3 a.c-link")
                if not title_a:
                    continue
                sec_title = title_a.get_text(strip=True)
                
                
                # 比對大分類標題 (使用 \u 轉義以免疫 any OS encoding bug)
                matched = False
                if category == "phone" and "\u624b\u6a5f" in sec_title:
                    matched = True
                elif category == "camera" and ("\u76f8\u6a5f" in sec_title or "\u55ae\u773c" in sec_title):
                    matched = True
                elif category == "laptop" and "\u7b46\u96fb" in sec_title:
                    matched = True
                elif category == "computer" and "\u96fb\u8166" in sec_title and "\u7b46\u8a18\u578b" not in sec_title:
                    matched = True
                elif category == "apple" and ("\u860b\u679c" in sec_title or "Apple" in sec_title):
                    matched = True
                    
                if matched:
                    # 抓取該大分類下的所有子板塊 (topiclist.php?f=xxx)
                    sub_links = sec.find_all("a", href=lambda x: x and "topiclist.php?f=" in x)
                    for link in sub_links:
                        href = link.get("href")
                        name = link.get_text(strip=True)
                        f_match = re.search(r"f=(\d+)", href)
                        if f_match:
                            forum_list.append({
                                "id": int(f_match.group(1)),
                                "name": name
                            })
            
            logger.info(f"Mobile01 Sitemap 解析完畢，分類='{category}'，共找到 {len(forum_list)} 個子版塊")
            return forum_list
        except Exception as e:
            logger.error(f"Mobile01 Sitemap 解析失敗: {str(e)}")
            return []

    async def _fetch_post_summary(self, forum_id: int, topic_id: str) -> str:
        """點入貼文詳細頁，抓取一樓前 300 個字做為內容摘要"""
        # 加入 0.5 ~ 1.5 秒隨機真人延遲，防範 Datacenter IP 請求頻率過快被 CF 判定為機器人 403
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        url = f"https://www.mobile01.com/topicdetail.php?f={forum_id}&t={topic_id}"
        ref_url = f"https://www.mobile01.com/topiclist.php?f={forum_id}"
        try:
            # 傳入母版塊 Referer 建立健全的 Referral 瀏覽路徑鏈條
            html = await self.request_cf(url, headers={"Referer": ref_url}, timeout=10.0)
            soup = BeautifulSoup(html, "lxml")
            
            content_elem = soup.select_one(".c-articleCard__content") or soup.select_one("article") or soup.select_one("[itemprop='articleBody']")
            if content_elem:
                text = content_elem.get_text(strip=True)
                # 清洗多餘空格
                text = re.sub(r"\s+", " ", text)
                return text[:300]
        except Exception as e:
            logger.warning(f"擷取貼文內文摘要失敗 (t={topic_id}): {str(e)}")
        return ""

    async def scrape(
        self,
        category: str,
        keyword: Optional[str] = None,
        limit: Optional[int] = 10
    ) -> List[NewsSchema]:
        limit = limit or 10
        logger.info(f"mobile01 爬取開始: 分類='{category}', 關鍵字='{keyword}', 目標數量={limit}")
        
        # 1. 取得目標大類的所有子板塊 ID
        forums = await self._get_forum_ids_by_category(category)
        if not forums:
            logger.warning(f"mobile01 分類 '{category}' 無子分類板塊，結束爬取。")
            return []
            
        posts: List[NewsSchema] = []
        
        # 2. 輪詢子板塊取得文章
        # 為了保證品類下的多樣性，我們從每個子板塊抓取前 5 篇，直到抓滿 limit
        posts_per_forum = 5
        
        for forum in forums:
            if len(posts) >= limit:
                break
                
            forum_id = forum["id"]
            forum_name = forum["name"]
            
            url = f"https://www.mobile01.com/topiclist.php?f={forum_id}"
            try:
                html = await self.request_cf(url)
                soup = BeautifulSoup(html, "lxml")
                
                rows = soup.select(".l-listTable__tr")
                # 跳過表頭 (第一列)
                if len(rows) <= 1:
                    continue
                    
                added_count = 0
                for row in rows[1:]:
                    if len(posts) >= limit or added_count >= posts_per_forum:
                        break
                        
                    # A. 標題與連結
                    title_a = row.select_one(".c-listTableTd__title a.c-link")
                    if not title_a:
                        continue
                    title = title_a.get_text(strip=True)
                    href = title_a.get("href")
                    
                    # 關鍵字過濾
                    if keyword and keyword.lower() not in title.lower():
                        continue
                        
                    # B. 發文時間 (發文者欄位下的 o-fNotes)
                    # 每列中有兩個 l-listTable__td--time，第一個是發文時間，第二個是最後回覆時間
                    time_elems = row.select(".l-listTable__td--time .o-fNotes")
                    published_at = None
                    if time_elems:
                        time_str = time_elems[0].get_text(strip=True)
                        try:
                            published_at = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                        except Exception:
                            pass
                            
                    # C. 回覆數 (Reply Count)
                    reply_count = "0"
                    reply_elem = row.select_one(".l-listTable__td--count .o-fMini")
                    if reply_elem:
                        reply_count = reply_elem.get_text(strip=True)
                        
                    t_match = re.search(r"t=(\d+)", href)
                    topic_id = t_match.group(1) if t_match else ""
                    
                    full_url = f"https://www.mobile01.com/topicdetail.php?f={forum_id}&t={topic_id}"
                    
                    # D. 點入第一樓抓取前 300 字摘要
                    content_summary = ""
                    if topic_id:
                        content_summary = await self._fetch_post_summary(forum_id, topic_id)
                        
                    post = NewsSchema(
                        source=f"Mobile01 - {forum_name} ({category.capitalize()})",
                        title=title,
                        url=full_url,
                        published_at=published_at,
                        content_summary=content_summary or title, # 回退方案
                        promotions=[f"回覆: {reply_count}"],
                        scraped_at=datetime.utcnow()
                    )
                    posts.append(post)
                    added_count += 1
                    
            except Exception as e:
                logger.warning(f"爬取 Mobile01 板塊 {forum_name} (f={forum_id}) 異常: {str(e)}")
                continue
                
        logger.info(f"mobile01 爬取結束，共獲取 {len(posts)} 筆貼文")
        return posts[:limit]
