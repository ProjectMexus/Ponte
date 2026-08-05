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

const DISPLAY_COPY = {
  "zh-Hant": {
    states: {
      ready: ["準備好了", "點按小澳開始說話"],
      "requesting-permission": ["正在準備麥克風", "請允許麥克風權限"],
      listening: ["小澳正在聆聽", "請自然說話，停頓後便會回應"],
      speaking: ["小澳正在聆聽", "繼續說話，或點按頭像停止"],
      stopping: ["正在完成這一輪", "正在整理你的語音"],
      captured: ["正在傳送", "小澳正在接收你的語音"],
      processing: ["小澳在思考中。", "正在整理你的需要"],
      "speaking-response": ["小澳正在回應。", "點按小澳即可中斷"],
      "audio-error": ["未能播放聲音", "請檢查輸出音量後再試"],
      "permission-denied": ["麥克風已被封鎖", "請允許麥克風權限後再試"],
      unsupported: ["正在使用瀏覽器語音", "粵語語音辨識備援已啟用"],
      error: ["暫時未能完成", "請點按小澳再試一次"],
    },
    captions: { user: "你", assistant: "小澳", separator: "：" },
    system: {
      healthChecking: "正在連線",
      healthOnline: "服務可用",
      healthOffline: "服務暫不可用",
      connectionChecking: "正在檢查語音服務",
      voiceCloud: "雲端語音已就緒",
      voiceFallback: "瀏覽器語音備援",
      voiceUnavailable: "語音需要設定",
      middlewareOffline: "服務未連線",
      serviceLabel: "服務",
      serviceChecking: "連線中",
      serviceOnline: "已連線",
      serviceOffline: "離線",
      voiceLabel: "語音",
      voiceChecking: "檢查中",
      microphoneLabel: "麥克風",
      microphone: {
        ready: "待命",
        "requesting-permission": "等待權限",
        listening: "聆聽中",
        speaking: "聆聽中",
        stopping: "處理中",
        captured: "處理中",
        processing: "處理中",
        "speaking-response": "播放中",
        unsupported: "瀏覽器辨識",
        "permission-denied": "已封鎖",
        "audio-error": "需要注意",
        error: "需要注意",
      },
      avatarAction: "點按小澳開始或停止語音",
      languageControl: "顯示語言",
    },
  },
  en: {
    states: {
      ready: ["Ready", "Tap Ponte to talk"],
      "requesting-permission": ["Microphone access", "Allow microphone access to begin"],
      listening: ["Ponte is listening", "Speak naturally, then pause"],
      speaking: ["Ponte is listening", "Keep speaking or tap the avatar to stop"],
      stopping: ["Finishing this turn", "Preparing your voice request"],
      captured: ["Sending", "Ponte is receiving your voice"],
      processing: ["Ponte is thinking.", "Organising what you need"],
      "speaking-response": ["Ponte is replying.", "Tap Ponte to interrupt"],
      "audio-error": ["Audio unavailable", "Check your output volume and try again"],
      "permission-denied": ["Microphone blocked", "Allow microphone access and try again"],
      unsupported: ["Browser voice active", "Cantonese recognition fallback is enabled"],
      error: ["Something went wrong", "Tap Ponte to try again"],
    },
    captions: { user: "You", assistant: "Ponte", separator: ": " },
    system: {
      healthChecking: "Connecting",
      healthOnline: "Service available",
      healthOffline: "Service unavailable",
      connectionChecking: "Checking voice service",
      voiceCloud: "Cloud voice ready",
      voiceFallback: "Browser voice fallback",
      voiceUnavailable: "Voice setup needed",
      middlewareOffline: "Service offline",
      serviceLabel: "Service",
      serviceChecking: "Connecting",
      serviceOnline: "Connected",
      serviceOffline: "Offline",
      voiceLabel: "Voice",
      voiceChecking: "Checking",
      microphoneLabel: "Microphone",
      microphone: {
        ready: "Standby",
        "requesting-permission": "Awaiting access",
        listening: "Listening",
        speaking: "Listening",
        stopping: "Processing",
        captured: "Processing",
        processing: "Processing",
        "speaking-response": "Playing",
        unsupported: "Browser recognition",
        "permission-denied": "Blocked",
        "audio-error": "Needs attention",
        error: "Needs attention",
      },
      avatarAction: "Tap Ponte to start or stop voice",
      languageControl: "Display language",
    },
  },
};

