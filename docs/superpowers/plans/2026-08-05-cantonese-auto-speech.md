# 粵語口語自動朗讀 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep written assistant replies in the conversation while automatically reading a separate Cantonese-spoken response that users can enable or disable.

**Architecture:** Add a pure Python Cantonese speech-text converter in `middleware/speech.py`. `build_response()` will add the converter output as `assistant_speech_message`, so every existing controller response path receives the new field without changing endpoint shapes or call sites. The frontend will keep rendering `assistant_message`, read the new field with a written-message fallback, and turn the existing speech control into an `aria-pressed` auto-read toggle.

**Tech Stack:** Python 3 standard library, `unittest`, browser Web Speech API, zero-build ES modules, static frontend server.

## Global Constraints

- Middleware response must preserve `assistant_message` and add `assistant_speech_message`.
- The conversation must continue displaying only the written `assistant_message`.
- Automatic speech is enabled by default and uses the browser `zh-HK` locale.
- The existing speech control becomes an `自動朗讀：開／關` toggle; disabling it immediately cancels current speech and prevents later automatic speech.
- Missing speech fields or unavailable speech APIs must leave text interactions usable.
- Do not add an external LLM, cloud TTS dependency, new endpoint, or speech-input redesign.

---

### Task 1: Add failing middleware speech contract tests

**Files:**
- Create: `middleware/tests/test_speech.py`
- Modify: `middleware/tests/test_task_manager.py` only if an existing response assertion needs the new field; otherwise leave it unchanged.

**Interfaces:**
- Consumes: planned `middleware.speech.to_cantonese_spoken` and existing `middleware.session.build_response`.
- Produces: executable regression tests for the converter and response field.

- [ ] **Step 1: Write the failing tests**

Create `middleware/tests/test_speech.py`:

```python
import unittest

from middleware.session import SessionState, build_response
from middleware.speech import to_cantonese_spoken


class CantoneseSpeechTests(unittest.TestCase):
    def test_converts_common_written_phrases_to_spoken_cantonese(self):
        text = "我已查到你目前的醫療預約，請選擇一個時段。"

        self.assertEqual(
            to_cantonese_spoken(text),
            "我幫你查到你而家嘅醫療預約，麻煩你揀一個時間。",
        )

    def test_preserves_unknown_service_names_and_identifiers(self):
        text = "服務 ABC-123 目前沒有資料。"

        spoken = to_cantonese_spoken(text)

        self.assertIn("ABC-123", spoken)
        self.assertIn("服務", spoken)
        self.assertIn("而家冇資料", spoken)

    def test_build_response_includes_written_and_spoken_messages(self):
        state = SessionState("S-SPEECH")

        response = build_response(state, "請選擇一個時段。", [])

        self.assertEqual(response["assistant_message"], "請選擇一個時段。")
        self.assertEqual(
            response["assistant_speech_message"],
            "麻煩你揀一個時間。",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest middleware.tests.test_speech -v`

Expected: FAIL because `middleware.speech` does not exist and `build_response()` has no `assistant_speech_message` field.

### Task 2: Implement the middleware Cantonese speech response

**Files:**
- Create: `middleware/speech.py`
- Modify: `middleware/session.py:70-122`

**Interfaces:**
- Consumes: `assistant_message: str` passed to `build_response()`.
- Produces: `to_cantonese_spoken(text: str) -> str` and response key `assistant_speech_message: str`.

- [ ] **Step 1: Implement the pure converter**

Create `middleware/speech.py` with ordered phrase replacements. Long phrases must be replaced before shorter phrases so the output remains grammatical:

```python
"我已查到" -> "我幫你查到"
"我已取得" -> "我已經攞到"
"目前" -> "而家"
"你的" -> "你嘅"
"請選擇" -> "麻煩你揀"
"選擇" -> "揀"
"時段" -> "時間"
"沒有" -> "冇"
"暫時無法" -> "而家未能"
"無法" -> "未能"
"這次" -> "今次"
"這個" -> "呢個"
```

The function must return `""` for an empty/non-string value only if the input is not a string; for a string, return the input after replacements. It must not alter identifiers, dates, punctuation, or unknown text.

- [ ] **Step 2: Add the field at the response boundary**

In `middleware/session.py`, import `to_cantonese_spoken` and add this adjacent to the existing written message in the `response` dictionary:

```python
"assistant_message": assistant_message,
"assistant_speech_message": to_cantonese_spoken(assistant_message),
```

Do not update individual controller call sites; the central boundary must cover normal messages, action responses, diagnostic responses, and recovery messages uniformly.

- [ ] **Step 3: Run the focused tests to verify they pass**

Run: `python -m unittest middleware.tests.test_speech -v`

Expected: 3 tests PASS.

- [ ] **Step 4: Run adjacent middleware regression tests**

Run: `python -m unittest middleware.tests.test_task_manager middleware.tests.test_controller -v`

Expected: all existing task-manager and controller tests PASS; no existing response contract assertion loses `assistant_message`.

### Task 3: Add failing frontend toggle and speech-field checks

**Files:**
- Modify: `tests/test_frontend_static.py`

**Interfaces:**
- Consumes: existing `frontend/index.html`, `frontend/app.js`, and `frontend/speech.js` source strings.
- Produces: static checks for the new control semantics and response-field wiring.

- [ ] **Step 1: Extend the frontend static tests**

Add a test method to `FrontendStaticTests`:

