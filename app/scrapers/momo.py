import logging
import re
from datetime import datetime
from typing import List, Optional, Any
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.schemas.product import ProductSchema

logger = logging.getLogger("scraper.momo")


class MomoScraper(BaseScraper):
    def __init__(self):
        # momo 防爬較嚴格，限制併發為 1，最小請求間隔 1.5 秒
        super().__init__(
            platform="momo", 
            concurrency=1, 
            min_interval=1.5, 
            max_retries=3
        )

    def _get_keyword_by_category(self, category: str) -> str:
        mapping = {
            "laptop": "筆電",
            "gpu": "顯示卡",
            "ssd": "SSD",
            "ram": "記憶體",
            "monitor": "螢幕",
            "phone": "手機",
            "tablet": "平板"
        }
        return mapping.get(category.lower(), "3C")

    def _extract_brand(self, title: str) -> Optional[str]:
        brands = ["ASUS", "華碩", "MSI", "微星", "ACER", "宏碁", "GIGABYTE", "技嘉", "LENOVO", "聯想", "HP", "DELL", "APPLE", "SAMSUNG"]
        upper_title = title.upper()
        for b in brands:
            if b in upper_title:
                return b.replace("華碩", "ASUS").replace("微星", "MSI").replace("宏碁", "ACER").replace("技嘉", "GIGABYTE").replace("聯想", "LENOVO")
        return None

    def _clean_price(self, price_str: str) -> int:
        # 移除非數字字元 (例如 $, , 元)
        nums = re.sub(r"[^\d]", "", price_str)
        return int(nums) if nums else 0

    async def scrape(
        self, 
        category: str, 
        keyword: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[ProductSchema]:
        search_kw = keyword or self._get_keyword_by_category(category)
        limit = limit or 15
        
        products = []
        page = 1
        max_pages = 4  # 防禦性最大頁數
        
        headers = {
            "Host": "m.momoshop.com.tw",
            "Referer": "https://m.momoshop.com.tw/"
        }
        
        logger.info(f"momo 爬取開始: 關鍵字='{search_kw}', 品類='{category}', 目標數量={limit}")
        
        try:
            while len(products) < limit and page <= max_pages:
                url = f"https://m.momoshop.com.tw/search.momo?searchKeyword={search_kw}&curPage={page}"
                response = await self.request(url, headers=headers)
                
                soup = BeautifulSoup(response.text, "lxml")
                
                # 尋找含有商品資料 JSON 欄位的 script 標籤 (Next.js App Router 狀態字串)
                scripts = soup.find_all("script")
                target_text = None
                for s in scripts:
                    if s.string and "goodsInfoList" in s.string:
                        target_text = s.string
                        break
                        
                if not target_text:
                    logger.info(f"momo 於第 {page} 頁未發現 goodsInfoList 數據，結束爬取。")
                    break
                    
                # 還原 React 序列化與轉義引號
                text_cleaned = target_text.replace('\\"', '"').replace('\\\\', '\\')
                
                # 尋找所有商品 ID (goodsCode) 的區間位置
                code_matches = list(re.finditer(r'"goodsCode"\s*:\s*"(\d+)"', text_cleaned))
                if not code_matches:
                    logger.info(f"momo 於第 {page} 頁未發現商品代碼，結束爬取。")
                    break
                    
                page_added = 0
                for idx, match in enumerate(code_matches):
                    code = match.group(1)
                    start = match.start()
                    # 切出單個商品的區間字串
                    end = code_matches[idx+1].start() if idx + 1 < len(code_matches) else start + 1200
                    block = text_cleaned[start:end]
                    
                    # 擷取商品名稱
                    name_m = re.search(r'"goodsName"\s*:\s*"([^"]+)"', block)
                    title = name_m.group(1) if name_m else ""
                    if not title:
                        continue
                        
                    # 擷取價格
                    price_m = re.search(r'"goodsPrice"\s*:\s*"([^"]+)"', block)
                    price = self._clean_price(price_m.group(1)) if price_m else 0
                    
                    # 擷取原價
                    ori_price_m = re.search(r'"goodsPriceOri"\s*:\s*"([^"]+)"', block)
                    original_price = self._clean_price(ori_price_m.group(1)) if ori_price_m else None
                    if original_price == 0 or original_price == price:
                        original_price = None
                        
                    prod_url = f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={code}"
                    
                    # 擷取促銷標籤與速達狀態
                    promotions = []
                    if '"haveGift":true' in block:
                        promotions.append("有贈品")
                    if '"useCounpon":true' in block:
                        promotions.append("可使用折價券")
                    if '"isSpeedArrive":"true"' in block:
                        promotions.append("速達")
                        
                    product = ProductSchema(
                        platform=self.platform,
                        brand=self._extract_brand(title),
                        category=category,
                        title=title,
                        model=code,
                        price=price,
                        original_price=original_price,
                        promotions=promotions,
                        stock_status="in_stock",
                        url=prod_url,
                        scraped_at=datetime.utcnow()
                    )
                    products.append(product)
                    page_added += 1
                    if len(products) >= limit:
                        break
                        
                if page_added == 0:
                    # 若該頁沒擷取到任何合法商品，提前終止防止無窮迴圈
                    break
                    
                page += 1
                
            logger.info(f"momo 成功抓取並標準化 {len(products)} 筆商品。")
            return products
            
        except Exception as e:
            logger.error(f"momo 爬取中途失敗: {str(e)}")
            return products
