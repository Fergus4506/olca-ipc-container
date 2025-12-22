from flask import Flask, request, jsonify, send_file
import os
import time
import olca_schema as o
import olca_ipc as ipc
from flask_cors import CORS 

# 讀取 .env（若你在專案根目錄放置 .env，會自動載入）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv 尚未安裝，環境變數仍可從系統取得
    pass
# Supabase client (optional):
# - 如果您想要啟用儲存功能，請安裝 supabase 套件並設定 SUPABASE_URL / SUPABASE_KEY / SUPABASE_TABLE。
# - 程式會嘗試載入 supabase，若載入失敗則不會中斷主流程（僅會停用儲存功能）。
try:
    from supabase import create_client, Client as SupabaseClient
except Exception:
    create_client = None
    SupabaseClient = None
    print('Warning: supabase not installed; Supabase integration disabled. Install with: pip install supabase')

app = Flask(__name__)
CORS(app)  # <--- 啟用 CORS，允許所有來源呼叫 (測試階段這樣做最方便)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_HTML_PATH = os.path.join(BASE_DIR, "test_compare.html")

# --- 設定區域 ---
# # 確保 Host 預設值與 docker-compose service name 一致
# OLCA_IPC_HOST = os.getenv("OLCA_IPC_HOST", "olca") 
# OLCA_IPC_PORT = int(os.getenv("OLCA_IPC_PORT", "8080"))

# OpenLCA 啟動較慢，建議增加重試總時間 (此處約 60秒)
IPC_CONNECT_RETRIES = int(os.getenv("IPC_CONNECT_RETRIES", "30"))
IPC_CONNECT_DELAY = float(os.getenv("IPC_CONNECT_DELAY", "2.0"))

# Supabase configuration - customize: set SUPABASE_URL, SUPABASE_KEY, SUPABASE_TABLE_*
# 安全性建議：在本機/伺服器上透過環境變數管理憑證，不要直接把金鑰寫在原始碼中。
# 支援讀取前端 .env 樣式的變數（REACT_APP_*），方便開發環境復用設定
SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("REACT_APP_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("REACT_APP_SUPABASE_ANON_KEY", "")
# print(f"Supabase URL: {SUPABASE_URL[:20]}... Key: {'set' if SUPABASE_KEY else 'not set'}")
# 預設的 table 名稱（可由環境變數覆寫）
SUPABASE_TABLE_IPCC = os.environ.get("SUPABASE_TABLE_IPCC", "IPCC 2021 AR6")
SUPABASE_TABLE_CO2DISTANCE = os.environ.get("SUPABASE_TABLE_CO2DISTANCE", "Co2ByDistance")
SUPABASE_TABLE_CO2OILUSE = os.environ.get("SUPABASE_TABLE_CO2OILUSE", "Co2ByOiluse")
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "")  # 舊的兼容變數


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
method = client.get(o.ImpactMethod, name="IPCC 2021 AR6")

# 如果 supabase client 已載入且 URL/KEY 有設定，則建立連線物件；否則將 supabase 設為 None（停用儲存功能）。
if create_client and SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    if create_client:
        print("Supabase not configured (missing URL/KEY). Set environment variables SUPABASE_URL/REACT_APP_SUPABASE_URL and SUPABASE_KEY/REACT_APP_SUPABASE_ANON_KEY.")
    else:
        print("Supabase client unavailable (package missing).")




