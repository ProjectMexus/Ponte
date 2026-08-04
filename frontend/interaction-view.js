const TASK_STATE_LABELS = {
  idle: "等待你的需要",
  querying: "正在查詢資料",
  selecting_service: "請選擇服務",
  selecting_slot: "請選擇時段",
  awaiting_confirmation: "等待你的確認",
  submitted: "已提交，正在等待服務回覆",
  completed: "已完成",
  cancelled: "已取消",
  failed: "需要再試一次",
  human_handoff: "已準備轉交人工",
};

const STEP_STATUS_LABELS = {
  completed: "已完成",
  current: "現在進行",
  failed: "需要處理",
  pending: "稍後進行",
};

function asText(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(asText).join("、");
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}：${asText(item)}`).join("；");
  return String(value);
}

function displayDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(value)) return asText(value);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-HK", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function displayLabel(value) {
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function createDataCard(title, value) {
  const card = createElement("article", "data-card");
  card.append(createElement("h3", "", title));

  if (value && typeof value === "object" && !Array.isArray(value)) {
    const list = createElement("dl");
    for (const [key, item] of Object.entries(value)) {
      list.append(
        createElement("dt", "", displayLabel(key)),
        createElement("dd", "", displayDate(item)),
      );
    }
    card.append(list);
  } else {
    card.append(createElement("p", "", displayDate(value)));
  }
  return card;
}

function renderData(container, data) {
  if (!data || typeof data !== "object" || Object.keys(data).length === 0) {
    container.append(createElement("div", "empty-workspace", "完成這一步後，相關資料會顯示在這裡。"));
    return;
  }

  for (const [key, value] of Object.entries(data)) {
    if (Array.isArray(value)) {
      if (value.length === 0) {
        container.append(createDataCard(displayLabel(key), "暫時沒有資料"));
      } else {
        value.forEach((item, index) => {
          container.append(createDataCard(`${displayLabel(key)} ${index + 1}`, item));
        });
      }
    } else {
      container.append(createDataCard(displayLabel(key), value));
    }
  }
}

function renderSteps(container, steps) {
  container.replaceChildren();
  (steps || []).forEach((step, index) => {
    const status = step.status || "pending";
    const item = createElement("li", `task-step is-${status}`);
    item.append(
      createElement("span", "task-step-marker", status === "completed" ? "✓" : String(index + 1)),
      createElement("span", "task-step-label", step.label || step.id || "服務步驟"),
      createElement("span", "task-step-status", STEP_STATUS_LABELS[status] || status),
    );
    container.append(item);
  });
}

function renderToolEvents(container, toolEvents) {
  (toolEvents || []).forEach((event) => {
    const card = createElement("article", "tool-event-card");
    const status = event.ok === false || event.status === "error" ? "未成功" : "已完成";
    card.append(
      createElement("strong", "", event.tool_name || event.tool || "服務工具"),
      createElement("span", "", status),
      createElement("span", "tool-event-meta", `步驟：${event.step_id || "—"}　請求編號：${event.request_id || "—"}`),
    );
    container.append(card);
  });
}

function inputDateValue(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function createDateField(label, name, value) {
  const field = createElement("label", "date-field");
  field.append(createElement("span", "date-field-label", label));
  const input = createElement("input");
  input.type = "date";
  input.name = name;
  input.value = value;
  field.append(input);
  return input;
}

function slotLabel(slot) {
  if (slot.label) return asText(slot.label);
  const start = displayDate(slot.start);
  const end = displayDate(slot.end);
  if (start !== "—" && end !== "—") return `${start} — ${end}`;
  if (start !== "—") return start;
  return asText(slot.id);
}

function renderGenericActions(container, actions, onAction) {
  (actions || []).forEach((action) => {
    const kind = action.kind || action.id || "action";
    const button = createElement("button", "action-button", action.label || "繼續");
    button.type = "button";
    if (kind === "confirm") button.classList.add("is-confirm");
    if (kind === "cancel" || kind === "human_help") button.classList.add("is-danger");
    button.addEventListener("click", () => onAction(action));
    container.append(button);
  });
}

function renderActions(container, response, onAction) {
  container.replaceChildren();
  const data = response?.data && typeof response.data === "object" ? response.data : {};
  const selectingService = response?.current_step === "select_service" || response?.task_state === "selecting_service";
  if (selectingService) {
    const today = new Date();
    const dateRange = createElement("div", "date-range-controls");
    const dateFrom = createDateField("開始日期", "date_from", inputDateValue(today));
    const dateTo = createDateField("結束日期", "date_to", inputDateValue(new Date(today.getFullYear(), today.getMonth(), today.getDate() + 14)));
    dateRange.append(dateFrom.closest("label"), dateTo.closest("label"));
    container.append(dateRange);

    const choices = createElement("div", "service-choice-list");
    const services = Array.isArray(data.services) ? data.services : [];
    services.forEach((service) => {
      const serviceName = asText(service.name || service.name_en || service.id);
      const button = createElement("button", "action-button", serviceName);
      button.type = "button";
      button.addEventListener("click", () => onAction({
        kind: "search_slots",
        label: `搜尋${serviceName}時段`,
        payload: {
          service_id: service.id,
          date_from: dateFrom.value,
          date_to: dateTo.value,
        },
      }));
      choices.append(button);
    });
    if (services.length === 0) choices.append(createElement("div", "empty-workspace", "目前沒有可預約服務。"));
    container.append(choices);
    return;
  }

  const selectingSlot = response?.current_step === "select_slot" || response?.task_state === "selecting_slot";
  if (selectingSlot) {
    const choices = createElement("div", "slot-choice-list");
    const slots = Array.isArray(data.slots) ? data.slots : [];
    slots.forEach((slot) => {
      const label = slotLabel(slot);
      const button = createElement("button", "action-button", label);
      button.type = "button";
      button.addEventListener("click", () => onAction({
        kind: "select_slot",
        label: `選擇${label}`,
        payload: {slot_id: slot.id},
      }));
      choices.append(button);
    });
    if (slots.length === 0) choices.append(createElement("div", "empty-workspace", "目前沒有可預約時段。"));
    container.append(choices);
    return;
  }

  renderGenericActions(container, response?.actions, onAction);
}

export function createInteractionView({
  conversationRoot,
  healthRoot,
  stepsRoot,
  taskRoot,
  actionsRoot,
  errorRoot,
  stateRoot,
  onAction,
}) {
  function appendMessage(role, text) {
    if (!text) return;
    const message = createElement("article", `message message-${role}`);
    message.append(
      createElement("span", "message-label", role === "user" ? "你說" : "Ponte 回覆"),
      createElement("p", "", text),
    );
    conversationRoot.append(message);
    conversationRoot.scrollTop = conversationRoot.scrollHeight;
  }

  function renderResponse(response) {
    if (response.assistant_message) appendMessage("assistant", response.assistant_message);
    if (stateRoot) stateRoot.textContent = TASK_STATE_LABELS[response.task_state] || response.task_state || TASK_STATE_LABELS.idle;
    renderSteps(stepsRoot, response.steps);
    taskRoot.replaceChildren();
    renderData(taskRoot, response.data);
    renderToolEvents(taskRoot, response.tool_events);
    renderActions(actionsRoot, response, onAction);
    clearError();
  }

  function renderHealth(payload) {
    const reachable = payload.backend_reachable !== false;
    healthRoot.classList.toggle("is-ready", reachable);
    healthRoot.classList.toggle("is-offline", !reachable);
    healthRoot.textContent = reachable
      ? `服務已連線｜${payload.tool_count || 0} 項能力可用`
      : "服務中心未連線，仍可先使用文字輸入。";
  }

  function renderError(error) {
    errorRoot.hidden = false;
    errorRoot.textContent = error?.message || "服務暫時未能回應，請稍後再試。";
  }

  function clearError() {
    errorRoot.hidden = true;
    errorRoot.textContent = "";
  }

  appendMessage("assistant", "你好，我是 Ponte。你可以告訴我想查詢或預約哪一項服務。重要操作一定會先請你確認。 ");

  return {
    appendUserMessage: (text) => appendMessage("user", text),
    renderResponse,
    renderHealth,
    renderError,
    clearError,
  };
}
