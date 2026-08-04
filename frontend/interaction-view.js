const TASK_STATE_LABELS = {
  idle: "等待你的需要",
  querying: "正在查詢資料",
  selecting_service: "請選擇服務",
  selecting_slot: "請選擇時段",
  awaiting_confirmation: "等待你的確認",
  awaiting_user_input: "需要你的協助",
  submitted: "已提交，正在等待服務回覆",
  completed: "已完成",
  cancelled: "已取消",
  failed: "需要再試一次",
  human_handoff: "已準備轉交人工",
};

const TERMINAL_TASK_STATES = new Set([
  "completed",
  "cancelled",
  "failed",
  "error",
  "human_handoff",
]);

function taskStatus(taskState) {
  if (taskState === "completed") return "completed";
  if (taskState === "cancelled") return "cancelled";
  if (taskState === "human_handoff") return "human_handoff";
  if (taskState === "failed" || taskState === "error") return "failed";
  return "running";
}

function taskTitle(value) {
  const text = String(value || "").trim();
  if (/查詢|查询/.test(text) && /醫療|医疗|預約|预约/.test(text)) return "查詢醫療預約";
  if (/預約|预约/.test(text) && /醫療|医疗/.test(text)) return "預約醫療服務";
  if (/現金分享/.test(text)) return "查詢現金分享計劃";
  if (/長者|长者/.test(text) && /活動|活动/.test(text)) return "查詢長者文娛活動";
  return text ? text.slice(0, 40) : "公共服務需求";
}

function taskTeaser(task) {
  const response = task.response || {};
  const data = response.data && typeof response.data === "object" ? response.data : {};
  const appointments = Array.isArray(data.appointments) ? data.appointments : [];
  if (data.intent === "medical_query") {
    return appointments.length ? `已查到 ${appointments.length} 個醫療預約` : "目前沒有已預約的醫療服務";
  }
  if (response.task_state === "completed") return "服務已完成";
  if (response.task_state === "cancelled") return "這次服務已取消";
  if (response.task_state === "awaiting_user_input") {
    return response.recovery?.explanation || "需要你的協助才能繼續";
  }
  if (task.status === "failed") return "需要再試一次";
  return TASK_STATE_LABELS[response.task_state] || "等待下一步操作";
}

const STEP_STATUS_LABELS = {
  completed: "已完成",
  current: "現在進行",
  failed: "需要處理",
  pending: "稍後進行",
};

const LOCATION_LABELS = {
  "LOC-MAIN-OPD": "第一門診",
  "LOC-IMAGING-CENTER": "影像中心",
  "LOC-REHAB-01": "復康治療室",
};

const STEP_LABELS = {
  load_appointments: "確認現有預約",
  load_services: "選擇服務",
  select_service: "選擇服務",
  search_slots: "查找可預約時段",
  select_slot: "選擇時段",
  confirm_appointment: "確認預約",
  create_appointment: "提交預約",
  get_task_status: "完成預約",
};

const STATUS_LABELS = {
  booked: "已預約",
  confirmed: "已確認",
  completed: "已完成",
  free: "可預約",
};

const HIDDEN_DATA_KEYS = new Set([
  "resourceType",
  "id",
  "service_id",
  "slot_id",
  "department_id",
  "location_id",
  "task_id",
  "task_status",
  "intent",
  "intent_source",
  "booking_source",
  "tool_name",
  "step_id",
  "arguments",
  "data",
  "error",
]);

