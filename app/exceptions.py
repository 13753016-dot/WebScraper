class ScraperError(Exception):
    """所有爬蟲相關異常的基類"""
    def __init__(self, message: str, platform: str = None):
        super().__init__(message)
        self.message = message
        self.platform = platform


class RateLimitExceeded(ScraperError):
    """觸發平台速率限制 (HTTP 429) 或併發限制"""
    pass


class ScrapeFailed(ScraperError):
    """爬取任務最終失敗（例如連線超時重試失敗，或頁面結構變更無法解析）"""
    pass


class JobNotFoundError(Exception):
    """查詢的 Job ID 不存在"""
    def __init__(self, job_id: str):
        super().__init__(f"Job {job_id} not found")
        self.job_id = job_id
