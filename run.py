import uvicorn

if __name__ == "__main__":
    print("啟動 3C 市場情報自動化資料蒐集系統 API...")
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
