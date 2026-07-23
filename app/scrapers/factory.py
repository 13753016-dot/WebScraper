from typing import Dict, Type
from app.scrapers.base import BaseScraper
from app.scrapers.pchome import PchomeScraper
from app.scrapers.momo import MomoScraper
from app.scrapers.coolpc import CoolpcScraper

_SCRAPERS: Dict[str, Type[BaseScraper]] = {
    "pchome": PchomeScraper,
    "momo": MomoScraper,
    "coolpc": CoolpcScraper
}


class ScraperFactory:
    @staticmethod
    def get_scraper(platform: str) -> BaseScraper:
        """根據平台名稱取得對應的 Scraper 實例"""
        plat_lower = platform.lower()
        if plat_lower not in _SCRAPERS:
            supported = ", ".join(_SCRAPERS.keys())
            raise ValueError(f"不支援的平台: '{platform}'。支援的平台有: {supported}")
        
        return _SCRAPERS[plat_lower]()
