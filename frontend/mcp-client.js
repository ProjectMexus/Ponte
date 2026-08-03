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
  return globalThis.PONTE_MIDDLEWARE_URL || "http://127.0.0.1:8090";
}

export class MiddlewareClient {
  constructor(baseUrl = defaultBaseUrl()) {
    this.baseUrl = String(baseUrl).replace(/\/$/, "");
  }

  async request(path, options = {}) {
    let response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
    } catch (error) {
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

  sendMessage(body) {
    return this.request("/api/interactions/message", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  sendAction(body) {
    return this.request("/api/interactions/action", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  callTool(name, argumentsValue) {
    return this.request("/api/mcp/tools/call", {
      method: "POST",
      body: JSON.stringify({ name, arguments: argumentsValue }),
    });
  }
}
