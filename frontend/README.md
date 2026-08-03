# Ponte Frontend

這是 Ponte 的零 build dependency 前端。它只負責畫面、文字輸入、瀏覽器語音能力及 middleware HTTP client；不直接呼叫 MCP 或 mock backend。

## 啟動前端

```bash
python3 -m frontend.server --host 127.0.0.1 --port 5173
```

開啟 [http://127.0.0.1:5173](http://127.0.0.1:5173)。前端預設連接 `http://127.0.0.1:8090` 的 middleware；middleware 尚未啟動時，頁面仍然可以載入，並會顯示可理解的連線錯誤，文字輸入仍保持可用。

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
- Middleware 返回的 task steps、tool events、服務資料、選項和確認操作會在畫面上顯示。
- middleware 連線錯誤不會清空既有對話或停用文字輸入。

## 驗證

```bash
python3 -m unittest tests.test_frontend_static -v
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
```

Middleware 的實際整合驗證留待 `docs/superpowers/plans/2026-08-03-ponte-middleware.md` 執行時進行。
