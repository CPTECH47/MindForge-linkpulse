"use strict";

document.querySelectorAll("[data-autosubmit]").forEach(select => select.addEventListener("change", () => select.form.requestSubmit()));
document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = "Copied ✓";
  } catch {
    // A selectable field is usable on non-secure LAN previews where Clipboard is unavailable.
    const input = document.createElement("input");
    input.value = button.dataset.copy;
    input.setAttribute("aria-label", "Select and copy this short URL");
    button.after(input);
    input.select();
    button.textContent = "Select & copy";
    return;
  }
  setTimeout(() => { button.textContent = original; }, 1800);
}));

const form = document.querySelector("#link-form");
if (form) {
  const isEditing = form.dataset.editing === "true";
  const steps = [...form.querySelectorAll("[data-step]")];
  const next = document.querySelector("#wizard-next");
  const back = document.querySelector("#wizard-back");
  const publish = document.querySelector("#publish-link");
  const hasErrors = form.querySelector(".errorlist");
  let current = 1;
  const updateReview = () => {
    document.querySelector("#review-summary").textContent = `Review: ${form.elements.title.value} → ${form.elements.destination.value}. ${form.elements.max_clicks.value ? `Limit: ${form.elements.max_clicks.value} redirects.` : "Unlimited redirects."}`;
  };
  form.addEventListener("input", updateReview);
  const show = value => {
    current = value;
    steps.forEach(step => { step.hidden = Number(step.dataset.step) !== value; });
    document.querySelector("#step-label-1").classList.toggle("selected", value === 1);
    document.querySelector("#step-label-2").classList.toggle("selected", value === 2);
    back.hidden = value === 1;
    next.hidden = value === 2;
    publish.hidden = value === 1;
    if (value === 2) {
      updateReview();
    }
  };
  if (!hasErrors && !isEditing) show(1);
  else { next.hidden = true; back.hidden = true; }
  next.addEventListener("click", () => {
    const invalid = [...steps[0].querySelectorAll("input,select")].find(input => !input.checkValidity());
    if (invalid) { invalid.reportValidity(); return; }
    show(2);
  });
  back.addEventListener("click", () => show(1));
  form.addEventListener("submit", () => {
    // Unhide all fields so native validation can focus any invalid control.
    steps.forEach(step => { step.hidden = false; });
  });
  document.querySelector("#validate-link").addEventListener("click", async () => {
    const result = document.querySelector("#preview-result");
    result.className = "notice";
    result.textContent = "Checking destination and rules…";
    try {
      const response = await fetch(form.dataset.preview, { method: "POST", body: new FormData(form), credentials: "same-origin", headers: { "X-CSRFToken": form.elements.csrfmiddlewaretoken.value } });
      const data = await response.json();
      result.textContent = data.valid ? [data.message, ...data.warnings].join(" ") : Object.entries(data.errors).map(([field, errors]) => `${field}: ${errors.map(item => item.message).join(" ")}`).join(" · ");
      result.classList.toggle("error", !data.valid);
    } catch { result.textContent = "Validation is unavailable. You can retry or submit for server validation."; }
  });
}