def save_to_supabase(inputs, impacts, extra=None):
    """
    先將 impacts 儲存到 IPCC 的 table（回傳其 id），再將一筆 Co2 表的資料插入並把 IPCC 的 id 放到 `CarbonEmissionID` 欄位。

    流程：
    1. 檢查 supabase 是否可用
    2. 將 impacts 等資訊序列化後插入到 IPCC table（SUPABASE_TABLE_IPCC）並抓取回傳的 id
    3. 根據 extra['model'] 選擇 Co2 表（Co2ByDistance 或 Co2ByOiluse）並插入一筆資料，欄位包含 inputs 的相對欄位與 CarbonEmissionID

    回傳值：
    - dict，包含 status、ipcc_id、co2_id（若已插入）、以及原始回應（供除錯）
    """
    # 檢查 supabase 是否可用（未設定或未安裝會返回 disabled）
    if not supabase:
        return {"status": "disabled", "message": "Supabase not configured"}
    

    # 1) Insert into IPCC table
    ipcc_payload = impacts.copy()

    print("Inserting IPCC payload:", ipcc_payload)

    try:
        # ipcc_res = supabase.table(SUPABASE_TABLE_IPCC).insert(ipcc_payload).execute()
        ipcc_res = supabase.table(SUPABASE_TABLE_IPCC).insert(ipcc_payload).execute()
        print("IPCC insert response:", ipcc_res)
        if isinstance(ipcc_res, dict) and ipcc_res.get('error'):
            print("IPCC insert error:", ipcc_res.get('error'))
            return {"status": "error", "message": str(ipcc_res.get('error'))}

        # 取出回傳 id（Supabase 通常回傳 data: [{"id": ...}]）
        ipcc_json = json.loads(ipcc_res.model_dump_json())
        ipcc_data = ipcc_json['data']
        ipcc_id = ipcc_data[0]['id']
        print("Inserted IPCC ID:", ipcc_id)

    except Exception as e:
        print("IPCC insert exception:", e)
        return {"status": "error", "message": f"IPCC insert failed: {e}"}

    # 2) Insert into the corresponding Co2 table
    model_name = extra.get("model") if extra else None

    # Prepare payloads for the two known models
    if model_name == "廚餘處理量":
        table = SUPABASE_TABLE_CO2DISTANCE
        payload = {
            "Distance": inputs.get("distance"),
            "Coefficient": inputs.get("factor"),
            "Load": inputs.get("load"),
            "Amount": inputs.get("amount"),
            "CarbonEmissionID": ipcc_id
        }
    elif model_name == "燃料消耗碳排":
        table = SUPABASE_TABLE_CO2OILUSE
        payload = {
            "Distance": inputs.get("distance"),
            "Coefficient": inputs.get("factor"),
            "Load": inputs.get("load"),
            "Amount": inputs.get("amount"),
            "Oiluse": inputs.get("oilUse"),
            "CarbonEmissionID": ipcc_id
        }

    try:
        co2_res = supabase.table(table).insert(payload).execute()
    except Exception as e:
        print("Co2 insert exception:", e)
        return {"status": "error", "message": f"Co2 insert failed: {e}", "ipcc_id": ipcc_id}




