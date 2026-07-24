import json
from typing import List, Any
from datetime import datetime, timedelta
from sqlmodel import Session, select, delete
from app.database import ScrapedResult, Job


class ResultRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_results(self, job_id: str, items: List[Any]):
        """批次儲存標準化 JSON 結果到資料庫中"""
        db_results = []
        for item in items:
            # 轉換 item (Pydantic model 或 dict) 為 JSON 字串
            if hasattr(item, "model_dump_json"):
                data_str = item.model_dump_json()
            elif hasattr(item, "json"):
                data_str = item.json()
            else:
                data_str = json.dumps(item, default=str)
                
            db_results.append(ScrapedResult(
                job_id=job_id,
                data_json=data_str,
                created_at=datetime.utcnow()
            ))
            
        self.db.add_all(db_results)
        self.db.commit()

    def get_results_by_job(self, job_id: str) -> List[dict]:
        """讀取某個 Job 的全部資料，並反序列化為 dict 陣列"""
        statement = select(ScrapedResult).where(ScrapedResult.job_id == job_id)
        results = self.db.exec(statement).all()
        return [json.loads(r.data_json) for r in results]

    def clear_expired_results(self, hours_to_keep: int = 12):
        """自動清理 12 小時前的暫存結果與任務紀錄，維持資料庫極輕量"""
        expiration_date = datetime.utcnow() - timedelta(hours=hours_to_keep)
        
        # 1. 刪除過期的 scraped_results
        stmt_results = delete(ScrapedResult).where(ScrapedResult.created_at < expiration_date)
        self.db.exec(stmt_results)
        
        # 2. 刪除過期的 jobs
        stmt_jobs = delete(Job).where(Job.created_at < expiration_date)
        self.db.exec(stmt_jobs)
        
        self.db.commit()