const FRIENDLY_DATA_LABELS = {
  plan_name: "計劃",
  year: "年度",
  status: "狀態",
  amount: "金額",
  currency: "貨幣",
  payment_status: "發放狀態",
  scheduled_date: "預定日期",
  title: "活動",
  summary: "簡介",
  district: "地區",
  name: "名稱",
  service_center_name: "服務中心",
  service_type: "服務類別",
  requested_date: "辦理日期",
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

function locationLabel(value) {
  if (value && typeof value === "object") {
    if (value.display) return String(value.display);
    if (value.name) return String(value.name);
    value = value.id;
  }
  return LOCATION_LABELS[String(value || "")] || "服務地點";
}

function dateOnly(value) {
  if (typeof value !== "string") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-HK", { dateStyle: "medium" }).format(date);
}

function timeOnly(value) {
  if (typeof value !== "string") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-HK", { timeStyle: "short" }).format(date);
}

function timeRange(value) {
  const start = timeOnly(value?.start);
  const end = timeOnly(value?.end);
  if (start === "—") return end;
  return end === "—" ? start : [start, end].join("–");
}

function durationLabel(minutes) {
  return Number.isFinite(Number(minutes)) ? [minutes, "分鐘"].join(" ") : "—";
}

function serviceName(service, services = []) {
  if (service && typeof service === "object") {
    return String(service.display || service.name || "醫療服務");
  }
  const match = services.find((item) => item?.id === service);
  return String(match?.name || "醫療服務");
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

function createSummaryCard(title, fields, className = "summary-card") {
  const card = createElement("article", className);
  card.append(createElement("h3", "", title));
  const list = createElement("dl");
  (fields || [])
    .filter((field) => field?.value && field.value !== "—")
    .forEach((field) => {
      list.append(
        createElement("dt", "", field.label),
        createElement("dd", "", field.value),
      );
    });
  if (!list.children.length) return null;
  card.append(list);
  return card;
}

function slotFields(slot, services) {
  const fields = [
    { label: "日期", value: dateOnly(slot?.start) },
    { label: "時間", value: timeRange(slot) },
    { label: "服務地點", value: locationLabel(slot?.location || slot?.location_id) },
  ];
  const service = services.find((item) => item?.id === slot?.service_id);
  if (service) {
    fields.unshift(
      { label: "服務", value: serviceName(service) },
      { label: "所需時間", value: durationLabel(service.duration_minutes) },
    );
  }
  return fields;
}

function renderMedicalData(container, data, response) {
  const services = Array.isArray(data.services) ? data.services : [];
  const selectedSlot = data.selected_slot && typeof data.selected_slot === "object" ? data.selected_slot : null;
  const slots = Array.isArray(data.slots) ? data.slots : [];
  const appointments = Array.isArray(data.appointments) ? data.appointments : [];

  if (data.intent === "medical_query") {
    if (appointments.length) {
      appointments.forEach((appointment, index) => {
        const card = createSummaryCard(
          serviceName(appointment.service, services) || `醫療預約 ${index + 1}`,
          [
            { label: "日期", value: dateOnly(appointment.start) },
            { label: "時間", value: timeRange(appointment) },
            { label: "服務地點", value: locationLabel(appointment.location) },
            { label: "狀態", value: STATUS_LABELS[appointment.status] || "已登記" },
          ],
        );
        if (card) container.append(card);
      });
    } else {
      container.append(createElement("div", "empty-workspace", "目前沒有已預約的醫療服務。"));
    }
    return;
  }

  if (selectedSlot) {
    const title = response?.task_state === "completed" ? "預約已完成" : "請確認預約資料";
    const service = services.find((item) => item?.id === data.service_id);
    const fields = slotFields(selectedSlot, services);
    if (service && !fields.some((field) => field.label === "所需時間")) {
      fields.splice(1, 0, { label: "所需時間", value: durationLabel(service.duration_minutes) });
    }
    const card = createSummaryCard(title, fields);
    if (card) container.append(card);
    return;
  }

  if (slots.length) {
    slots.forEach((slot, index) => {
      const card = createSummaryCard(`可預約時段 ${index + 1}`, slotFields(slot, services));
      if (card) container.append(card);
    });
    return;
  }

  if (services.length) {
    services.forEach((service) => {
      const card = createSummaryCard(serviceName(service), [
        { label: "所需時間", value: durationLabel(service.duration_minutes) },
        { label: "服務地點", value: locationLabel(service.location || service.location_id) },
      ]);
      if (card) container.append(card);
    });
    return;
  }

  if (appointments.length) {
    appointments.forEach((appointment, index) => {
      const card = createSummaryCard(
        serviceName(appointment.service, services) || `醫療預約 ${index + 1}`,
        [
          { label: "日期", value: dateOnly(appointment.start) },
          { label: "時間", value: timeRange(appointment) },
          { label: "服務地點", value: locationLabel(appointment.location) },
          { label: "狀態", value: STATUS_LABELS[appointment.status] || "已登記" },
        ],
      );
      if (card) container.append(card);
    });
    return;
  }

  if (data.intent === "medical_query") {
    container.append(createElement("div", "empty-workspace", "目前沒有已預約的醫療服務。"));
  }
}

function friendlyScalarValue(key, value) {
  if (key.includes("date")) return dateOnly(String(value));
  return displayDate(value);
}

function collectFriendlyFields(value, fields = []) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectFriendlyFields(item, fields));
    return fields;
  }
  if (!value || typeof value !== "object") return fields;

  for (const [key, item] of Object.entries(value)) {
    if (
      HIDDEN_DATA_KEYS.has(key)
      || key.endsWith("_id")
      || item === null
      || item === undefined
    ) continue;
    if (typeof item === "object") {
      collectFriendlyFields(item, fields);
      continue;
    }
    if (FRIENDLY_DATA_LABELS[key]) {
      fields.push({ label: FRIENDLY_DATA_LABELS[key], value: friendlyScalarValue(key, item) });
    }
  }
  return fields;
}

