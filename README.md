# olca-ipc-container

openLCA IPC 伺服器的 Docker Compose 多容器解決方案，包含 openLCA IPC Server 和 Flask API Gateway。該架構確保 openLCA Server 僅在容器內網可見，所有外部請求均透過 Flask 代理處理。

## 📁 專案結構

```
olca-ipc-container/
├── Dockerfile              # openLCA IPC Server 多階段建置
├── docker-compose.yml      # 兩個服務的編排定義
├── pom.xml                 # Maven 依賴管理（openLCA IPC）
├── run.sh                  # openLCA 啟動腳本
├── Flask/
│   ├── Dockerfile          # Flask API Gateway 容器定義
│   ├── my_flask1.py        # Flask 應用程式
│   └── requirements.txt     # Python 依賴
├── TestPlatForm/           # 本地開發資料夾
│   └── databases/
│       └── mainTestDatabase/  # openLCA 資料庫
└── FindTest.js             # 資料掛載驗證工具
```

## 🚀 快速啟動

### 前置條件
- Docker 和 Docker Compose 已安裝
- `TestPlatForm/databases/mainTestDatabase` 資料庫存在
- 在 Windows 上，確保 Docker Desktop 已授權共用磁碟機（D: 驅動器）

### 啟動步驟

在 `olca-ipc-container` 目錄執行：

```powershell
docker-compose build
docker-compose up -d
```

## 🏗️ 架構說明

### openLCA IPC Server 容器（`olca` 服務）

**建置流程（多階段）：**
1. **Maven 階段**：編譯並打包 openLCA IPC 依賴
2. **Native 階段**：使用官方 `ghcr.io/greendelta/gdt-server-native` 映像取得本機計算庫
3. **最終階段**：基於 OpenJDK 21 JRE，僅包含必要的依賴和啟動腳本

**設定：**
- **容器名稱**：`olca-ipc`
- **內部埠**：`8080`（openLCA IPC Server）
- **對外映射**：主機埠 `5011` → 容器埠 `8080`
- **資料掛載**：本地 `./TestPlatForm` → 容器 `/app/data`
- **啟動命令**：`-db mainTestDatabase`（使用指定資料庫）
- **重啟策略**：`unless-stopped`

### Flask API Gateway 容器（`flask` 服務）

**容器配置：**
- **基礎映像**：Python 3.11 slim
- **容器名稱**：`olca-flask`
- **對外埠**：主機埠 `5010` → 容器埠 `5000`
- **依賴**：Flask、gunicorn、olca-ipc、olca-schema
- **啟動指令**：Gunicorn（1 個 worker 進程）
- **重啟策略**：`unless-stopped`

**環境變數（與 openLCA Server 連接）：**
- `OLCA_IPC_HOST=olca`（Docker Compose 服務名稱）
- `OLCA_IPC_PORT=8080`
- `IPC_CONNECT_RETRIES=20`（重試次數）
- `IPC_CONNECT_DELAY=1.0`（重試間隔，秒）

**Volume 掛載：**
- `./flask/my_flask1.py:/app/my_flask1.py:ro`（唯讀掛載，便於開發更新）

## 📝 Flask 應用程式說明

### 功能概述

Flask 應用程式提供單一計算端點 `/calculate`，支援以下工作流程：

1. 接收 POST 請求的 JSON 參數
2. 透過 IPC 連接池連接 openLCA Server
3. 根據參數名稱動態查詢目標產品系統和影響評估方法
4. 設定參數並執行計算
5. 篩選 GWP（溫室氣體潛勢）相關的影響類別並回傳

### 核心程式邏輯

```python
def create_ipc_client():
    """建立帶有重試機制的 IPC 連線"""
    # 固定連接到 olca:8080（Docker 內部網路）
    # 支援設定環境變數控制重試行為
    # 失敗會拋出例外，由呼叫方處理

def calculate_openlca(distance, factor, load, amount):
    """執行計算流程"""
    # 1. 按名稱查詢模型（"廚餘處理量" ProductSystem）
    # 2. 按名稱查詢影響評估方法（"IPCC 2021 AR6"）
    # 3. 取得模型的所有參數
    # 4. 建立計算設定並設定參數值
    # 5. 執行計算，等待完成，取得總影響值
    # 6. 篩選並回傳 GWP 相關類別
```

### API 端點

#### POST `/calculate`

