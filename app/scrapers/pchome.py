import logging
from datetime import datetime
from typing import List, Optional, Any
import httpx

from app.scrapers.base import BaseScraper
from app.schemas.product import ProductSchema

logger = logging.getLogger("scraper.pchome")


class PchomeScraper(BaseScraper):
    def __init__(self):
        # PChome API 較穩定，併發設為 2，最小間隔 0.5s
        super().__init__(
            platform="pchome", 
            concurrency=2, 
            min_interval=0.5, 
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
        # 簡單從標題首字判定常見品牌
        brands = ["ASUS", "MSI", "ACER", "GIGABYTE", "LENOVO", "HP", "DELL", "APPLE", "SAMSUNG"]
        upper_title = title.upper()
        for b in brands:
            if b in upper_title:
                return b
        # 若沒匹配到，提取第一個英文單字作為 brand 猜測
        words = title.split()
        if words and words[0].isalnum():
            return words[0]
        return None

    async def scrape(
        self, 
        category: str, 
        keyword: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[ProductSchema]:
        search_kw = keyword or self._get_keyword_by_category(category)
        limit = limit or 20
        
        products = []
        page = 1
        max_pages = 5  # 防禦性最大頁數，防止無窮迴圈
        
        logger.info(f"PChome 爬取開始: 關鍵字='{search_kw}', 品類='{category}', 目標數量={limit}")
        
        try:
            while len(products) < limit and page <= max_pages:
                url = f"https://ecshweb.pchome.com.tw/search/v3.3/all/results?q={search_kw}&page={page}&sort=rnk/dc"
                response = await self.request(url)
                data = response.json()
                
                if "prods" not in data or not data["prods"]:
                    logger.info(f"PChome API 於第 {page} 頁未返回更多商品。")
                    break
                    
                for item in data["prods"]:
                    title = item.get("name", "")
                    price = item.get("price", 0)
                    original_price = item.get("originPrice", None)
                    if original_price == 0 or original_price == price:
                        original_price = None
                        
                    prod_id = item.get("Id", "")
                    prod_url = f"https://24h.pchome.com.tw/prod/{prod_id}"
                    
                    # 促銷活動解析
                    promotions = []
                    if item.get("isCoupon", False):
                        promotions.append("折價券折抵")
                    if item.get("isPChomePay", False):
                        promotions.append("PChomePay 優惠")
                        
                    product = ProductSchema(
                        platform=self.platform,
                        brand=self._extract_brand(title),
                        category=category,
                        title=title,
                        model=prod_id,
                        price=int(price) if price else 0,
                        original_price=int(original_price) if original_price else None,
                        promotions=promotions,
                        stock_status="in_stock" if item.get("isRed", False) or item.get("qty", 1) > 0 else "out_of_stock",
                        url=prod_url,
                        scraped_at=datetime.utcnow()
                    )
                    products.append(product)
                    if len(products) >= limit:
                        break
                        
                page += 1
                
            logger.info(f"PChome 成功抓取並標準化 {len(products)} 筆商品。")
            return products
            
        except Exception as e:
            logger.error(f"PChome 爬取中途失敗: {str(e)}")
            return products
