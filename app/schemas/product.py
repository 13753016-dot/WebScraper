from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ProductSchema(BaseModel):
    platform: str = Field(..., description="來源平台，例如 momo, pchome, coolpc")
    brand: Optional[str] = Field(None, description="品牌名稱")
    category: str = Field(..., description="商品品類，例如 laptop, gpu, ssd")
    title: str = Field(..., description="商品完整名稱")
    model: Optional[str] = Field(None, description="商品型號")
    price: int = Field(..., description="目前售價")
    original_price: Optional[int] = Field(None, description="原始價格/原價")
    promotions: List[str] = Field(default_factory=list, description="促銷活動列表")
    stock_status: str = Field("in_stock", description="庫存狀態: in_stock, out_of_stock, unknown")
    url: str = Field(..., description="商品詳情頁網址")
    scraped_at: datetime = Field(default_factory=datetime.utcnow, description="爬取時間")


class NewsSchema(BaseModel):
    source: str = Field(..., description="科技媒體來源，例如 TechNews, Mashdigi")
    title: str = Field(..., description="新聞標題")
    url: str = Field(..., description="新聞網址")
    published_at: Optional[datetime] = Field(None, description="發布時間")
    content_summary: Optional[str] = Field(None, description="內文摘要")
    scraped_at: datetime = Field(default_factory=datetime.utcnow, description="爬取時間")
