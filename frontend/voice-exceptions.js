function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function actionKind(action) {
  return action?.kind || action?.action || action?.id || "";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "object") return Object.values(value).filter(Boolean).join(" · ");
  return String(value);
}

function addFactList(container, facts) {
  const list = element("dl", "voice-facts");
  facts.filter(([, value]) => formatValue(value)).forEach(([label, value]) => {
    const row = element("div", "voice-fact");
    row.append(element("dt", "", label), element("dd", "", formatValue(value)));
    list.append(row);
  });
  if (list.children.length) container.append(list);
}

function receiptFacts(receipt) {
  const result = [];
  for (const [key, value] of Object.entries(receipt || {})) {
    if (value === null || value === undefined || value === "" || key === "receipt_id") continue;
    if (typeof value === "object") {
      for (const [childKey, childValue] of Object.entries(value)) {
        if (childValue !== null && childValue !== undefined && childValue !== "") {
          result.push([childKey.replaceAll("_", " "), childValue]);
        }
      }
    } else {
      result.push([key.replaceAll("_", " "), value]);
    }
  }
  return result;
}

function inputDateValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function serviceLabel(service) {
  const name = service?.name_zh || service?.name || service?.name_en || service?.id || "可預約服務";
  const details = [service?.duration_minutes ? `${service.duration_minutes} 分鐘` : "", service?.location?.name || service?.location || service?.location_id || ""].filter(Boolean);
  return [name, ...details].join("｜");
}

function slotLabel(slot) {
  const values = [slot?.start || slot?.start_time, slot?.end || slot?.end_time].filter(Boolean);
  const range = values.map((value) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString("zh-HK", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false});
  }).join(" – ");
  return [range || "可預約時段", slot?.location?.name || slot?.location || slot?.location_id].filter(Boolean).join("｜");
}

function actionButton(action, onAction) {
  const kind = actionKind(action);
  const button = element("button", `exception-button ${/confirm|approve|select_slot|search_slots/.test(kind) ? "is-primary" : ""}`, action?.label || "繼續");
  button.type = "button";
  button.addEventListener("click", () => onAction?.({...action, payload: {...(action?.payload || {})}}));
  return button;
}