**請求格式：**
```json
{
  "distance": 10,
  "factor": 1.2,
  "load": 100,
  "amount": 1
}
```

**成功回應（200）：**
```json
{
  "status": "ok",
  "inputs": {
    "distance": 10,
    "factor": 1.2,
    "load": 100,
    "amount": 1
  },
  "impacts": [
    {
      "category": "GWP 100-year",
      "value": 120.5,
      "unit": "kg CO2-Eq"
    }
  ]
}
```

**錯誤回應（400/500）：**
```json
{
  "status": "error",
  "message": "缺少參數 / openLCA 連線失敗"
}
```

## 🧪 測試與驗證

### 1. 確認容器狀態

```powershell
docker-compose ps
docker-compose logs -f olca
docker-compose logs -f flask
```

### 2. 驗證資料掛載

```powershell
# 宿主機檢查資料庫是否存在
node FindTest.js

# 或在容器內列出掛載目錄
docker-compose exec olca /bin/sh -c 'ls -la /app/data'
```

### 3. 測試 openLCA IPC Server（直接）

```powershell
curl -d '{"jsonrpc":"2.0","id":1,"method":"data/get/descriptors","params":{"@type":"ProductSystem"}}' `
  -H "Content-Type: application/json" `
  -X POST http://localhost:5011
```

### 4. 測試 Flask API Gateway

```powershell
curl -X POST http://localhost:5010/calculate `
  -H "Content-Type: application/json" `
  -d '{"distance":10,"factor":1.2,"load":100,"amount":1}'
```

## 🔧 開發與維護

### 修改 Flask 程式碼

由於 `docker-compose.yml` 已配置唯讀掛載 `./flask/my_flask1.py:/app/my_flask1.py:ro`，修改本地檔案後，容器會自動更新（Gunicorn 監控檔案變更）。

### 升級 openLCA 依賴

修改 `pom.xml` 中的 `<version>` 標籤，然後重建：

```powershell
docker-compose build --no-cache olca
docker-compose up -d olca
```

### 使用不同的資料庫

修改 `docker-compose.yml` 的 `olca` 服務 `command` 欄位：

```yaml
command: -db 你的資料庫名稱
```

然後重啟：

```powershell
docker-compose up -d olca
```

## ⚠️ 常見問題與解決方案

### openLCA Server 啟動失敗

**症狀：** `Cannot invoke "java.sql.Connection.createStatement()" because "con" is null`

**原因：** 資料庫資料夾不可寫、不完整或權限不足

**解決：**
1. 確認 `TestPlatForm/databases/mainTestDatabase` 存在且完整
2. 檢查 `docker-compose.yml` 中的 volume 掛載權限（不應為 `:ro`）
3. Windows 上確保 Docker Desktop 已授權磁碟機共用

### Flask 無法連接 openLCA

**症狀：** Flask 容器日誌顯示連線失敗（20 次重試後）

**原因：** openLCA Server 尚未啟動或內部通訊失敗

**解決：**
1. 檢查 openLCA 容器日誌：`docker-compose logs olca`
2. 確認 openLCA 已成功監聽 8080 埠
3. 檢查 Flask 環境變數是否正確設定（`OLCA_IPC_HOST=olca`）
4. 增加 `IPC_CONNECT_RETRIES` 或 `IPC_CONNECT_DELAY` 的值

### SLF4J 日誌警告

**症狀：** 容器日誌中出現 SLF4J binding 警告

**處理：** 這些是無害的資訊性警告，不影響伺服器運作

### Windows 權限問題

**症狀：** 容器無法存取掛載的卷

**解決：** 
1. 確保 Docker Desktop 中已啟用 D: 驅動器共用（Settings → Resources → File Sharing）
2. 使用正斜線（`D:/openLCA/...`）而非反斜線在 `docker-compose.yml` 中

## 🛑 停止與清理

```powershell
# 停止所有容器（保留卷）
docker-compose stop

# 停止並移除容器（保留卷）
docker-compose down

# 完全清理（包含卷）
docker-compose down -v
```

## 📚 參考資源

- [openLCA JSON-RPC API 文件](https://greendelta.github.io/openLCA-ApiDoc/ipc/)
- [olca-ipc Python 套件](https://github.com/GreenDelta/olca-ipc.py)
- [olca-schema Python 套件](https://github.com/GreenDelta/olca-schema.py)
- [Docker Compose 文件](https://docs.docker.com/compose/)
