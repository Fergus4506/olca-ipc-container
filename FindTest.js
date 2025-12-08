// 引入 fetch (如果在 Node.js 環境需要這行，但在較新版本 Node 如 v20 可省略)
// import fetch from 'node-fetch'; 

async function run() {
    // 定義第一個請求 (Project) - 尚未發送，只是 Promise
    const reqProject = fetch("http://localhost:3000", {
        method: "POST",
        body: JSON.stringify({
            jsonrpc: "2.0",
            id: 1,
            method: "data/get",
            params: { "@type": "Project", "@id": "0a36b0b4-6836-4b4e-a275-a51b7f9f2633" }
        })
    });

    // 定義第二個請求 (ProductSystem)
    const reqSystem = fetch("http://localhost:3000", {
        method: "POST",
        body: JSON.stringify({
            jsonrpc: "2.0",
            id: 2,
            method: "data/get",
            params: { "@type": "ProductSystem", "@id": "724bff37-cc16-4af4-a059-a1948f61af93" }
        })
    });

    try {
        // 關鍵：使用 Promise.all 同時等待兩個請求回來
        console.log("正在發送查詢...");
        const [resp1, resp2] = await Promise.all([reqProject, reqSystem]);

        // 分別讀取結果 (解決 Body already read 問題：每個 resp 只讀一次)
        const resultProject = await resp1.json();
        const resultSystem = await resp2.json();

        // 顯示結果
        console.log("------------------------------------------------");
        if (resultProject.error) {
            console.log("Project 查詢失敗:", resultProject.error);
        } else {
            console.log("Project 結果:", resultProject.result ? "找到資料" : "無資料");
             console.log(resultProject.result); // 想看詳細內容就把這行打開
        }

        console.log("------------------------------------------------");
        if (resultSystem.error) {
            console.log("ProductSystem 查詢失敗:", resultSystem.error);
        } else {
            console.log("ProductSystem 結果:", resultSystem.result ? "找到資料" : "無資料");
             console.log(resultSystem.result); // 想看詳細內容就把這行打開
        }

    } catch (error) {
        console.error("連線發生錯誤:", error);
    }
}

run();