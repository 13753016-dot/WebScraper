from curl_cffi import requests
from bs4 import BeautifulSoup
import sys

url = "https://www.mobile01.com/sitemap.php"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.mobile01.com/"
}

try:
    # impersonate="chrome110" 會使 requests 完美模擬 Chrome 110 的 TLS/HTTP/2 特徵，繞過 Cloudflare 阻擋！
    r = requests.get(url, headers=headers, impersonate="chrome110", timeout=15.0)
    print(f"Status Code: {r.status_code}")
    print(f"Final URL: {r.url}")
    
    if r.status_code != 200:
        print("Failed to bypass CF.")
        sys.exit(1)
        
    soup = BeautifulSoup(r.text, "lxml")
    
    # 尋找 Sitemap 中的大類，通常是有特定 Class 的標題
    # 根據圖片，標題是「手機」並且下面有很多子分類 (Android, BlackBerry, Google...)
    # 我們看看大分類標題在 HTML 中的結構
    print("\n--- Testing Sitemap DOM parsing ---")
    
    # 列出部分含有熱門字眼的 h2/h3/h4 或 div
    for h in soup.find_all(["h2", "h3", "h4", "div", "span"]):
        txt = h.get_text(strip=True)
        if txt in ["手機", "相機", "筆電", "電腦", "蘋果"]:
            print(f"找到大類標籤: {h.name}, class: {h.get('class')}, text: {txt}")
            # 尋找該大類下面的子分類連結
            # 通常在它的 parent 或是下一個 sibling
            parent = h.parent
            print(f"  Parent: {parent.name}, class: {parent.get('class')}")
            # 印出這個大類前後一部分的 HTML 看結構
            print(f"  Snippet: {str(parent)[:500]}")
            
except Exception as e:
    print(f"Error: {e}")