export function createVoiceExceptions({ approvalRoot, errorRoot, artifactRoot, artifactContentRoot, onAction } = {}) {
  let lastReceipt = null;
  let lastFocusedElement = null;
  let errorTimer = null;
  const exceptionSurface = approvalRoot?.closest(".voice-exceptions");

  function syncExceptionSurface() {
    exceptionSurface?.classList.toggle("has-modal", Boolean(
      approvalRoot?.children.length || (errorRoot && !errorRoot.hidden),
    ));
  }

  function clearError() {
    clearTimeout(errorTimer);
    errorTimer = null;
    if (!errorRoot) return;
    errorRoot.hidden = true;
    errorRoot.replaceChildren();
    syncExceptionSurface();
  }

  function renderError(error) {
    if (!errorRoot) return;
    clearTimeout(errorTimer);
    errorRoot.hidden = false;
    errorRoot.textContent = error?.message || "暫時未能完成這次服務，請再試一次。";
    syncExceptionSurface();
    errorTimer = setTimeout(() => {
      clearError();
    }, 8000);
  }

  function closeArtifact() {
    if (!artifactRoot) return;
    artifactRoot.hidden = true;
    document.body.classList.remove("artifact-open");
    lastFocusedElement?.focus?.();
  }

  function openArtifact(receipt = lastReceipt) {
    if (!artifactRoot || !artifactContentRoot || !receipt) return;
    lastReceipt = receipt;
    lastFocusedElement = document.activeElement;
    artifactContentRoot.replaceChildren();
    artifactContentRoot.append(element("p", "artifact-status", "服務已完成"));
    addFactList(artifactContentRoot, receiptFacts(receipt));
    artifactContentRoot.append(element("p", "artifact-reference", `參考編號：${receipt.receipt_id || "—"}`));
    if (typeof receipt.html === "string" && receipt.html.trim()) artifactContentRoot.innerHTML = receipt.html;
    artifactRoot.hidden = false;
    document.body.classList.add("artifact-open");
    artifactRoot.querySelector("[data-artifact-close]")?.focus();
  }

  function renderApproval(response) {
    if (!approvalRoot) return;
    approvalRoot.replaceChildren();
    const approval = response?.approval;
    const actions = Array.isArray(response?.actions) ? [...response.actions] : [];
    const needsApproval = Boolean(approval) || response?.task_state === "awaiting_confirmation"
      || actions.some((action) => /confirm|approve|cancel/.test(actionKind(action)));
    if (!needsApproval || (actions.length === 0 && !approval)) return;

    const card = element("section", "voice-exception-card approval-card");
    if (approval?.summary) card.append(element("p", "approval-summary", approval.summary));
    if (approval?.risk_level) card.append(element("p", "approval-risk", `Risk ${approval.risk_level}`));
    card.append(element("p", "exception-kicker", "需要你的確認"));
    card.append(element("h2", "", "請確認這項服務安排"));
    const data = response?.data && typeof response.data === "object" ? response.data : {};
    const proposed = data.proposed_appointment || data.selected_slot || {};
    const current = data.current_appointment || {};
    addFactList(card, [
      ["新安排", [proposed.date || proposed.start, proposed.time, proposed.doctor || proposed.service?.name].filter(Boolean).join(" · ")],
      ["原有安排", [current.date || current.start, current.time, current.doctor || current.service?.name].filter(Boolean).join(" · ")],
    ]);
    const confirmActionExists = actions.some((action) => /confirm|approve/.test(actionKind(action)));
    let referralControl = null;
    if (confirmActionExists) {
      const appointments = Array.isArray(data.appointments) ? data.appointments : [];
      const field = element("label", "voice-date-field referral-field");
      field.append(element("span", "", "關聯門診／轉介編號"));
      if (appointments.length) {
        referralControl = element("select");
        appointments.forEach((appointment) => {
          if (!appointment?.id) return;
          const option = element("option", "", [appointment.service?.display || appointment.service?.name || "門診", slotLabel(appointment)].join("｜"));
          option.value = appointment.id;
          referralControl.append(option);
        });
      } else {
        referralControl = element("input");
        referralControl.type = "text";
        referralControl.placeholder = "請輸入轉介編號";
      }
      referralControl.name = "referring_appointment_id";
      field.append(referralControl);
      card.append(field);
    }
    const buttons = element("div", "exception-actions");
    actions.forEach((action) => {
      const kind = actionKind(action);
      if (!kind || kind === "request_human_help" || kind === "human_help") return;
      const button = element("button", `exception-button ${/confirm|approve/.test(kind) ? "is-primary" : ""}`, action.label || "繼續");
      button.type = "button";
      button.addEventListener("click", () => {
        const prepared = {...action, payload: {...(action.payload || {})}};
        if (/confirm|approve/.test(kind) && referralControl?.value?.trim()) {
          prepared.payload.referring_appointment_id = referralControl.value.trim();
        }
        onAction?.(prepared);
      });
      buttons.append(button);
    });
    if (buttons.children.length) card.append(buttons);
    approvalRoot.append(card);
    syncExceptionSurface();
  }

  function renderTaskInteraction(response) {
    if (!approvalRoot) return false;
    const data = response?.data && typeof response.data === "object" ? response.data : {};
    const actions = Array.isArray(response?.actions) ? response.actions : [];
    const selectingService = response?.task_state === "selecting_service" || response?.current_step === "select_service";
    const selectingSlot = response?.task_state === "selecting_slot" || response?.current_step === "select_slot";
    const recovery = response?.recovery && typeof response.recovery === "object" ? response.recovery : null;
    if (!selectingService && !selectingSlot && !recovery) return false;

    approvalRoot.replaceChildren();
    const card = element("section", "voice-exception-card task-choice-card");
    card.append(element("p", "exception-kicker", recovery ? "需要你的協助" : "選擇下一步"));
    card.append(element("h2", "", selectingService ? "選擇服務及日期" : selectingSlot ? "選擇預約時段" : "下一步怎樣做"));
    if (recovery?.explanation) card.append(element("p", "recovery-explanation", recovery.explanation));
    (Array.isArray(recovery?.required_fields) ? recovery.required_fields : []).forEach((field) => card.append(element("p", "recovery-field", `需要補充：${field?.label || "必要資料"}`)));

    const buttons = element("div", "exception-actions task-choice-actions");
    if (selectingService) {
      const range = element("div", "voice-date-range");
      const today = new Date();
      const end = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 14);
      const dateFrom = element("input");
      dateFrom.type = "date";
      dateFrom.value = inputDateValue(today);
      const dateTo = element("input");
      dateTo.type = "date";
      dateTo.value = inputDateValue(end);
      const fromLabel = element("label", "voice-date-field");
      fromLabel.append(element("span", "", "開始日期"), dateFrom);
      const toLabel = element("label", "voice-date-field");
      toLabel.append(element("span", "", "結束日期"), dateTo);
      range.append(fromLabel, toLabel);
      card.append(range);
      (Array.isArray(data.services) ? data.services : []).forEach((service) => {
        buttons.append(actionButton({kind: "search_slots", label: serviceLabel(service), payload: {service_id: service.id, date_from: dateFrom.value, date_to: dateTo.value}}, (action) => {
          action.payload.date_from = dateFrom.value;
          action.payload.date_to = dateTo.value;
          onAction?.(action);
        }));
      });
    } else if (selectingSlot) {
      (Array.isArray(data.slots) ? data.slots : []).forEach((slot) => buttons.append(actionButton({kind: "select_slot", label: slotLabel(slot), payload: {slot_id: slot.id}}, onAction)));
    }
    actions.forEach((action) => {
      const kind = actionKind(action);
      if (!kind || (selectingService && kind === "search_slots") || (selectingSlot && kind === "select_slot")) return;
      buttons.append(actionButton(action, onAction));
    });
    if (buttons.children.length) card.append(buttons);
    else card.append(element("p", "empty-choice", "目前沒有可用選項。"));
    approvalRoot.append(card);
    syncExceptionSurface();
    return true;
  }

  function renderReceipt(receipt) {
    if (!approvalRoot || !receipt) return;
    lastReceipt = receipt;
    const card = element("section", "voice-exception-card receipt-card");
    card.append(element("p", "exception-kicker", "服務完成"));
    card.append(element("h2", "", "你的收據已準備好"));
    const button = element("button", "exception-button is-primary", "查看收據");
    button.type = "button";
    button.addEventListener("click", () => openArtifact(receipt));
    card.append(button);
    approvalRoot.append(card);
    syncExceptionSurface();
  }

  function renderResponse(response) {
    clearError();
    if (!renderTaskInteraction(response)) renderApproval(response);
    if (response?.receipt || response?.artifact) renderReceipt(response.receipt || response.artifact);
    syncExceptionSurface();
  }

  artifactRoot?.querySelectorAll("[data-artifact-close]").forEach((button) => button.addEventListener("click", closeArtifact));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && artifactRoot && !artifactRoot.hidden) closeArtifact();
  });
  return { clearError, renderError, renderResponse, openArtifact, closeArtifact };
}
