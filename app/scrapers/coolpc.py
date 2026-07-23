import logging
import re
from datetime import datetime
from typing import List, Optional, Any, Union
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.schemas.product import ProductSchema, NewsSchema

logger = logging.getLogger("scraper.coolpc")


class CoolpcScraper(BaseScraper):
    def __init__(self):
        # 原價屋主機防爬與流量限制一般，但為求穩定設置併發 1，最小間隔 1.0 秒
        super().__init__(
            platform="coolpc", 
            concurrency=1, 
            min_interval=1.0, 
            max_retries=3
        )

    def _get_select_name_by_category(self, category: str) -> Optional[str]:
        # 原價屋估價單 (evaluate.php) 中各品類 select name 的映射
        mapping = {
            "laptop": "n2",      # 筆電/套裝電腦
            "ram": "n6",         # 記憶體
            "ssd": "n7",         # 固態硬碟 SSD
            "gpu": "n12",        # 顯示卡
            "monitor": "n13",    # 螢幕
        }
        return mapping.get(category.lower())

    def _extract_brand(self, title: str) -> Optional[str]:
        brands = ["華碩", "ASUS", "微星", "MSI", "技嘉", "GIGABYTE", "微軟", "MICROSOFT", "聯想", "LENOVO", "ACER", "宏碁", "HP", "DELL", "APPLE", "SAMSUNG", "金士頓", "KINGSTON", "美光", "CRUCIAL", "創見", "TRANSCEND", "威剛", "ADATA"]
        upper_title = title.upper()
        for b in brands:
            if b in upper_title:
                return b.replace("華碩", "ASUS").replace("微星", "MSI").replace("技嘉", "GIGABYTE").replace("微軟", "MICROSOFT").replace("聯想", "LENOVO").replace("宏碁", "ACER").replace("金士頓", "KINGSTON").replace("美光", "CRUCIAL").replace("創見", "TRANSCEND").replace("威剛", "ADATA")
        return None

    async def _scrape_products(self, category: str, limit: int) -> List[ProductSchema]:
        select_name = self._get_select_name_by_category(category)
        if not select_name:
            logger.warning(f"原價屋不支援商品品類: {category}")
            return []
            
        url = "https://coolpc.com.tw/evaluate.php"
        
        try:
            logger.info(f"原價屋商品爬取開始: 品類='{category}'")
            response = await self.request(url)
            
            # 原價屋使用 big5 編碼，必須手動指定避免亂碼
            html_content = response.content.decode("big5", errors="ignore")
            soup = BeautifulSoup(html_content, "lxml")
            
            select_tag = soup.find("select", attrs={"name": select_name})
            if not select_tag:
                logger.error(f"找不到 select name 為 {select_name} 的商品區塊。")
                return []
                
            options = select_tag.find_all("option")
            products = []
            
            # 第一個 option 通常是分類提示，如「請選擇...」，跳過
            for opt in options[1:]:
                opt_text = opt.get_text(strip=True)
                if not opt_text or "◆" in opt_text: # 跳過群組分隔線
                    continue
                    
                # 原價屋選項格式範例:
                # 華碩 ROG Zephyrus G16 GU605... $62900 ◆ ★ 熱賣
                # 微星 RTX4060Ti Ventus 2X Black 8G OC $11900
                price_match = re.search(r"\$(\d+)", opt_text)
                if not price_match:
                    continue
                    
                price = int(price_match.group(1))
                
                # 取得價格之前的文字作為標題
                title_part = opt_text.split("$")[0].strip()
                # 去除末尾的逗號或斜線
                title = re.sub(r"[,/]$", "", title_part).strip()
                
                # 提取促銷活動 (例如有 "★"、"熱賣"、"優惠價"、"送..." 等字眼)
                promotions = []
                if "★" in opt_text:
                    promotions.append("推薦/熱賣商品")
                if "砍" in opt_text or "下殺" in opt_text or "促銷" in opt_text:
                    promotions.append("限時下殺")
                # 擷取括弧外的促銷文字，例如「送滑鼠」
                gift_match = re.search(r"送[^\s,]*", opt_text)
                if gift_match:
                    promotions.append(gift_match.group(0))
                    
                product = ProductSchema(
                    platform=self.platform,
                    brand=self._extract_brand(title),
                    category=category,
                    title=title,
                    model=None, # 原價屋為列表，型號需從標題中解析
                    price=price,
                    original_price=None,
                    promotions=promotions,
                    stock_status="in_stock" if "缺貨" not in opt_text else "out_of_stock",
                    url="https://coolpc.com.tw/evaluate.php", # 原價屋無單品連結，皆指向估價單頁面
                    scraped_at=datetime.utcnow()
                )
                products.append(product)
                if len(products) >= limit:
                    break
                    
            logger.info(f"原價屋商品成功抓取並標準化 {len(products)} 筆商品。")
            return products
            
        except Exception as e:
            logger.error(f"原價屋商品爬取失敗: {str(e)}")
            return []

    async def _scrape_news(self, limit: int) -> List[NewsSchema]:
        """抓取原價屋促銷與新品新聞"""
        url = "https://coolpc.com.tw/"
        
        try:
            logger.info("原價屋新聞爬取開始")
            response = await self.request(url)
            soup = BeautifulSoup(response.text, "lxml")
            
            # 取得文章列表
            articles = soup.find_all("article")
            news_list = []
            
            for article in articles[:limit]:
                # 尋找非空的 a 標籤作為標題與連結
                title = None
                news_url = None
                for a in article.find_all("a"):
                    text = a.get_text(strip=True)
                    href = a.get("href")
                    # 過濾掉「閱讀更多」、「閱讀全文」或是空白連結
                    if text and href and text != "閱讀更多" and text != "詳細下架" and len(text) > 5:
                        title = text
                        news_url = href
                        break
                
                if not title or not news_url:
                    continue
                    
                # 轉成絕對路徑
                if news_url.startswith("/"):
                    news_url = f"https://coolpc.com.tw{news_url}"
                
                # 發布時間 (解析 posted-on 下的文字日期 2026/07/22)
                published_at = None
                posted_on = article.select_one(".posted-on")
                if posted_on:
                    time_text = posted_on.get_text(strip=True)
                    date_match = re.search(r"(\d{4}/\d{2}/\d{2})", time_text)
                    if date_match:
                        try:
                            published_at = datetime.strptime(date_match.group(1), "%Y/%m/%d")
                        except Exception:
                            pass
                
                # 內文摘要
                summary_div = article.select_one(".entry-content") or article.select_one(".entry-summary")
                summary = summary_div.get_text(strip=True)[:200] if summary_div else ""
                
                news = NewsSchema(
                    source="原價屋 Coolpc",
                    title=title,
                    url=news_url,
                    published_at=published_at,
                    content_summary=summary,
                    scraped_at=datetime.utcnow()
                )
                news_list.append(news)
                
            logger.info(f"原價屋新聞成功抓取並標準化 {len(news_list)} 筆。")
            return news_list
            
        except Exception as e:
            logger.error(f"原價屋新聞爬取失敗: {str(e)}")
            return []

    async def scrape(
        self, 
        category: str, 
        keyword: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[Union[ProductSchema, NewsSchema]]:
        limit = limit or 20
        if category.lower() == "news":
            return await self._scrape_news(limit)
        else:
            return await self._scrape_products(category, limit)
