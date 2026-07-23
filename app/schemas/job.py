from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobCreate(BaseModel):
    platform: str = Field(..., description="要爬取的平台，如 pchome, momo, coolpc")
    category: str = Field(..., description="品類，如 laptop, gpu, ssd")
    keyword: Optional[str] = Field(None, description="可選關鍵字")
    limit: Optional[int] = Field(None, description="最大爬取數量")


class JobStatusResponse(BaseModel):
    job_id: str = Field(..., description="任務唯一 ID")
    platform: str = Field(..., description="爬取平台")
    category: str = Field(..., description="品類")
    status: JobStatus = Field(..., description="任務狀態")
    progress: str = Field("0%", description="任務進度")
    error_message: Optional[str] = Field(None, description="錯誤訊息")
    result_count: int = Field(0, description="已抓取商品/新聞數量")
    created_at: datetime = Field(..., description="任務建立時間")
    completed_at: Optional[datetime] = Field(None, description="任務完成時間")
