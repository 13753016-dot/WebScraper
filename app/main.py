from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.database import init_db
from app.api.scrape import router as scrape_router
from app.api.jobs import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在應用啟動時建立 SQLite 資料庫與表格
    init_db()
    yield
    # 應用關閉時的清理操作（目前不需要額外操作）


app = FastAPI(
    title="3C 市場情報資料蒐集系統 API",
    description="負責多平台（PChome、momo、原價屋）的 Stateless-ish 資料爬取、標準化 JSON 輸出與短期任務暫存服務。",
    version="1.0.0",
    lifespan=lifespan
)

# 註冊路由
app.include_router(scrape_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root_redirect():
    """根目錄預設導向 Swagger API 文件頁面"""
    return RedirectResponse(url="/docs")
