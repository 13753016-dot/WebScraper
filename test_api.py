import httpx
import time
import json

BASE_URL = "http://127.0.0.1:8000/api/v1"


def test_sync_pchome():
    print("\n--- 1. 測試同步爬取 PChome 筆電 ---")
    payload = {
        "platform": "pchome",
        "category": "laptop",
        "keyword": "ASUS Zenbook",
        "limit": 25
    }
    try:
        response = httpx.post(f"{BASE_URL}/scrape/sync", json=payload, timeout=20.0)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"成功取得商品筆數: {len(data)}")
            if data:
                print("第一筆商品 JSON 範例:")
                print(json.dumps(data[0], indent=2, ensure_ascii=False))
        else:
            print(f"錯誤回應: {response.text}")
    except Exception as e:
        print(f"測試異常: {str(e)}")


def test_async_coolpc_news():
    print("\n--- 2. 測試非同步任務爬取原價屋新聞 ---")
    payload = {
        "platform": "coolpc",
        "category": "news",
        "limit": 15
    }
    try:
        # A. 建立任務
        create_resp = httpx.post(f"{BASE_URL}/jobs", json=payload, timeout=10.0)
        print(f"建立任務 Status: {create_resp.status_code}")
        if create_resp.status_code != 202:
            print(f"建立任務失敗: {create_resp.text}")
            return
            
        job_data = create_resp.json()
        job_id = job_data["job_id"]
        print(f"任務建立成功, Job ID: {job_id}")
        
        # B. 輪詢任務狀態
        for i in range(15):
            time.sleep(2)
            status_resp = httpx.get(f"{BASE_URL}/jobs/{job_id}", timeout=5.0)
            status_data = status_resp.json()
            print(f"輪詢第 {i+1} 次 - 狀態: {status_data['status']}, 進度: {status_data['progress']}")
            
            if status_data["status"] == "completed":
                print("任務已完成！")
                break
            elif status_data["status"] == "failed":
                print(f"任務失敗: {status_data['error_message']}")
                return
        else:
            print("超時！任務未在預期時間內完成。")
            return
            
        # C. 取得結果
        results_resp = httpx.get(f"{BASE_URL}/jobs/{job_id}/results", timeout=5.0)
        results = results_resp.json()
        print(f"取得暫存結果筆數: {len(results)}")
        if results:
            print("第一筆新聞 JSON 範例:")
            print(json.dumps(results[0], indent=2, ensure_ascii=False))
            
    except Exception as e:
        print(f"測試異常: {str(e)}")


def test_sync_momo():
    print("\n--- 3. 測試同步爬取 momo 筆電 ---")
    payload = {
        "platform": "momo",
        "category": "laptop",
        "limit": 10
    }
    try:
        response = httpx.post(f"{BASE_URL}/scrape/sync", json=payload, timeout=20.0)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"成功取得商品筆數: {len(data)}")
            if data:
                print("第一筆商品 JSON 範例:")
                print(json.dumps(data[0], indent=2, ensure_ascii=False))
        else:
            print(f"錯誤回應: {response.text}")
    except Exception as e:
        print(f"測試異常: {str(e)}")


def test_sync_mobile01():
    print("\n--- 4. 測試同步爬取 Mobile01 蘋果板塊 ---")
    payload = {
        "platform": "mobile01",
        "category": "apple",
        "limit": 5
    }
    try:
        # 二級爬取一樓內文耗時較長，超時放寬至 30.0 秒
        response = httpx.post(f"{BASE_URL}/scrape/sync", json=payload, timeout=30.0)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"成功取得貼文筆數: {len(data)}")
            if data:
                print("第一筆貼文 JSON 範例:")
                print(json.dumps(data[0], indent=2, ensure_ascii=False))
        else:
            print(f"錯誤回應: {response.text}")
    except Exception as e:
        print(f"測試異常: {str(e)}")


if __name__ == "__main__":
    # 給 FastAPI 1-2 秒啟動時間
    time.sleep(2)
    test_sync_pchome()
    test_async_coolpc_news()
    test_sync_momo()
    test_sync_mobile01()
