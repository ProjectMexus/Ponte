import { renderWorkspace as renderCanonicalWorkspace } from "./interaction-view.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function valueText(value) {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) return value.map(valueText).filter(Boolean).join(" · ");
  if (typeof value === "object") return Object.values(value).map(valueText).filter(Boolean).join(" · ");
  return String(value);
}

function canonicalReceiptFields(receipt) {
  const appointment = receipt?.appointment || {};
  return [
    ["Service", appointment.service],
    ["Date", appointment.date],
    ["Time", appointment.time],
    ["Location", appointment.location],
    ["Status", appointment.status || receipt?.status],
    ["Issued", receipt?.issued_at],
    ["Task", receipt?.task_id],
  ].filter(([, value]) => valueText(value));
}

function appendReceiptFields(container, receipt) {
  const list = element("dl", "voice-facts");
  canonicalReceiptFields(receipt).forEach(([label, value]) => {
    const row = element("div", "voice-fact");
    row.append(element("dt", "", label), element("dd", "", valueText(value)));
    list.append(row);
  });
  if (list.children.length) container.append(list);
}

function renderWorkspaceCard(container, workspace, onAction) {
  if (!workspace || typeof workspace !== "object") return;
  const childCount = container.children.length;
  renderCanonicalWorkspace(container, workspace, onAction);
  const card = container.children[childCount];
  if (!card) return;
  card.classList.add("voice-exception-card");
  // The first server action is the expected next step for the user.
  card.querySelector(".action-button")?.classList.add("is-primary");
}

function renderRecovery(container, recovery) {
  if (!recovery || typeof recovery !== "object") return;
  const panel = element("section", "recovery-panel voice-exception-card");
  panel.setAttribute("role", "status");
  panel.append(element("h3", "recovery-title", "Recovery"));
  if (recovery.reason) panel.append(element("p", "recovery-explanation", String(recovery.reason)));
  container.append(panel);
}

// Informational cards (no actions) fade away on their own; decision cards
// stay until the user acts or dismisses them.
const AUTO_DISMISS_MS = 10000;

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

  function dismissCard(card) {
    if (!card?.isConnected || card.classList.contains("is-leaving")) return;
    if (card.dismissTimer) { clearTimeout(card.dismissTimer); card.dismissTimer = null; }
    card.classList.add("is-leaving");
    const remove = () => {
      if (!card.isConnected) return;
      card.remove();
      syncExceptionSurface();
    };
    card.addEventListener("animationend", remove, { once: true });
    card.dismissTimer = setTimeout(remove, 340);
  }

  function dismissAll() {
    Array.from(approvalRoot?.children || []).forEach(dismissCard);
    clearError();
  }

  // Toast-like behaviour for informational cards: auto-dismiss, but pause
  // while the user is reading (hover or keyboard focus).
  function scheduleAutoDismiss(card) {
    const start = () => {
      if (!card.isConnected || card.classList.contains("is-leaving") || card.dismissTimer) return;
      card.dismissTimer = setTimeout(() => dismissCard(card), AUTO_DISMISS_MS);
    };
    const pause = () => {
      if (card.dismissTimer) { clearTimeout(card.dismissTimer); card.dismissTimer = null; }
    };
    card.addEventListener("pointerenter", pause);
    card.addEventListener("focusin", pause);
    card.addEventListener("pointerleave", start);
    card.addEventListener("focusout", start);
    start();
  }

  function addDismiss(card, { interactive } = {}) {
    if (!card?.isConnected || card.querySelector(".exception-close")) return;
    const closeButton = element("button", "exception-close", "\u00d7");
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "Close");
    closeButton.addEventListener("click", () => dismissCard(card));
    card.append(closeButton);
    if (interactive) card.querySelector(".action-button, .exception-button")?.focus();
    else scheduleAutoDismiss(card);
  }

  function renderError(error) {
    if (!errorRoot) return;
    clearTimeout(errorTimer);
    errorRoot.hidden = false;
    errorRoot.textContent = error?.message || "The service could not complete this turn.";
    syncExceptionSurface();
    errorTimer = setTimeout(clearError, 8000);
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
    artifactContentRoot.append(element("p", "artifact-status", "Service completed"));
    appendReceiptFields(artifactContentRoot, receipt);
    artifactContentRoot.append(element("p", "artifact-reference", `Reference: ${receipt.receipt_id || "—"}`));
    artifactRoot.hidden = false;
    document.body.classList.add("artifact-open");
    artifactRoot.querySelector("[data-artifact-close]")?.focus();
  }

  function renderWorkspace(response) {
    if (!approvalRoot) return;
    approvalRoot.replaceChildren();
    renderWorkspaceCard(approvalRoot, response?.workspace, onAction);
    if (!approvalRoot.children.length) renderRecovery(approvalRoot, response?.recovery);
    Array.from(approvalRoot.children).forEach((card) => {
      const interactive = Boolean(card.querySelector(".action-button, .exception-button"));
      addDismiss(card, { interactive });
    });
    syncExceptionSurface();
  }

  // Kept as the delivery-surface hook used by the avatar app. It renders only
  // the canonical workspace projection; confirmation decisions arrive inside
  // workspace.actions[].event and are never created in the browser.
  function renderApproval(response) {
    renderWorkspace(response);
  }

  function renderReceipt(receipt) {
    if (!approvalRoot || !receipt) return;
    lastReceipt = receipt;
    const card = element("section", "voice-exception-card receipt-card");
    card.append(element("p", "exception-kicker", "Action receipt"));
    card.append(element("h2", "", "Your receipt is ready"));
    const button = element("button", "exception-button is-primary", "View receipt");
    button.type = "button";
    button.addEventListener("click", () => openArtifact(receipt));
    card.append(button);
    approvalRoot.append(card);
    addDismiss(card, { interactive: true });
    syncExceptionSurface();
  }

  function renderResponse(response) {
    clearError();
    renderApproval(response);
    if (response?.receipt) renderReceipt(response.receipt);
    syncExceptionSurface();
  }

  artifactRoot?.querySelectorAll("[data-artifact-close]").forEach((button) => button.addEventListener("click", closeArtifact));
  artifactRoot?.querySelector("#artifact-print")?.addEventListener("click", () => window.print());
  artifactRoot?.querySelector("#artifact-download")?.addEventListener("click", () => {
    const body = artifactContentRoot?.cloneNode(true).outerHTML || "";
    const html = `<!doctype html><html lang="en"><meta charset="utf-8"><title>Ponte receipt</title><body>${body}</body></html>`;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    link.download = `ponte-receipt-${lastReceipt?.receipt_id || "service"}.html`;
    link.click();
    URL.revokeObjectURL(link.href);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (artifactRoot && !artifactRoot.hidden) { closeArtifact(); return; }
    dismissAll();
  });
  exceptionSurface?.addEventListener("pointerdown", (event) => {
    if (event.target.closest?.(".voice-exception-card, .voice-error")) return;
    dismissAll();
  });

  return { clearError, renderError, renderResponse, renderWorkspace, renderApproval, renderReceipt, openArtifact, closeArtifact };
}