export function startPonteApp() {
  const client = new MiddlewareClient();
  const sessionId = makeSessionId();
  const ponteButton = byId("ponte-button");
  const avatar = byId("ponte-avatar");
  const voiceState = byId("voice-state");
  const meterFill = byId("voice-meter-fill");
  const voiceStatusLabel = byId("voice-status-label");
  const voiceStatusHint = byId("voice-status-hint");
  const captionLine = byId("caption-line");
  const serviceStatusLabel = byId("service-status-label");
  const serviceStatusValue = byId("service-status-value");
  const voicePathLabel = byId("voice-path-label");
  const voicePathValue = byId("voice-path-value");
  const microphoneStatusLabel = byId("microphone-status-label");
  const microphoneStatusValue = byId("microphone-status-value");
  let activeAudio = null;
  let activeRequest = null;
  let latestTurn = 0;
  let recordedTranscript = "";
  let recognitionOnly = false;
  let backendVoiceReady = false;
  let activeSpeechTurn = 0;
  let displayLocale = "zh-Hant";
  let currentState = "ready";
  let currentCaption = null;
  let captionTimer = null;
  let healthSnapshot = { reachable: null, voiceReady: null };

  function copy() {
    return DISPLAY_COPY[displayLocale];
  }

  function renderCaption() {
    if (!captionLine || !currentCaption?.text) {
      if (captionLine) captionLine.textContent = "";
      return;
    }
    const captions = copy().captions;
    captionLine.textContent = `${captions[currentCaption.role]}${captions.separator}${currentCaption.text}`;
  }

  function setCaption(role, text) {
    const value = String(text || "").trim();
    clearTimeout(captionTimer);
    captionTimer = null;
    currentCaption = value ? { role, text: value } : null;
    renderCaption();
    if (value) {
      captionTimer = setTimeout(() => {
        currentCaption = null;
        captionTimer = null;
        renderCaption();
      }, 8000);
    }
  }

  function showUserSpeech(text) {
    setCaption("user", text);
  }

  function showPonteReply(text) {
    setCaption("assistant", text);
  }

  // A project can provide another same-origin asset without changing markup.
  const configuredAvatar = globalThis.PONTE_AVATAR_URL;
  if (typeof configuredAvatar === "string" && configuredAvatar.startsWith("/")) avatar.src = configuredAvatar;
  avatar.addEventListener("error", () => { avatar.src = avatar.dataset.defaultAvatar; }, { once: true });

  function renderSystemStatus() {
    const system = copy().system;
    const health = byId("health-status");
    const connection = byId("connection-label");
    const reachable = healthSnapshot.reachable;
    const voiceReady = healthSnapshot.voiceReady;

    health.textContent = reachable === null
      ? system.healthChecking
      : (reachable ? system.healthOnline : system.healthOffline);
    health.classList.toggle("is-offline", reachable === false);
    connection.textContent = reachable === null
      ? system.connectionChecking
      : (!reachable
        ? system.middlewareOffline
        : (voiceReady ? system.voiceCloud : (speech.supported ? system.voiceFallback : system.voiceUnavailable)));

    serviceStatusLabel.textContent = system.serviceLabel;
    serviceStatusValue.textContent = reachable === null
      ? system.serviceChecking
      : (reachable ? system.serviceOnline : system.serviceOffline);
    voicePathLabel.textContent = system.voiceLabel;
    voicePathValue.textContent = reachable === null
      ? system.voiceChecking
      : (!reachable
        ? system.middlewareOffline
        : (voiceReady ? system.voiceCloud : (speech.supported ? system.voiceFallback : system.voiceUnavailable)));
    microphoneStatusLabel.textContent = system.microphoneLabel;
    microphoneStatusValue.textContent = system.microphone[currentState] || system.microphone.ready;
  }

  function setState(state, { level = null } = {}) {
    currentState = state;
    document.body.dataset.voiceState = state;
    ponteButton.setAttribute("aria-pressed", String(["requesting-permission", "listening", "speaking", "processing", "speaking-response"].includes(state)));
    const [visibleLabel, visibleHint] = copy().states[state] || copy().states.ready;
    voiceState.textContent = `${visibleLabel} ${visibleHint}`;
    voiceStatusLabel.textContent = visibleLabel;
    voiceStatusHint.textContent = visibleHint;
    microphoneStatusValue.textContent = copy().system.microphone[state] || copy().system.microphone.ready;
    if (level !== null) meterFill.style.transform = `scaleX(${Math.max(0.03, Math.min(1, level))})`;
  }

  function setDisplayLocale(locale) {
    if (!DISPLAY_COPY[locale]) return;
    displayLocale = locale;
    document.documentElement.lang = locale;
    byId("language-toggle").setAttribute("aria-label", copy().system.languageControl);
    document.querySelectorAll("[data-locale]").forEach((button) => {
      const active = button.dataset.locale === locale;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    ponteButton.setAttribute("aria-label", copy().system.avatarAction);
    avatar.alt = displayLocale === "zh-Hant" ? "小澳" : "Ponte";
    byId("avatar-action-label").textContent = copy().system.avatarAction;
    setState(currentState);
    renderSystemStatus();
    renderCaption();
  }

  function stopPlayback() {
    activeAudio?.pause();
    if (activeAudio) activeAudio.currentTime = 0;
    activeAudio = null;
    activeSpeechTurn = 0;
    speech.stopSpeaking();
  }

  function interruptCurrentTurn() {
    activeRequest?.abort();
    activeRequest = null;
    stopPlayback();
  }

  async function playResponse(payload, turn) {
    if (turn !== latestTurn) return;
    const message = payload?.result?.assistant_message || payload?.assistant_message;
    showPonteReply(message);
    const audioUrl = responseAudioUrl(payload);
    if (audioUrl) {
      const audio = new Audio(client.absoluteUrl(audioUrl));
      activeAudio = audio;
      audio.addEventListener("ended", () => {
        if (activeAudio === audio) {
          activeAudio = null;
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
    activeSpeechTurn = turn;
    const speechStarted = message && speech.speak(message, { onEnd: () => {
      if (turn === latestTurn) {
        activeSpeechTurn = 0;
        setState("ready");
      }
    } });
    if (speechStarted) {
      setState("speaking-response");
      return;
    }
    activeSpeechTurn = 0;
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
    interruptCurrentTurn();
    const turn = ++latestTurn;
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
      if (state === "audio-error" && activeSpeechTurn === latestTurn && document.body.dataset.voiceState === "speaking-response") {
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
    const state = document.body.dataset.voiceState;
    if (state === "speaking-response") {
      latestTurn += 1;
      interruptCurrentTurn();
      setState("ready");
      return;
    }
    if (["listening", "speaking", "requesting-permission"].includes(state)) {
      capture.stop("manual");
      speech.stop();
      return;
    }
    startVoiceTurn();
  });

  document.querySelectorAll("[data-locale]").forEach((button) => {
    button.addEventListener("click", () => setDisplayLocale(button.dataset.locale));
  });

  client.health()
    .then((payload) => {
      const reachable = payload.backend_reachable !== false;
      backendVoiceReady = payload.voice_ready !== false;
      healthSnapshot = { reachable, voiceReady: backendVoiceReady };
      renderSystemStatus();
    })
    .catch(() => {
      backendVoiceReady = false;
      healthSnapshot = { reachable: false, voiceReady: false };
      renderSystemStatus();
    });

  setDisplayLocale("zh-Hant");
  return { client, sessionId, capture, speech, submitVoice, handleAction, interruptCurrentTurn };
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", startPonteApp, { once: true });
}
