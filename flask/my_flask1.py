from flask import Flask, request, jsonify
import os
import time
import olca_schema as o
import olca_ipc as ipc
from flask_cors import CORS  # <--- 新增這個

app = Flask(__name__)
CORS(app)  # <--- 啟用 CORS，允許所有來源呼叫 (測試階段這樣做最方便)

# --- 設定區域 ---
# # 確保 Host 預設值與 docker-compose service name 一致
# OLCA_IPC_HOST = os.getenv("OLCA_IPC_HOST", "olca") 
# OLCA_IPC_PORT = int(os.getenv("OLCA_IPC_PORT", "8080"))

# OpenLCA 啟動較慢，建議增加重試總時間 (此處約 60秒)
IPC_CONNECT_RETRIES = int(os.getenv("IPC_CONNECT_RETRIES", "30"))
IPC_CONNECT_DELAY = float(os.getenv("IPC_CONNECT_DELAY", "2.0"))

# 固定 UUID
# PRODUCT_SYSTEM_ID = os.getenv("PRODUCT_SYSTEM_ID", "724bff37-cc16-4af4-a059-a1948f61af93")
# IMPACT_METHOD_ID = os.getenv("IMPACT_METHOD_ID", "fb0bfc55-63f1-4c38-8167-25be95473fee")

def create_ipc_client():
    """建立 IPC 連線，包含重試機制"""
    # print(f"準備連線至 OpenLCA Server: {OLCA_IPC_HOST}:{OLCA_IPC_PORT}")
    
    last_exc = None
    for attempt in range(1, IPC_CONNECT_RETRIES + 1):
        try:
            # 強制指定 host，確保在 Docker 網路內能找到對方
            client = ipc.Client(3000)
            client.url = f"http://olca:8080"
            
            # 測試連線是否真的通了 (送一個輕量請求)
            # 嘗試取得一個簡單物件，如果失敗代表 server 可能還在啟動中
            # client.get(o.ImpactMethod, IMPACT_METHOD_ID)
            
            print(f"成功連線至 OpenLCA (第 {attempt} 次嘗試)")
            return client
        except Exception as e:
            print(f"連線失敗 (第 {attempt}/{IPC_CONNECT_RETRIES} 次): {e}")
            last_exc = e
            time.sleep(IPC_CONNECT_DELAY)
            
    print("錯誤：無法連接到 OpenLCA Server，請檢查容器日誌。")
    raise last_exc

# 初始化 Client (注意：如果 OpenLCA 還沒好，這裡會卡住直到超時)
# 在生產環境通常建議由第一個 Request 觸發連線，或使用 Before_first_request
# 但為了簡單起見，我們維持在全域初始化
client = create_ipc_client()


# # 固定模型與影響評估方法 UUID（可改為從環境變數或設定檔讀取）
# PRODUCT_SYSTEM_ID = os.getenv("PRODUCT_SYSTEM_ID", "724bff37-cc16-4af4-a059-a1948f61af93")
# IMPACT_METHOD_ID = os.getenv("IMPACT_METHOD_ID", "fb0bfc55-63f1-4c38-8167-25be95473fee")

# 將原本的計算流程封裝成函式
def calculate_openlca(distance, factor, load, amount):
    # 取得模型
    model = client.get(o.ProductSystem, name="廚餘處理量")
    method = client.get(o.ImpactMethod, name="IPCC 2021 AR6")

    # 取得參數
    parameters = client.get_parameters(o.ProductSystem, model.id)

    # 建立計算設定
    setup = o.CalculationSetup(
        target=model,
        amount=amount,
        impact_method=method,
        parameters=[
            o.ParameterRedef(name=parameters[0].name, value=factor, context=parameters[0].context),
            o.ParameterRedef(name=parameters[1].name, value=distance, context=parameters[1].context),
            o.ParameterRedef(name=parameters[2].name, value=load, context=parameters[2].context),
        ],
    )

    # 計算
    result = client.calculate(setup)
    result.wait_until_ready()
    impacts = result.get_total_impacts()
    result.dispose()

    # 篩選 GWP
    gwp_impacts = []
    for i in impacts:
        if "GWP" in i.impact_category.name:
            gwp_impacts.append({
                "category": i.impact_category.name,
                "value": i.amount,
                "unit": i.impact_category.ref_unit
            })
    return gwp_impacts

# Flask API
@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.json
    distance = data.get("distance")
    factor = data.get("factor")
    load = data.get("load")
    amount = data.get("amount")

    if None in (distance, factor, load, amount):
        return jsonify({"status": "error", "message": "缺少參數"}), 400

    try:
        impacts = calculate_openlca(distance, factor, load, amount)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({
        "status": "ok",
        "inputs": {"distance": distance, "factor": factor, "load": load, "amount": amount},
        "impacts": impacts
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
