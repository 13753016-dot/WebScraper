from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.database import get_db
from app.schemas.job import JobCreate
from app.services.job_service import JobService
from app.exceptions import ScraperError, RateLimitExceeded

router = APIRouter(prefix="/scrape", tags=["Sync Scrape"])


@router.post("/sync", response_model=List[Any], summary="同步即時爬取商品或新聞資料")
async def scrape_sync(request: JobCreate, db: Session = Depends(get_db)):
    """
    立即觸發爬取，並等待結果回傳。
    此端點通常用於少量資料抓取與除錯，限制爬取數量防止 HTTP Timeout。
    """
    # 限制同步爬取的數量，防止阻塞與 Timeout
    limit = min(request.limit or 20, 50)
    
    service = JobService(db)
    try:
        results = await service.run_sync_scrape(
            platform=request.platform,
            category=request.category,
            keyword=request.keyword,
            limit=limit
        )
        return results
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RateLimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"平台 {e.platform} 連續觸發限速，暫時拒絕請求: {e.message}"
        )
    except ScraperError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"爬取失敗: {e.message}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"系統未知異常: {str(e)}"
        )
