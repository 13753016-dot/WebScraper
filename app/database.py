import os
from datetime import datetime
from typing import Optional, Generator
from sqlmodel import Field, SQLModel, create_engine, Session

# 取得專案根目錄絕對路徑，固定 SQLite 資料庫檔案位置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(BASE_DIR, "market_info.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# 建立 SQLite Engine
# connect_args={"check_same_thread": False} 適用於 SQLite 的多執行緒異步呼叫
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False},
    echo=False
)


# 定義 Job 資料表
class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    
    job_id: str = Field(primary_key=True, index=True)
    platform: str
    category: str
    keyword: Optional[str] = None
    status: str = "pending"
    progress: str = "0%"
    error_message: Optional[str] = None
    result_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


# 定義 ScrapedResult 資料表 (暫存 JSON 結果)
class ScrapedResult(SQLModel, table=True):
    __tablename__ = "scraped_results"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    data_json: str = Field(description="JSON 序列化後的標準資料")
    created_at: datetime = Field(default_factory=datetime.utcnow)


def init_db():
    """初始化資料庫與建立資料表"""
    SQLModel.metadata.create_all(engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依賴注入 Session 產生器"""
    with Session(engine) as session:
        yield session
