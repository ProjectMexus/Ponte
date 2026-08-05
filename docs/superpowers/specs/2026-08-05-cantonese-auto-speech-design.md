# 粵語口語自動朗讀設計

## 目標

讓長者不用持續閱讀屏幕也能完成對話：對話框保留清晰的書面語文字，同一個助手回覆自動以粵語口語版本朗讀；使用者可以用一個開關控制後續自動朗讀。

## 範圍

- Middleware response 額外提供 `assistant_speech_message`。
- 對話框繼續只顯示既有的 `assistant_message` 書面語內容。
- 所有助手回覆，包括一般結果、錯誤和可恢復 recovery 回覆，都由中央轉換器產生朗讀文字；未來可逐句替換成更自然的人工口語文案。
- 前端預設啟用自動朗讀，使用 `zh-HK` 語音。
- 「停止朗讀」控制改為「自動朗讀：開／關」切換按鈕。關閉時立即停止當前語音，並阻止後續回覆自動朗讀。
- 語音 API 不可用時，文字對話及所有既有操作仍可正常使用。

不在本次範圍：引入外部語言模型或雲端 TTS、改變 middleware HTTP endpoint、把口語版本顯示在對話框、或改造語音輸入流程。

## 設計

### Response contract

`middleware.session.build_response()` 會在 response 中保留：

```json
{
  "assistant_message": "我已查到你目前的醫療預約。",
  "assistant_speech_message": "我幫你查到而家嘅醫療預約喇。"
}
```

`assistant_message` 是面向閱讀的公開文案；`assistant_speech_message` 是面向朗讀的粵語口語文案。前端對缺少新欄位的舊 middleware 回應使用 `assistant_message` 作 fallback，避免版本不同步時失去語音輸出。

### 粵語口語轉換

新增集中式、純函式轉換器，輸入一段書面語並輸出口語朗讀稿。轉換採保守的完整短語優先規則，覆蓋目前 middleware 的常用回覆，例如「目前」→「而家」、「沒有」→「冇」、「你的」→「你嘅」、「請選擇」→「麻煩你揀」。沒有匹配的內容原樣保留，確保醫療名稱、日期、編號及未知資料不被破壞。

轉換器不負責音訊生成；瀏覽器 `SpeechSynthesisUtterance` 仍使用 `zh-HK`，並維持現有速度與停止能力。

### Frontend flow

1. `app.js` 收到成功 response 後照常呼叫 `view.updateTask()`，因此對話框新增的仍是 `assistant_message`。
2. 若自動朗讀開關為開，呼叫 `speech.speak(response.assistant_speech_message || response.assistant_message)`。
3. 開關按鈕使用 `aria-pressed="true|false"` 和「自動朗讀：開／關」文字反映狀態。
4. 使用者關閉開關時呼叫 `speech.stopSpeaking()`，立即取消目前 utterance；再次開啟只影響之後的回覆，不重播舊訊息。
5. 語音 API 不支援時，開關保持可理解的文字狀態或停用，並不影響文字輸入、任務卡和 action。

### Error handling

- `assistant_speech_message` 不能生成或欄位缺失時，前端朗讀 `assistant_message`。
- `speechSynthesis.speak()` 發生例外時，保留已渲染的書面語，不讓語音錯誤中斷任務流程。
- 關閉開關永遠安全呼叫 `cancel()`；瀏覽器沒有 `speechSynthesis` 時是 no-op。

## 測試

- Middleware 單元測試確認轉換器的常用短語、未知文字原樣保留，以及 `build_response()` 同時輸出兩個欄位。
- Frontend 靜態測試確認 HTML 開關、`aria-pressed`、新 response 欄位 fallback 及 `speech.speak()` wiring。
- 執行現有 frontend static tests、middleware tests，以及所有前端 JavaScript `node --check`。
- 手動驗收一個查詢回覆和一個 action 回覆：書面語出現在對話框，朗讀使用口語欄位；關閉開關會立即停止並不朗讀下一個回覆。

