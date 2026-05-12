import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

# 加载保险箱
load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# 指向合约模拟盘地址 (Demo Trading)
BASE_URL = "https://testnet.binancefuture.com"
def check_demo_balance():
    print("🔐 Hermes AI 正在接入合约模拟金库...")
    print("-" * 40)
    
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    
    url = f"{BASE_URL}/fapi/v2/account?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}

    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if response.status_code == 200:
            print("✅ 成功连接！模拟盘资产：")
            # 过滤出有余额的资产（模拟盘通常会有很多 USDT）
            assets = [a for a in data.get('assets', []) if float(a['walletBalance']) > 0]
            for a in assets:
                print(f"💰 {a['asset']}: {a['walletBalance']}")
        else:
            print(f"❌ 报错: {data.get('msg', '未知错误')}")
    except Exception as e:
        print(f"📡 连接异常: {e}")

if __name__ == "__main__":
    check_demo_balance()