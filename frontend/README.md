# Ponte Frontend

這是 Ponte 的零 build dependency 前端。它只負責畫面、文字輸入、瀏覽器語音能力及 middleware HTTP client；不直接呼叫 MCP 或 mock backend。

## 啟動前端

```bash
python3 -m frontend.server --host 127.0.0.1 --port 5173
```

開啟 [http://127.0.0.1:5173](http://127.0.0.1:5173)。前端預設連接 `http://127.0.0.1:8090` 的 middleware；middleware 尚未啟動時，頁面仍然可以載入，並會顯示可理解的連線錯誤，文字輸入仍保持可用。

完整 stack runner 會列出可直接開啟的 URL；若 middleware 使用其他 port，也可以使用 query override：

```text
http://127.0.0.1:15173/?middleware=http://127.0.0.1:18090
```

如需更換 middleware 位置，可在載入 `app.js` 前設定：

```html
<script>
  window.PONTE_MIDDLEWARE_URL = "http://127.0.0.1:8090";
</script>
```

## 已實現的互動

- 大字、高對比、適合長者閱讀的對話與服務工作區。
- 文字輸入及快捷需求按鈕。
- 支援 `SpeechRecognition` / `webkitSpeechRecognition` 時，以 `zh-HK` 取得粵語 transcript；transcript 會先回填文字框，使用者按送出後才傳給 middleware。
- 支援 `speechSynthesis` 時朗讀助手回覆，並提供停止朗讀控制。
- Middleware 返回的服務進度、可讀的服務／日期／時間／地點摘要、選項和確認操作會在畫面上顯示；API 工具名稱、請求編號和原始 backend 欄位不會展示給一般使用者。
- 可用文字輸入測試自然語言 workflow：`我想查詢自己的醫療預約` 是只讀查詢，只展示 `medical.get_my_appointments` 的結果；`我想預約醫療服務` 會讓使用者選擇服務和日期範圍，展示 `medical.search_appointment_slots` 返回的可預約時段，再經確認建立 mock 預約。預約後再次輸入前一個查詢即可讀回記錄；另外也可測試 `我想查現金分享計劃` 和 `我想找長者文娛活動`。
- 開發者整合測試仍保留固定 MCP tool 的 `confirm_tool` 確認 action 和既有 `sendAction` contract；這些技術細節不會出現在一般服務工作區。
- middleware 連線錯誤不會清空既有對話或停用文字輸入。

## 驗證

```bash
python3 -m unittest tests.test_frontend_static -v
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
```

完整驗收流程請參考 repo 根目錄的 `README.md`：輸入上述任一需求並送出，畫面應顯示 middleware 已連線、對應進度，以及可讀的服務資料摘要。
