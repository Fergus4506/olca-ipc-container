# call_flask.py
import requests

url = "http://localhost:5010/calculate"  # 確認 Flask 正在跑
payload = {
    # 若你已在 Flask 把 Product System 與 Method 固定，這裡就只送四個參數
    "distance": 10,
    "factor": 0,
    "load": 5,
    "amount": 100
    # 若沒有固定，請加入 product_system_id 與 impact_method_id
}

res = requests.post(url, json=payload)
print("HTTP status:", res.status_code)
print(res.json())
