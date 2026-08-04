import { MiddlewareClient, MiddlewareError } from "./mcp-client.js";
import { createInteractionView } from "./interaction-view.js";
import { createSpeechController } from "./speech.js";

function makeSessionId() {
  return `S-${Date.now().toString(36)}`;
}

function byId(id) {
  return document.getElementById(id);
}

export function startPonteApp() {
  const client = new MiddlewareClient();
  const sessionId = makeSessionId();
  const messageInput = byId("message-input");
  const messageForm = byId("message-form");
  const sendButton = byId("send-button");
  const micButton = byId("mic-button");
  const speechStatus = byId("speech-status");
  let requestPending = false;
  let inputSource = "text";
  let activeTaskId = null;

  const view = createInteractionView({
    conversationRoot: byId("conversation-list"),
    healthRoot: byId("health-status"),
    taskListRoot: byId("task-list"),
    errorRoot: byId("global-error"),
    onAction: handleAction,
  });

  const speech = createSpeechController({
    onTranscript({ text, isFinal }) {
      if (text) {
        messageInput.value = text;
        inputSource = "voice";
      }
      speechStatus.textContent = isFinal ? "已聽到你的話，請先檢查文字，再按送出。" : "正在聽，請繼續說…";
    },
    onStateChange(state) {
      if (state === "unsupported") {
        speechStatus.textContent = "這個瀏覽器未支援語音輸入，你仍然可以打字。";
        micButton.disabled = true;
        micButton.setAttribute("aria-pressed", "false");
        return;
      }
      if (state === "listening") {
        micButton.textContent = "停止聽取";
        micButton.setAttribute("aria-pressed", "true");
        speechStatus.textContent = "正在聽，請說出你的需要。";
        return;
      }
      micButton.textContent = "按這裡說話";
      micButton.setAttribute("aria-pressed", "false");
      if (state === "permission-denied") {
        speechStatus.textContent = "未能使用麥克風，你仍然可以打字。";
      } else if (state === "error") {
        speechStatus.textContent = "未能聽清楚，你可以再試一次或改為打字。";
      } else if (state === "idle") {
        speechStatus.textContent = "你可以先檢查文字，再按送出。";
      }
    },
  });

  function setPending(pending) {
    requestPending = pending;
    sendButton.disabled = pending;
    sendButton.textContent = pending ? "處理中…" : "送出";
  }

  async function sendMessage(message, source = "text") {
    const trimmed = String(message || "").trim();
    if (!trimmed || requestPending) return;
    view.clearError();
    view.appendUserMessage(trimmed);
    messageInput.value = "";
    inputSource = "text";
    const taskId = view.startTask({
      channel: source,
      value: trimmed,
    });
    activeTaskId = taskId;
    setPending(true);
    try {
      const response = await client.sendMessage({ session_id: sessionId, message: trimmed, source });
      view.updateTask(taskId, response);
      speech.speak(response.assistant_message);
    } catch (error) {
      view.failTask(taskId, error);
      handleError(error);
    } finally {
      setPending(false);
      messageInput.focus();
    }
  }

  async function handleAction(action, taskId = null) {
    if (!action || requestPending) return;
    taskId = taskId || activeTaskId;
    if (!taskId) {
      taskId = view.startTask({ channel: "ui", value: action });
      activeTaskId = taskId;
    } else {
      view.continueTask(taskId, {
        channel: "ui",
        value: action,
      });
    }
    view.clearError();
    setPending(true);
    try {
      const response = await client.sendAction({
        session_id: sessionId,
        action: action.kind || action.action || action.id,
        payload: action.payload || {},
      });
      view.updateTask(taskId, response);
      speech.speak(response.assistant_message);
    } catch (error) {
      view.failTask(taskId, error);
      handleError(error);
    } finally {
      setPending(false);
    }
  }

  function handleError(error) {
    if (error instanceof MiddlewareError) {
      view.renderError(error);
      if (error.code === "MIDDLEWARE_UNAVAILABLE") {
        view.renderHealth({ backend_reachable: false });
      }
      return;
    }
    view.renderError({ message: "暫時未能完成這一步，你可以再試一次。" });
  }

  messageForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(messageInput.value, inputSource);
  });

  micButton.addEventListener("click", () => {
    if (!speech.supported) return;
    if (micButton.getAttribute("aria-pressed") === "true") {
      speech.stop();
    } else {
      speech.start();
    }
  });

  byId("speak-stop-button").addEventListener("click", () => speech.stopSpeaking());

  document.querySelectorAll("[data-quick-message]").forEach((button) => {
    button.addEventListener("click", () => sendMessage(button.dataset.quickMessage, "text"));
  });

  byId("human-help-button").addEventListener("click", () => handleAction({
    kind: "human_help",
    label: "需要人工幫忙",
    payload: {},
  }));

  client.health()
    .then((payload) => view.renderHealth(payload))
    .catch((error) => handleError(error));

  return { client, sessionId, speech, view, sendMessage, handleAction };
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", startPonteApp, { once: true });
}
