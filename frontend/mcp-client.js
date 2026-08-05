export class MiddlewareError extends Error {
  constructor(code, message, status = 0, details = {}) {
    super(message);
    this.name = "MiddlewareError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function defaultBaseUrl() {
  if (globalThis.PONTE_MIDDLEWARE_URL) {
    return globalThis.PONTE_MIDDLEWARE_URL;
  }
  if (typeof globalThis.location !== "undefined") {
    const configured = new URL(globalThis.location.href).searchParams.get("middleware");
    if (configured) return configured;
  }
  return "http://127.0.0.1:8090";
}

export class MiddlewareClient {
  constructor(baseUrl = defaultBaseUrl()) {
    this.baseUrl = String(baseUrl).replace(/\/$/, "");
  }

  async request(path, options = {}) {
    let response;
    try {
      const hasBody = options.body !== undefined && options.body !== null;
      const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
      response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers: {
          ...(hasBody && !isFormData ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {}),
        },
      });
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw new MiddlewareError(
        "MIDDLEWARE_UNAVAILABLE",
        "暫時未能連接服務中心，請稍後再試。",
        0,
        { cause: error instanceof Error ? error.message : String(error) },
      );
    }

    const raw = await response.text();
    let payload;
    try {
      payload = raw ? JSON.parse(raw) : {};
    } catch (error) {
      throw new MiddlewareError(
        "MIDDLEWARE_INVALID_RESPONSE",
        "服務中心返回了無法讀取的資料。",
        response.status,
        { cause: error instanceof Error ? error.message : String(error) },
      );
    }

    if (!response.ok) {
      const errorPayload = payload.error || payload;
      throw new MiddlewareError(
        errorPayload.code || "MIDDLEWARE_HTTP_ERROR",
        errorPayload.message || "服務暫時未能回應。",
        response.status,
        errorPayload,
      );
    }
    return payload;
  }

  health() {
    return this.request("/api/health");
  }

  sendMessage(body, options = {}) {
    return this.request("/api/interactions/message", {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  absoluteUrl(path) {
    return new URL(path, `${this.baseUrl}/`).toString();
  }

  sendAction(body, options = {}) {
    return this.request("/api/interactions/action", {
      ...options,
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  sendVoiceTurn({ sessionId, turnId, audio, signal }) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("turn_id", turnId);
    form.append("locale", "zh-HK");
    form.append("audio", audio, `ponte-${turnId}.${audio?.type?.includes("ogg") ? "ogg" : "webm"}`);
    return this.request("/api/voice/turn", { method: "POST", body: form, signal });
  }

  callTool(name, argumentsValue) {
    return this.request("/api/mcp/tools/call", {
      method: "POST",
      body: JSON.stringify({ name, arguments: argumentsValue }),
    });
  }
}
