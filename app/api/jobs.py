from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlmodel import Session

from app.database import get_db
from app.schemas.job import JobCreate, JobStatusResponse
from app.services.job_service import JobService
from app.exceptions import JobNotFoundError

router = APIRouter(prefix="/jobs", tags=["Async Jobs"])


@router.post("", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED, summary="建立背景爬蟲任務")
async def create_job(
    request: JobCreate, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    """
    建立非同步爬取任務，立即返回 job_id，並在背景以非同步方式執行爬取。
    """
    service = JobService(db)
    try:
        # 1. 建立任務記錄 (Pending)
        response = service.create_async_job(request)
        
        # 2. 加入背景任務佇列
        background_tasks.add_task(
            service.execute_scrape_job,
            job_id=response.job_id,
            platform=request.platform,
            category=request.category,
            keyword=request.keyword,
            limit=request.limit
        )
        
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{job_id}", response_model=JobStatusResponse, summary="查詢任務執行狀態與進度")
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    查詢特定任務的進度、狀態與錯誤訊息。
    """
    service = JobService(db)
    try:
        return service.get_job_status(job_id)
    except JobNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/{job_id}/results", response_model=List[Any], summary="獲取任務抓取到的標準 JSON 結果")
async def get_job_results(job_id: str, db: Session = Depends(get_db)):
    """
    下載此任務所爬取到的所有標準化 JSON 資料。
    """
    service = JobService(db)
    try:
        # 確認狀態
        status_info = service.get_job_status(job_id)
        if status_info.status == "pending" or status_info.status == "running":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"任務目前處於 {status_info.status} 狀態，尚未完成，請稍後再試。"
            )
            
        return service.get_job_results(job_id)
    except JobNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/cleanup", summary="手動/自動觸發過期暫存資料清理")
async def cleanup_results(days: int = 7, db: Session = Depends(get_db)):
    """
    清理指定天數 (預設 7 天) 之前的過期任務資料與暫存 JSON，防止 SQLite 檔案無限變大。
    """
    service = JobService(db)
    service.run_cleanup(days_to_keep=days)
    return {"message": f"成功清理大於 {days} 天的暫存資料"}
