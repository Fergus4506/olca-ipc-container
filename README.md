# olca-ipc-container

This repository contains an example for packaging an openLCA v2 IPC server in a Docker container. This is done in a multi-stage build where the final image only contains the necessary resources to run the server. To build the image, just run:

```bash
cd olca-ipc-container
docker build -t olca-ipc-server .
```

This will package the IPC server and native calculation libraries in an image tagged as `olca-ipc-server`. The following example will start a container from that image:

```bash
docker run \
  -p 3000:8080 \
  -v $HOME/openLCA-data-1.4:/app/data \
  --rm -d olca-ipc-server \
  -db example --readonly
```


**使用 Flask 作為對外 API 閘道（建議：以 Docker Compose 運行兩個容器）**

範例架構：一個容器運行 openLCA IPC Server（內部埠 8080/8081），另一個容器運行 Flask gateway（對外埠 5000）。這樣能確保外部只能存取 Flask，Flask 再透過容器內網呼叫 openLCA。

快速啟動（在 `olca-ipc-container` 目錄）：

```bash
docker-compose build
docker-compose up -d
```

- Flask 對外 API 在 `http://localhost:5000`（例如：`POST /calculate`）。
- openLCA IPC server 僅在容器內網可見，未對主機直接公開埠（若需要公開可修改 `docker-compose.yml`）。

容器內 Flask 會使用下列環境變數來連接 openLCA IPC Server：
- `OLCA_IPC_HOST`（預設 `olca`，在 compose 中為服務名稱）
- `OLCA_IPC_PORT`（預設 `8080`，可視 openLCA Server 設定調整）
- `IPC_CONNECT_RETRIES`、`IPC_CONNECT_DELAY`（連線重試行為）

維護與修改建議：
- 在開發階段，使用 `docker-compose` 的 volume 將本地 `my_flask1.py` 掛載到容器，修改會立即生效（範例 compose 已示範）。
- 若要升級 openLCA 或 native libs，修改 `pom.xml` 或 native 映像來源，重新 `docker build`。
- 若要把 Flask 放到獨立 repo 或 service，請確保環境變數與內部網路名稱相同。

疑難排解：
- 若 Flask 無法連上 IPC，先檢查 `olca` 服務日誌：`docker-compose logs olca`，確定 IPC Server 已啟動並監聽的埠號。
- 如需測試 openLCA API，容器內可以用 `curl` 對 `http://olca:8080` 發送 JSON-RPC 呼叫。

This will start the server in the container at port `8080` using `/app/data` as data folder. The data folder is mapped to the default openLCA workspace in the example and the port to `3000` of the host. More options can be passed in to the container after the image name (`olca-ipc-server`). In the example, the database is set to `example` (so `~/openLCA-data-1.4/databases/example` would be the full path of the database) and the server is run in `readonly` mode.

The server implements the JSON-RPC protocol of the openLCA API (see https://greendelta.github.io/openLCA-ApiDoc/ipc/). Here is an example `curl` command to list the product systems via the API:

```bash
curl -d '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "data/get/descriptors",
  "params": { "@type": "ProductSystem" }}'\
  -H "Content-Type: application/json"\
  -X POST http://localhost:3000
```

**測試說明**

- **建置映像**：在 `olca-ipc-container` 目錄執行：

```powershell
docker build -t olca-ipc-server .
```

- **以 Docker Compose 啟動（推薦）**：

```powershell
docker-compose build
docker-compose up -d
```

- **直接測試 openLCA IPC（主機對容器埠 3000 映射）**：

```powershell
curl -d '{"jsonrpc":"2.0","id":1,"method":"data/get/descriptors","params":{"@type":"ProductSystem"}}' -H "Content-Type: application/json" -X POST http://localhost:3000
```

- **測試 Flask gateway（若使用 compose 範例）**：

```powershell
curl -X POST http://localhost:5000/calculate -H "Content-Type: application/json" -d '{"distance":10,"factor":1.2,"load":100,"amount":1}'
```

- **檢查容器狀態與日誌**：

```powershell
docker-compose ps
docker-compose logs -f olca
docker-compose logs -f flask
```

- **確認資料掛載是否正確（宿主機執行 `FindTest.js`）**：
  - 在 `olca-ipc-container` 目錄執行：

```powershell
node FindTest.js
```

  - 或在容器內列出 `/app/data`：

```powershell
docker-compose exec olca /bin/sh -c 'ls -la /app/data'
```

- **常見錯誤與處理**：
  - `Cannot invoke "java.sql.Connection.createStatement()" because "con" is null`：通常因為資料庫資料夾不可寫或資料目錄不完整。請確認 `TestPlatForm/databases/<dbName>` 存在且 `docker-compose.yml` 的 `volumes` 有給予寫入權限（非 `:ro`）。
  - SLF4J 警告：可忽略（是 logging binding 相關警示），非啟動失敗主因。
  - 權限問題（Windows）：確保 Docker Desktop 已允許共用 `D:` 磁碟，或使用絕對路徑並以正斜線（`D:/openLCA/...`）在 `docker-compose.yml` 中指定。

- **停止與移除**：

```powershell
docker-compose down
```

若測試時仍遇到容器不斷重啟或 DB 無法初始化，請貼上 `docker-compose logs olca --tail=200` 的輸出，我會協助進一步診斷。
