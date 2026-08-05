import { MiddlewareClient, MiddlewareError } from "./mcp-client.js";
import { createSpeechController } from "./speech.js";
import { createVoiceCapture } from "./voice-capture.js";
import { createVoiceExceptions } from "./voice-exceptions.js";

function makeSessionId() {
  return `S-${Date.now().toString(36)}`;
}

function makeTurnId() {
  return `VT-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function byId(id) {
  return document.getElementById(id);
}

function isAbort(error) {
  return error?.name === "AbortError";
}

function responseAudioUrl(payload) {
  const speech = payload?.voice_turn?.speech || payload?.speech || payload?.audio;
  return typeof speech?.url === "string" && speech.url ? speech.url : null;
}

export function startPonteApp() {
  const client = new MiddlewareClient();
  const sessionId = makeSessionId();
  const ponteButton = byId("ponte-button");
  const avatar = byId("ponte-avatar");
  const voiceState = byId("voice-state");
  const meterFill = byId("voice-meter-fill");
  const stopAudioButton = byId("stop-audio-button");
  const voiceStatusLabel = byId("voice-status-label");
  const voiceStatusHint = byId("voice-status-hint");
  const captionLine = byId("caption-line");
  const visibleVoiceStates = {
    ready: ["Ready", "Tap Ponte to talk"],
    "requesting-permission": ["Microphone access", "Allow microphone access to begin"],
    listening: ["Listening", "Speak naturally, then pause"],
    speaking: ["Listening", "Keep speaking or tap to stop"],
    stopping: ["Finishing turn", "Preparing your request"],
    captured: ["Sending", "Ponte is receiving your voice"],
    processing: ["Thinking", "Ponte is checking the safest next step"],
    "speaking-response": ["Ponte is replying", "Tap the avatar to interrupt"],
    "audio-error": ["Audio blocked", "Check your output volume, then try again"],
    "permission-denied": ["Microphone blocked", "Enable microphone access and try again"],
    unsupported: ["Browser fallback", "Using browser speech recognition"],
    error: ["Something went wrong", "Tap Ponte to try again"],
  };
  let activeAudio = null;
  let activeRequest = null;
  let latestTurn = 0;
  let recordedTranscript = "";
  let recognitionOnly = false;
  let backendVoiceReady = false;

  function setCaption(target, text, label) {
    if (!target) return;
    const value = String(text || "").trim();
    target.textContent = value ? `${label}：${value}` : "";
  }

  function showUserSpeech(text) {
    setCaption(captionLine, text, "你");
  }

  function showPonteReply(text) {
    setCaption(captionLine, text, "Ponte");
  }

  // A project can provide another same-origin asset without changing markup.
  const configuredAvatar = globalThis.PONTE_AVATAR_URL;
  if (typeof configuredAvatar === "string" && configuredAvatar.startsWith("/")) avatar.src = configuredAvatar;
  avatar.addEventListener("error", () => { avatar.src = avatar.dataset.defaultAvatar; }, { once: true });

  function setState(state, { level = null } = {}) {
    document.body.dataset.voiceState = state;
    ponteButton.setAttribute("aria-pressed", String(["requesting-permission", "listening", "speaking", "processing"].includes(state)));
    const labels = {
      ready: "點按 Ponte，開始說話",
      "requesting-permission": "正在準備麥克風…",
      listening: "我正在聽",
      speaking: "請繼續說，我會在你停下後回應",
      stopping: "正在整理你的語音…",
      captured: "正在傳送你的語音…",
      processing: "Ponte 正在思考…",
      "speaking-response": "Ponte 正在回應",
      "permission-denied": "未能使用麥克風。請允許權限後再試一次。",
      unsupported: "此瀏覽器沒有錄音功能，正使用語音辨識備援。",
      error: "暫時未能完成，請再點按 Ponte 重試。",
      "audio-error": "瀏覽器未能播放聲音。請檢查音量後再試。",
    };
    voiceState.textContent = labels[state] || labels.ready;
    const [visibleLabel, visibleHint] = visibleVoiceStates[state] || visibleVoiceStates.ready;
    voiceState.textContent = `${visibleLabel}. ${visibleHint}`;
    voiceStatusLabel.textContent = visibleLabel;
    voiceStatusHint.textContent = visibleHint;
    if (level !== null) meterFill.style.transform = `scaleX(${Math.max(0.03, Math.min(1, level))})`;
  }

  function stopPlayback() {
    activeAudio?.pause();
    if (activeAudio) activeAudio.currentTime = 0;
    activeAudio = null;
    stopAudioButton.hidden = true;
    speech.stopSpeaking();
  }

  function interruptCurrentTurn() {
    activeRequest?.abort();
    activeRequest = null;
    stopPlayback();
  }

  async function playResponse(payload, turn) {
    if (turn !== latestTurn) return;
    const audioUrl = responseAudioUrl(payload);
    if (audioUrl) {
      const audio = new Audio(client.absoluteUrl(audioUrl));
      activeAudio = audio;
      stopAudioButton.hidden = false;
      audio.addEventListener("ended", () => {
        if (activeAudio === audio) {
          activeAudio = null;
          stopAudioButton.hidden = true;
          setState("ready");
        }
      }, { once: true });
      try {
        await audio.play();
        if (turn === latestTurn) setState("speaking-response");
        return;
      } catch {
        // User agents may block remote audio; speech synthesis below is the fallback.
      }
    }
    const message = payload?.result?.assistant_message || payload?.assistant_message;
    showPonteReply(message);
    if (message && speech.speak(message, { onEnd: () => {
      if (turn === latestTurn) {
        stopAudioButton.hidden = true;
        setState("ready");
      }
    } })) {
      stopAudioButton.hidden = false;
      setState("speaking-response");
      return;
    }
    if (turn === latestTurn) {
      exceptions.renderError({ message: "未能播放 Ponte 的聲音。請檢查瀏覽器音訊權限與系統輸出裝置。" });
      setState("audio-error");
    }
  }

  async function submitVoice(clip, transcript = "") {
    const turn = ++latestTurn;
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    exceptions.clearError();
    setState("processing");
    showUserSpeech(transcript);
    try {
      const payload = await client.sendVoiceTurn({
        sessionId,
        turnId: makeTurnId(),
        audio: clip.blob,
        signal: controller.signal,
      });
      if (turn !== latestTurn) return;
      const result = payload?.result || payload;
      exceptions.renderResponse(result);
      await playResponse(payload, turn);
    } catch (error) {
      if (turn !== latestTurn || isAbort(error)) return;
      // When cloud STT is not configured, use the browser recognizer transcript
      // instead of leaving the user with a silent 503 voice turn.
      if (!backendVoiceReady && transcript && speech.supported) {
        recognitionOnly = false;
        await submitTranscript(transcript);
        return;
      }
      exceptions.renderError(error instanceof MiddlewareError ? error : { message: "語音傳送未完成，請再試一次。" });
      setState("error");
    } finally {
      if (turn === latestTurn) activeRequest = null;
    }
  }

  async function submitTranscript(text) {
    const transcript = String(text || "").trim();
    if (!transcript) return;
    const turn = ++latestTurn;
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    exceptions.clearError();
    setState("processing");
    showUserSpeech(transcript);
    try {
      const payload = await client.sendMessage({ session_id: sessionId, message: transcript, source: "voice" }, { signal: controller.signal });
      if (turn !== latestTurn) return;
      exceptions.renderResponse(payload);
      showPonteReply(payload?.assistant_message);
      await playResponse(payload, turn);
    } catch (error) {
      if (turn !== latestTurn || isAbort(error)) return;
      exceptions.renderError(error instanceof MiddlewareError ? error : { message: "語音辨識後未能送出，請再試一次。" });
      setState("error");
    } finally {
      if (turn === latestTurn) activeRequest = null;
    }
  }

  async function handleAction(action) {
    const kind = action?.kind || action?.action || action?.id;
    if (!kind) return;
    const turn = ++latestTurn;
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    exceptions.clearError();
    setState("processing");
    try {
      const payload = await client.sendAction({ session_id: sessionId, action: kind, payload: action.payload || {} }, { signal: controller.signal });
      if (turn !== latestTurn) return;
      exceptions.renderResponse(payload);
      showPonteReply(payload?.assistant_message);
      await playResponse(payload, turn);
    } catch (error) {
      if (turn !== latestTurn || isAbort(error)) return;
      exceptions.renderError(error instanceof MiddlewareError ? error : { message: "暫時未能完成這項服務，請重試。" });
      setState("error");
    } finally {
      if (turn === latestTurn) activeRequest = null;
    }
  }

  const exceptions = createVoiceExceptions({
    approvalRoot: byId("approval-region"),
    errorRoot: byId("global-error"),
    artifactRoot: byId("artifact-drawer"),
    artifactContentRoot: byId("artifact-content"),
    onAction: handleAction,
  });

  const speech = createSpeechController({
    onTranscript({ text, isFinal }) {
      recordedTranscript = text || recordedTranscript;
      showUserSpeech(recordedTranscript);
      if (recognitionOnly && isFinal) submitTranscript(recordedTranscript);
    },
    onStateChange(state) {
      if (recognitionOnly && state === "listening") setState("listening");
      if (recognitionOnly && state === "permission-denied") setState("permission-denied");
      if (state === "audio-error") {
        exceptions.renderError({ message: "瀏覽器未能播放聲音。請檢查系統輸出裝置與音量，然後再試一次。" });
        setState("audio-error");
      }
    },
  });

  const capture = createVoiceCapture();

  async function startVoiceTurn() {
    interruptCurrentTurn();
    recordedTranscript = "";
    recognitionOnly = false;
    if (!backendVoiceReady && speech.supported) {
      recognitionOnly = true;
      setState("unsupported");
      speech.start();
      return;
    }
    if (capture.supported) {
      // Recognition is optional: it improves accessibility and provides a
      // transcript while the recorded clip remains the authoritative turn.
      if (speech.supported) speech.start();
      await capture.start({
        onStateChange(state) { setState(state); },
        onLevel(level) { setState(document.body.dataset.voiceState || "listening", { level }); },
        onComplete(clip) {
          speech.stop();
          submitVoice(clip, recordedTranscript);
        },
        onFailure(error) {
          if (speech.supported) {
            recognitionOnly = true;
            setState("unsupported");
            speech.start();
          } else {
            exceptions.renderError({ message: error?.name === "NotAllowedError" ? "請允許麥克風權限後再試一次。" : "這個瀏覽器未能開始錄音。" });
            setState("error");
          }
        },
      });
      return;
    }
    if (speech.supported) {
      recognitionOnly = true;
      setState("unsupported");
      speech.start();
    } else {
      exceptions.renderError({ message: "請使用支援麥克風錄音或語音辨識的瀏覽器。" });
      setState("error");
    }
  }

  ponteButton.addEventListener("click", () => {
    // A user gesture is required before some browsers allow speech/audio output.
    speech.unlock?.();
    if (["listening", "speaking", "requesting-permission"].includes(document.body.dataset.voiceState)) {
      capture.stop("manual");
      speech.stop();
      return;
    }
    startVoiceTurn();
  });
  stopAudioButton.addEventListener("click", () => { stopPlayback(); setState("ready"); });

  client.health()
    .then((payload) => {
      const health = byId("health-status");
      const reachable = payload.backend_reachable !== false;
      backendVoiceReady = payload.voice_ready !== false;
      byId("connection-label").textContent = !reachable ? "Middleware offline" : (backendVoiceReady ? "Voice ready" : (speech.supported ? "Browser voice fallback" : "Voice setup needed"));
      health.textContent = reachable ? "服務可用" : "服務暫不可用";
      health.classList.toggle("is-offline", !reachable);
    })
    .catch(() => {
      const health = byId("health-status");
      health.textContent = "服務暫不可用";
      byId("connection-label").textContent = "Middleware offline";
      health.classList.add("is-offline");
    });

  setState("ready");
  return { client, sessionId, capture, speech, submitVoice, handleAction, interruptCurrentTurn };
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", startPonteApp, { once: true });
}
