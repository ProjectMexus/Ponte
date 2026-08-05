# Ponte voice agent

The browser now starts on a Ponte avatar surface. A click unlocks the microphone; `MediaRecorder` captures WebM/Opus (or Ogg/Opus), and a Web Audio analyser ends a turn after 1.35 seconds of silence. Starting a new turn cancels current playback and aborts the previous request. Responses are ignored unless their local turn is still current.

The middleware endpoint is `POST /api/voice/turn` with multipart fields `session_id`, `turn_id`, and `audio`. It accepts binary audio up to 4 MiB and returns assistant metadata. Synthesized speech is fetched as raw bytes from `GET /api/voice/turn/{turn_id}/speech?session_id=...`.

With cloud endpoints configured, the flow is:

`audio -> STT (zh-HK) -> registry agent (all 21 tools) -> optional TTS`

R0 tools execute automatically. R1/R2 tools are converted into a five-minute, SHA-256-protected proposal. The isolated approval classifier receives only the current confirmation utterance and returns `APPROVE`, `CANCEL`, or `UNCERTAIN`; the task agent never decides approval. Approved execution uses the stored proposal arguments exactly, then returns an HTML receipt artifact for the side drawer.

Set `PONTE_LLM_API_URL`, `PONTE_LLM_API_KEY`, `PONTE_LLM_MODEL`, `PONTE_VOICE_STT_URL`, `PONTE_VOICE_STT_MODEL`, and optionally `PONTE_VOICE_TTS_URL`, `PONTE_VOICE_TTS_MODEL`, and `PONTE_VOICE_TTS_VOICE`. Set `PONTE_VOICE_AGENT_ENABLED=true` if you want browser transcript fallback to use the same agent without cloud STT. If cloud voice is not configured, the endpoint returns a structured 503 and the browser keeps its Web Speech recognition/synthesis fallback. A browser abort cannot undo a mutation that has already started on the server; the action receipt remains the source of truth.
