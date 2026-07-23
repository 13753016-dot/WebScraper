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
    # 本地備用子版塊快取 (當 Sitemap 被 WAF 阻擋或解析失敗時無縫降級啟用，確保 100% 服務可用性)
    FALLBACK_FORUMS = {
        "apple": [
            {"id": 383, "name": "iPhone"},
            {"id": 627, "name": "iPhone 軟體"},
            {"id": 563, "name": "iPad"},
            {"id": 626, "name": "iPad 軟體"},
            {"id": 481, "name": "Mac筆記型電腦"},
            {"id": 480, "name": "Mac桌上型電腦"},
            {"id": 470, "name": "Apple Watch"},
            {"id": 482, "name": "蘋果軟體綜合"},
            {"id": 483, "name": "蘋果周邊綜合"}
        ],
        "phone": [
            {"id": 569, "name": "Samsung"},
            {"id": 588, "name": "ASUS"},
            {"id": 565, "name": "Google"},
            {"id": 566, "name": "Sony"},
            {"id": 568, "name": "Android智慧型手機綜合"}
        ],
        "camera": [
            {"id": 244, "name": "Canon單眼相機"},
            {"id": 248, "name": "Nikon單眼相機"},
            {"id": 254, "name": "Sony單眼相機"},
            {"id": 257, "name": "單眼數位相機綜合"}
        ],
        "laptop": [
            {"id": 233, "name": "Asus筆記型電腦"},
            {"id": 232, "name": "Acer筆記型電腦"},
            {"id": 241, "name": "MSI筆記型電腦"},
            {"id": 159, "name": "攜帶型電腦綜合"}
        ],
        "computer": [
            {"id": 396, "name": "自組電腦分享"},
            {"id": 513, "name": "電腦桌上型綜合"},
            {"id": 300, "name": "電腦安全綜合"}
        ]
    }

    def __init__(self, **kwargs):
        # 由於論壇防爬機制嚴格，我們限制併發數為 2，並維持至少 1.0 秒請求間隔以示友善
        super().__init__(platform="mobile01", concurrency=2, min_interval=1.0, **kwargs)
        self.session: Optional[AsyncSession] = None

    async def get_session(self) -> AsyncSession:
        """獲取或懶載入初始化 curl_cffi AsyncSession 實例"""
        if self.session is None:
            # 預設禁用系統代理，避免本地代理軟體干擾
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
        headers["Referer"] = "https://www.mobile01.com/"
        
        # 合併並彈出 kwargs 中的自定義 headers，避免 session.get 重複傳參
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
                
                
                # 比對大分類標題 (使用 chr() 函數動態構造，徹底免疫任何作業系統/直譯器編碼載入 Bug)
                matched = False
                title_phone = chr(25163) + chr(27231)        # 手機
                title_camera = chr(30456) + chr(27231)       # 相機
                title_dslr = chr(21934) + chr(30524)         # 單眼
                title_laptop = chr(31558) + chr(38651)       # 筆電
                title_computer = chr(38651) + chr(33126)     # 電腦
                title_notebook = chr(31558) + chr(35352) + chr(22411) # 筆記型
                title_apple = chr(34315) + chr(26524)        # 蘋果
                
                if category == "phone" and title_phone in sec_title:
                    matched = True
                elif category == "camera" and (title_camera in sec_title or title_dslr in sec_title):
                    matched = True
                elif category == "laptop" and title_laptop in sec_title:
                    matched = True
                elif category == "computer" and title_computer in sec_title and title_notebook not in sec_title:
                    matched = True
                elif category == "apple" and (title_apple in sec_title or "Apple" in sec_title):
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
            
            if not forum_list:
                fallback_list = self.FALLBACK_FORUMS.get(category, [])
                logger.warning(f"Mobile01 Sitemap 解析子分類為空，啟用本地靜態 Fallback 快取... 分類='{category}', 快取長度={len(fallback_list)}")
                return fallback_list
            return forum_list
        except Exception as e:
            fallback_list = self.FALLBACK_FORUMS.get(category, [])
            logger.error(f"Mobile01 Sitemap 解析失敗: {str(e)}，啟用本地靜態 Fallback 快取... 分類='{category}', 快取長度={len(fallback_list)}")
            return fallback_list

    async def _fetch_post_summary(self, forum_id: int, topic_id: str) -> str:
        """點入貼文詳細頁，抓取一樓前 300 個字做為內容摘要"""
        # 微調隨機真人延遲，防範 Datacenter IP 請求頻率過快被 CF 判定為機器人 403
        await asyncio.sleep(random.uniform(1.0, 2.2))
        
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
        limit: Optional[int] = None
    ) -> List[NewsSchema]:
        logger.info(f"mobile01 爬取開始: 分類='{category}', 關鍵字='{keyword}', 目標數量={limit if limit is not None else '無限制'}")
        
        # 1. 取得目標大類的所有子板塊 ID
        forums = await self._get_forum_ids_by_category(category)
        logger.info(f"Mobile01 分類='{category}' 取得子板塊共 {len(forums)} 個，準備開始遍歷爬取...")
        if not forums:
            logger.warning(f"mobile01 分類 '{category}' 無子分類板塊，結束爬取。")
            return []
            
        posts: List[NewsSchema] = []
        consecutive_failures = 0
        
        # 2. 輪詢子板塊取得文章，每個子板塊固定抓取最新的前 15 則文章
        posts_per_forum = 15
        
        for forum in forums:
            if limit is not None and len(posts) >= limit:
                break
                
            # 關閉並重置 Session 連線，讓每個子板塊皆使用全新 TLS 握手與 Local Port，粉碎 WAF 行為追蹤
            await self.close()
            
            forum_id = forum["id"]
            forum_name = forum["name"]
            logger.info(f"[DEBUG] 開始爬取板塊 {forum_name} (f={forum_id})")
            
            url = f"https://www.mobile01.com/topiclist.php?f={forum_id}"
            try:
                html = await self.request_cf(url)
                soup = BeautifulSoup(html, "lxml")
                
                rows = soup.select(".l-listTable__tr")
                # 跳過表頭 (第一列)
                if len(rows) <= 1:
                    logger.warning(f"[mobile01] 板塊 {forum_name} (f={forum_id}) 貼文列表為空，疑似遭遇 CF WAF 挑戰攔截")
                    
                added_count = 0
                for row in rows[1:]:
                    if (limit is not None and len(posts) >= limit) or added_count >= posts_per_forum:
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
                        
                    # 統計連續失敗次數，用以自適應觸發冷卻防禦 WAF
                    if topic_id:
                        if not content_summary:
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0
                            
                    if consecutive_failures >= 3:
                        logger.warning("[mobile01] 檢測到連續 3 次詳情頁抓取失敗，疑似觸發 Cloudflare WAF 限速。主動進行 15 秒深度冷卻休眠...")
                        await asyncio.sleep(15.0)
                        consecutive_failures = 0  # 重置
                        
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
                
            # 板塊與板塊之間加入隨機延遲，防止高頻請求觸發 Cloudflare WAF 阻擋
            await asyncio.sleep(random.uniform(1.5, 3.0))
                
        logger.info(f"mobile01 爬取結束，共獲取 {len(posts)} 筆貼文")
        return posts[:limit] if limit is not None else posts