# 將原本的計算流程封裝成函式
def get_co2_by_tkm(distance, factor, load, amount):
    """執行廚餘處理量模型的 LCA 計算並回傳 GWP 類別的影響值列表。

    流程：
    1. 從 openLCA client 取得指定的 ProductSystem 模型（名稱為 "廚餘處理量"）
    2. 取得模型參數與單位（t 為噸）
    3. 使用傳入的 distance/factor/load/amount 設定 CalculationSetup
    4. 呼叫 client.calculate() 執行計算並等待完成
    5. 篩選 impact category 名稱包含 "GWP" 的項目並回傳

    回傳：list of dict，每個 dict 包含 category、value、unit
    """
    # 取得模型
    model = client.get(o.ProductSystem, name="廚餘處理量")
    

    print("Model ID:", model.id)
    print("Method ID:", method.id) 

    # 取得參數
    parameters = client.get_parameters(o.ProductSystem, model.id)
    
    mass_group_descriptor = client.find(o.UnitGroup, "Units of mass")
    mass_group = client.get(o.UnitGroup, mass_group_descriptor.id)
    ton_unit = next((unit for unit in mass_group.units if unit.name == 't'), None)

    # 建立計算設定
    setup = o.CalculationSetup(
        target=model,
        amount=amount,
        unit=ton_unit,
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
        gwp_impacts.append({
            "category": i.impact_category.name,
            "value": i.amount,
            "unit": i.impact_category.ref_unit
        })
    return gwp_impacts

# 將原本的計算流程封裝成函式
def get_co2_by_oil_km(distance, factor, load, amount, oilUse):
    """執行燃料消耗碳排模型的 LCA 計算並回傳 GWP 類別的影響值列表。

    與 get_co2_by_tkm 類似，但此模型需要額外的 oilUse 參數。

    回傳：list of dict，每個 dict 包含 category、value、unit
    """
    # 取得模型
    model = client.get(o.ProductSystem, name="燃料消耗碳排")
    

    print("Model ID:", model.id)
    print("Method ID:", method.id) 

    # 取得參數
    parameters = client.get_parameters(o.ProductSystem, model.id)
    print("Parameters:", [p.name for p in parameters])
    
    mass_group_descriptor = client.find(o.UnitGroup, "Units of mass")
    mass_group = client.get(o.UnitGroup, mass_group_descriptor.id)
    ton_unit = next((unit for unit in mass_group.units if unit.name == 't'), None)

    # 建立計算設定
    setup = o.CalculationSetup(
        target=model,
        amount=amount,
        unit=ton_unit,
        impact_method=method,
        parameters=[
            o.ParameterRedef(name=parameters[0].name, value=factor, context=parameters[0].context),
            o.ParameterRedef(name=parameters[1].name, value=oilUse, context=parameters[1].context),
            o.ParameterRedef(name=parameters[2].name, value=distance, context=parameters[2].context),
            o.ParameterRedef(name=parameters[3].name, value=load, context=parameters[3].context),
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
        gwp_impacts.append({
            "category": i.impact_category.name,
            "value": i.amount,
            "unit": i.impact_category.ref_unit
        })
    return gwp_impacts

# Flask API
@app.route("/calculate/Co2BYTKM", methods=["POST"])
def calculate():
    """API endpoint: /calculate/Co2BYTKM

    - 請求內容 (JSON): { distance, factor, load, amount }
    - 驗證必要參數，呼叫 get_co2_by_tkm 執行計算
    - 嘗試把輸入與結果儲存到 Supabase（若已配置），回傳 db_status 用於檢查儲存狀態
    """
    data = request.json
    distance = data.get("distance")
    factor = data.get("factor")
    load = data.get("load")
    amount = data.get("amount")

    if None in (distance, factor, load, amount):
        return jsonify({"status": "error", "message": "缺少參數"}), 400

    try:
        impacts = get_co2_by_tkm(distance, factor, load, amount)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    inputs = {"distance": distance, "factor": factor, "load": load, "amount": amount}
    supabase_impact = {impact["category"]: impact["value"] for impact in impacts}
    db_result = save_to_supabase(inputs, supabase_impact, extra={"model": "廚餘處理量", "method": method.name if method else None})

    return jsonify({
        "status": "ok",
        "inputs": inputs,
        "impacts": impacts,
        "db_status": db_result
    })

@app.route("/calculate/Co2BYOilKM", methods=["POST"])
def calculate_oil():
    """API endpoint: /calculate/Co2BYOilKM

    - 請求內容 (JSON): { distance, factor, load, oilUse, amount }
    - 驗證必要參數，呼叫 get_co2_by_oil_km 執行計算
    - 嘗試把輸入與結果儲存到 Supabase（若已配置），回傳 db_status 用於檢查儲存狀態
    """
    data = request.json
    distance = data.get("distance")
    factor = data.get("factor")
    load = data.get("load")
    oilUse = data.get("oilUse")
    amount = data.get("amount")

    if None in (distance, factor, load, oilUse, amount):
        return jsonify({"status": "error", "message": "缺少參數"}), 400

    try:
        impacts = get_co2_by_oil_km(distance, factor, load, amount, oilUse)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    inputs = {"distance": distance, "factor": factor, "load": load, "oilUse": oilUse, "amount": amount}
    supabase_impact = {impact["category"]: impact["value"] for impact in impacts}
    db_result = save_to_supabase(inputs, supabase_impact, extra={"model": "燃料消耗碳排", "method": method.name if method else None})

    return jsonify({
        "status": "ok",
        "inputs": inputs,
        "impacts": impacts,
        "db_status": db_result
    })

if __name__ == "__main__":
    # debug=True 會啟用自動重新載入 (code change 後自動重啟)
    app.run(host="0.0.0.0", port=5000, debug=True)