function renderFriendlyData(container, data) {
  const fields = collectFriendlyFields(data);
  const card = createSummaryCard("服務資料", fields);
  if (card) container.append(card);
}

function renderData(container, data, response) {
  if (!data || typeof data !== "object" || Object.keys(data).length === 0) {
    container.append(createElement("div", "empty-workspace", "完成這一步後，相關資料會顯示在這裡。"));
    return;
  }

  if (data.services || data.slots || data.selected_slot || data.appointments || data.intent === "medical_query") {
    renderMedicalData(container, data, response);
  } else {
    renderFriendlyData(container, data);
  }

  if (!container.children.length) {
    container.append(createElement("div", "empty-workspace", "完成這一步後，相關資料會顯示在這裡。"));
  }
}

function renderSteps(container, steps, currentStep) {
  container.replaceChildren();
  (steps || []).forEach((step, index) => {
    const rawStatus = step.status || (step.ok === false ? "failed" : step.ok === true ? "completed" : "pending");
    const status = rawStatus === "pending" && step.step_id === currentStep ? "current" : rawStatus;
    const item = createElement("li", `task-step is-${status}`);
    item.append(
      createElement("span", "task-step-marker", status === "completed" ? "✓" : String(index + 1)),
      createElement("span", "task-step-label", STEP_LABELS[step.step_id] || "服務步驟"),
      createElement("span", "task-step-status", STEP_STATUS_LABELS[status] || "尚未開始"),
    );
    container.append(item);
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
  const date = dateOnly(slot.start);
  const range = timeRange(slot);
  const location = locationLabel(slot.location || slot.location_id);
  if (date === "—" && range === "—") return "可預約時段";
  return [date, range, location].filter((value) => value !== "—").join("｜");
}

const MOCK_REFERRAL_ID = "APT-REF-1";

function actionKind(action) {
  return action.kind || action.action || action.id || "";
}

function createReferralControl(data) {
  const field = createElement("label", "referral-field");
  field.append(createElement("span", "date-field-label", "關聯門診／轉介編號"));

  const appointmentOptions = (Array.isArray(data.appointments) ? data.appointments : [])
    .map((appointment) => ({
      id: appointment?.id,
      label: [
        serviceName(appointment?.service),
        dateOnly(appointment?.start),
      ].join("｜"),
    }))
    .filter((option) => typeof option.id === "string" && option.id.trim());
  let control;
  if (appointmentOptions.length > 0) {
    control = createElement("select");
    control.name = "referring_appointment_id";
    appointmentOptions.forEach((appointment) => {
      const option = createElement("option", "", appointment.label);
      option.value = appointment.id;
      control.append(option);
    });
  } else {
    control = createElement("input");
    control.type = "text";
    control.name = "referring_appointment_id";
    control.value = MOCK_REFERRAL_ID;
    control.placeholder = MOCK_REFERRAL_ID;
  }
  field.append(control);
  return control;
}

function renderGenericActions(container, actions, onAction, prepareAction = (action) => action) {
  (actions || []).forEach((action) => {
    const kind = actionKind(action) || "action";
    const button = createElement("button", "action-button", action.label || "繼續");
    button.type = "button";
    if (kind === "confirm") button.classList.add("is-confirm");
    if (kind === "cancel" || kind === "human_help") button.classList.add("is-danger");
    button.addEventListener("click", () => onAction(prepareAction(action)));
    container.append(button);
  });
}

function renderConfirmationActions(container, response, onAction) {
  const data = response?.data && typeof response.data === "object" ? response.data : {};
  const referralControl = createReferralControl(data);
  container.append(referralControl.closest("label"));
  container.append(createElement("p", "field-help", "需要轉介資料才能完成預約。"));
  renderGenericActions(container, response?.actions, onAction, (action) => {
    if (actionKind(action) !== "confirm") return action;
    return {
      ...action,
      payload: {
        ...(action.payload || {}),
        referring_appointment_id: referralControl.value.trim(),
      },
    };
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
      const serviceNameText = serviceName(service);
      const label = [
        serviceNameText,
        durationLabel(service.duration_minutes),
        locationLabel(service.location || service.location_id),
      ].join("｜");
      const button = createElement("button", "action-button", label);
      button.type = "button";
      button.addEventListener("click", () => onAction({
        kind: "search_slots",
        label: `搜尋${serviceNameText}時段`,
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

  if (response?.current_step === "confirm_appointment") {
    renderConfirmationActions(container, response, onAction);
    return;
  }

  renderGenericActions(container, response?.actions, onAction);
}

function renderRecovery(container, recovery) {
  if (!recovery || typeof recovery !== "object") return;
  const panel = createElement("section", "recovery-panel");
  panel.setAttribute("role", "status");
  panel.append(createElement("h3", "recovery-title", "下一步怎樣做"));
  if (typeof recovery.explanation === "string" && recovery.explanation) {
    panel.append(createElement("p", "recovery-explanation", recovery.explanation));
  }
  const fields = Array.isArray(recovery.required_fields) ? recovery.required_fields : [];
  fields.forEach((field) => {
    const label = typeof field?.label === "string" && field.label ? field.label : "必要資料";
    panel.append(createElement("p", "recovery-field", `需要補充：${label}`));
  });
  container.append(panel);
}

export function createInteractionView({
  conversationRoot,
  healthRoot,
  taskListRoot,
  errorRoot,
  onAction,
}) {
  /** @typedef {Object} TaskRecord */
  const tasks = [];
  let taskSequence = 0;
  let activeTaskId = null;

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

  function findTask(taskId) {
    return tasks.find((task) => task.localId === taskId || task.backendTaskId === taskId) || null;
  }

  function renderTaskList() {
    taskListRoot.replaceChildren();
    tasks.forEach((task) => {
      const card = createElement("details");
      card.className = `task-card is-${task.status}`;
      card.open = Boolean(task.expanded);
      card.addEventListener("toggle", () => {
        task.expanded = card.open;
      });

      const summary = createElement("summary", "task-card-summary");
      const response = task.response || {};
      const statusLabel = TASK_STATE_LABELS[response.task_state] || "正在處理";
      summary.append(
        createElement("span", "task-card-title", task.title),
        createElement("span", "task-card-state", statusLabel),
        createElement("span", "task-card-teaser", taskTeaser(task)),
      );
      card.append(summary);

      const body = createElement("div", "task-card-body");
      const progress = createElement("div", "task-summary");
      progress.append(
        createElement("span", "task-summary-label", "目前進度"),
        createElement("strong", "", statusLabel),
      );
      body.append(progress);

      if (task.response) {
        const steps = createElement("ol", "task-steps");
        steps.setAttribute("aria-label", "服務流程");
        renderSteps(steps, response.steps, response.current_step);
        body.append(steps);

        const data = createElement("div", "task-content");
        renderData(data, response.data, response);
        body.append(data);

        if (response.error?.message) {
          body.append(createElement("div", "alert alert-error", response.error.message));
        }

        if (response.recovery) {
          const recovery = createElement("div", "recovery-content");
          renderRecovery(recovery, response.recovery);
          body.append(recovery);
        }

        const actions = createElement("div", "action-list");
        actions.setAttribute("aria-label", "可以進行的操作");
        if (!TERMINAL_TASK_STATES.has(response.task_state)) {
          renderActions(actions, response, (action) => onAction(action, task.localId));
        }
        body.append(actions);
      } else {
        body.append(createElement("div", "empty-workspace", "正在準備服務資料…"));
      }
      card.append(body);
      taskListRoot.append(card);
    });
  }

  function startTask({ channel = "text", value = "", taskId = null } = {}) {
    const localId = taskId || `UI-TASK-${++taskSequence}`;
    tasks.forEach((task) => {
      task.expanded = false;
    });
    tasks.push({
      localId,
      backendTaskId: null,
      title: taskTitle(value),
      channel,
      value,
      status: "running",
      taskState: "querying",
      currentStep: "welcome",
      response: null,
      expanded: true,
    });
    activeTaskId = localId;
    renderTaskList();
    return localId;
  }

  function updateTask(taskId, response) {
    const task = findTask(taskId);
    if (!task) return;
    const nextResponse = response && typeof response === "object" ? response : {};
    task.response = nextResponse;
    task.taskState = nextResponse.task_state || "querying";
    task.currentStep = nextResponse.current_step || "welcome";
    task.status = taskStatus(task.taskState);
    task.backendTaskId = typeof nextResponse.task_id === "string" ? nextResponse.task_id : task.backendTaskId;
    task.expanded = !TERMINAL_TASK_STATES.has(task.taskState);
    if (nextResponse.assistant_message) appendMessage("assistant", nextResponse.assistant_message);
    clearError();
    renderTaskList();
  }

  function continueTask(taskId, input = {}) {
    const task = findTask(taskId);
    if (!task) return false;
    task.channel = input.channel || task.channel;
    task.value = input.value ?? task.value;
    task.status = "running";
    task.expanded = true;
    activeTaskId = task.localId;
    renderTaskList();
    return true;
  }

  function toggleTask(taskId) {
    const task = findTask(taskId);
    if (!task) return false;
    task.expanded = !task.expanded;
    renderTaskList();
    return task.expanded;
  }

  function failTask(taskId, error) {
    const task = findTask(taskId);
    if (!task) return;
    task.status = "failed";
    task.taskState = "failed";
    task.expanded = false;
    task.response = {
      ...(task.response || {}),
      task_state: "failed",
      current_step: task.currentStep,
      steps: task.response?.steps || [],
      data: task.response?.data || {},
      actions: [],
      error: { message: error?.message || "暫時未能完成這一步，你可以再試一次。" },
    };
    renderTaskList();
  }

  function renderHealth(payload) {
    const reachable = payload.backend_reachable !== false;
    healthRoot.classList.toggle("is-ready", reachable);
    healthRoot.classList.toggle("is-offline", !reachable);
    healthRoot.textContent = reachable
      ? "服務已連線"
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
    startTask,
    updateTask,
    continueTask,
    toggleTask,
    failTask,
    renderHealth,
    renderError,
    clearError,
  };
}
