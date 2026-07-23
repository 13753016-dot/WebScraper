from typing import Optional
from datetime import datetime
from sqlmodel import Session, select
from app.database import Job


class JobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_job(self, job_id: str, platform: str, category: str, keyword: Optional[str] = None) -> Job:
        job = Job(
            job_id=job_id,
            platform=platform,
            category=category,
            keyword=keyword,
            status="pending",
            progress="0%",
            created_at=datetime.utcnow()
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        statement = select(Job).where(Job.job_id == job_id)
        return self.db.exec(statement).first()

    def update_job_status(
        self, 
        job_id: str, 
        status: str, 
        progress: str = None, 
        error_message: str = None, 
        result_count: int = None
    ) -> Optional[Job]:
        job = self.get_job(job_id)
        if not job:
            return None
        
        job.status = status
        if progress is not None:
            job.progress = progress
        if error_message is not None:
            job.error_message = error_message
        if result_count is not None:
            job.result_count = result_count
            
        if status in ("completed", "failed"):
            job.completed_at = datetime.utcnow()
            
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job
