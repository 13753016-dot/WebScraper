import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Any
from sqlmodel import Session

from app.database import Job
from app.exceptions import JobNotFoundError, ScraperError
from app.schemas.job import JobCreate, JobStatusResponse, JobStatus
from app.repositories.job_repository import JobRepository
from app.repositories.result_repository import ResultRepository
from app.scrapers.factory import ScraperFactory

logger = logging.getLogger("services.job")


class JobService:
    def __init__(self, db: Session):
        self.db = db
        self.job_repo = JobRepository(db)
        self.result_repo = ResultRepository(db)

    def create_async_job(self, request: JobCreate) -> JobStatusResponse:
        """建立一個背景爬蟲任務"""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        
        # 建立任務記錄 (Pending)
        job = self.job_repo.create_job(
            job_id=job_id,
            platform=request.platform,
            category=request.category,
            keyword=request.keyword
        )
        
        # 建立任務時，自動在背景順便清理 5 天 (120 小時) 前的過期任務與結果紀錄
        try:
            self.run_cleanup(hours_to_keep=120)
        except Exception as e:
            logger.warning(f"自動清理過期暫存資料失敗: {str(e)}")
            
        return JobStatusResponse(
            job_id=job.job_id,
            platform=job.platform,
            category=job.category,
            status=JobStatus.PENDING,
            progress=job.progress,
            error_message=job.error_message,
            result_count=job.result_count,
            created_at=job.created_at,
            completed_at=job.completed_at
        )

    async def execute_scrape_job(
        self, 
        job_id: str, 
        platform: str, 
        category: str, 
        keyword: Optional[str] = None, 
        limit: Optional[int] = None
    ):
        """背景任務實際執行體，負責調用爬蟲、更新進度並儲存結果"""
        logger.info(f"開始執行背景爬取任務 {job_id} ({platform}/{category})")
        self.job_repo.update_job_status(job_id, status="running", progress="10%")
        
        scraper = None
        try:
            # 取得對應平台的爬蟲
            scraper = ScraperFactory.get_scraper(platform)
            self.job_repo.update_job_status(job_id, status="running", progress="30%")
            
            # 開始爬取
            results = await scraper.scrape(category=category, keyword=keyword, limit=limit)
            self.job_repo.update_job_status(job_id, status="running", progress="70%")
            
            # 儲存結果
            if results:
                self.result_repo.save_results(job_id, results)
                
            # 標記完成
            self.job_repo.update_job_status(
                job_id, 
                status="completed", 
                progress="100%", 
                result_count=len(results)
            )
            logger.info(f"任務 {job_id} 順利完成，共擷取 {len(results)} 筆資料")
            
        except Exception as e:
            logger.error(f"任務 {job_id} 執行異常: {str(e)}", exc_info=True)
            self.job_repo.update_job_status(
                job_id, 
                status="failed", 
                progress="100%", 
                error_message=str(e)
            )
        finally:
            if scraper:
                await scraper.close()

    def get_job_status(self, job_id: str) -> JobStatusResponse:
        """獲取目前任務的最新狀態"""
        job = self.job_repo.get_job(job_id)
        if not job:
            raise JobNotFoundError(job_id)
            
        return JobStatusResponse(
            job_id=job.job_id,
            platform=job.platform,
            category=job.category,
            status=JobStatus(job.status),
            progress=job.progress,
            error_message=job.error_message,
            result_count=job.result_count,
            created_at=job.created_at,
            completed_at=job.completed_at
        )

    def get_job_results(self, job_id: str) -> List[dict]:
        """獲取該任務的爬取 JSON 結果"""
        job = self.job_repo.get_job(job_id)
        if not job:
            raise JobNotFoundError(job_id)
        return self.result_repo.get_results_by_job(job_id)

    async def run_sync_scrape(
        self, 
        platform: str, 
        category: str, 
        keyword: Optional[str] = None, 
        limit: Optional[int] = None
    ) -> List[Any]:
        """同步即時執行爬取並返回結果，不儲存到 SQLite 資料庫"""
        scraper = ScraperFactory.get_scraper(platform)
        try:
            results = await scraper.scrape(category=category, keyword=keyword, limit=limit)
            return results
        finally:
            await scraper.close()
            
    def run_cleanup(self, hours_to_keep: int = 120):
        """主動清理過期暫存資料"""
        self.result_repo.clear_expired_results(hours_to_keep)