```python
def test_frontend_supports_written_and_spoken_reply_toggle(self):
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    app = Path("frontend/app.js").read_text(encoding="utf-8")

    self.assertIn('id="speak-stop-button"', html)
    self.assertIn('aria-pressed="true"', html)
    self.assertIn("自動朗讀：開", html)
    self.assertIn("assistant_speech_message", app)
    self.assertIn("autoSpeakEnabled", app)
    self.assertIn("speech.stopSpeaking()", app)
    self.assertIn(
        "response.assistant_speech_message || response.assistant_message",
        app,
    )
```

Also extend `test_speech_module_has_fallback_and_cantonese_locale` with:

```python
self.assertIn("try", js)
self.assertIn("catch", js)
```

- [ ] **Step 2: Run the new checks to verify they fail**

Run: `python -m unittest tests.test_frontend_static.FrontendStaticTests.test_frontend_supports_written_and_spoken_reply_toggle -v`

Expected: FAIL because the existing HTML still says `停止朗讀` and `app.js` has no toggle state or new response field.

### Task 4: Implement resilient speech output and the auto-read toggle

**Files:**
- Modify: `frontend/index.html:49-54`
- Modify: `frontend/app.js:18-160`
- Modify: `frontend/speech.js:54-69`

**Interfaces:**
- Consumes: response objects with optional `assistant_speech_message`.
- Produces: default-on auto-read behavior, a toggle control, immediate cancellation when off, and safe speech synthesis failures.

- [ ] **Step 1: Change the existing control into an accessible toggle**

Keep `id="speak-stop-button"` to preserve the existing DOM contract, but change the button to:

```html
<button
  id="speak-stop-button"
  type="button"
  class="button button-secondary"
  aria-pressed="true"
>
  自動朗讀：開
</button>
```

- [ ] **Step 2: Add default-on state and response speech selection**

In `startPonteApp()`:

```javascript
const autoSpeakButton = byId("speak-stop-button");
let autoSpeakEnabled = true;

function renderAutoSpeakState() {
  autoSpeakButton.setAttribute("aria-pressed", String(autoSpeakEnabled));
  autoSpeakButton.textContent = `自動朗讀：${autoSpeakEnabled ? "開" : "關"}`;
}

function speakResponse(response) {
  if (!autoSpeakEnabled) return;
  speech.speak(response.assistant_speech_message || response.assistant_message);
}
```

Call `speakResponse(response)` after `view.updateTask()` in both `sendMessage()` and `handleAction()`. Replace the existing direct `speech.speak(response.assistant_message)` calls.

Bind the control:

```javascript
autoSpeakButton.addEventListener("click", () => {
  autoSpeakEnabled = !autoSpeakEnabled;
  if (!autoSpeakEnabled) speech.stopSpeaking();
  renderAutoSpeakState();
});

renderAutoSpeakState();
```

The toggle must remain usable while a request is pending; only the submit button is disabled by `setPending()`.

- [ ] **Step 3: Make speech synthesis failure-safe**

Wrap the current `speechSynthesis.cancel()`, `new SpeechSynthesisUtterance(text)`, and `speechSynthesis.speak(utterance)` sequence in `frontend/speech.js` in `try/catch`. Return `true` only after `speak()` is called; return `false` on missing APIs, empty text, or an exception. Keep `utterance.lang = "zh-HK"`, `rate = 0.92`, and `pitch = 1`.

- [ ] **Step 4: Run syntax and focused frontend tests**

Run: `node --check frontend/app.js; node --check frontend/speech.js`

Expected: both commands exit 0.

Run: `python -m unittest tests.test_frontend_static -v`

Expected: all frontend static tests PASS, including the new toggle test.

### Task 5: Update frontend documentation and verify the full change

**Files:**
- Modify: `frontend/README.md` in the 「已實現的互動」 and 「驗證」 sections.

**Interfaces:**
- Consumes: final response contract and UI behavior from Tasks 2 and 4.
- Produces: user-facing documentation that accurately describes written reply display, Cantonese speech output, and the auto-read switch.

- [ ] **Step 1: Update the interaction documentation**

Replace the existing speech-output bullet with wording that explicitly says the assistant keeps written text in the conversation, reads `assistant_speech_message` in Cantonese, defaults to enabled, and uses `自動朗讀：開／關` to control it. State that missing speech support does not disable text interaction.

- [ ] **Step 2: Run the complete verification suite**

Run: `python -m unittest discover -v`

Expected: exit 0 with 0 failures and 0 errors.

Run: `node --check frontend/app.js; node --check frontend/mcp-client.js; node --check frontend/interaction-view.js; node --check frontend/speech.js`

Expected: all four commands exit 0.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 3: Review the final diff against the spec**

Run: `git status --short; git diff --stat; git diff -- middleware/speech.py middleware/session.py frontend/index.html frontend/app.js frontend/speech.js tests/test_frontend_static.py frontend/README.md middleware/tests/test_speech.py`

Confirm:

1. The conversation renderer still receives and displays `assistant_message`.
2. The browser reads `assistant_speech_message` with a fallback.
3. The toggle defaults to on, uses `aria-pressed`, and cancels speech when turned off.
4. No external dependency or endpoint changed.

- [ ] **Step 4: Commit the implementation**

```bash
git add middleware/speech.py middleware/session.py middleware/tests/test_speech.py frontend/index.html frontend/app.js frontend/speech.js tests/test_frontend_static.py frontend/README.md
git commit -m "feat: add Cantonese auto speech toggle"
```

