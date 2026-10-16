const $ = (id) => document.getElementById(id);
let dirty = false;
let queuedItems = [];
let reusableDrafts = [];
let savedProcedure = null;
let guidedActive = false;
let guidedInspected = false;
let guidedSessionId = null;
let guidedStarting = false;
let guidedInitialized = false;
let guidedStatusText = "The guided demo has not started.";
let session = null,
  sessions = [],
  moments = [],
  recorder = null,
  stream = null,
  chunks = [],
  recordingStarted = 0,
  timer = null;
const basePrompts = [
  ["account", "Which account or workspace should be selected?"],
  ["done", "What proves the task is finished?"],
  ["stop", "When should your agent stop and ask you?"],
];
let prompts = [...basePrompts];
const defaultSteps = [];
const practiceSteps = [
  {goal: "Select the requested media", check: "Media receives the requested filename", action: "select_media", target: "Media", input: "filename"},
  {goal: "Enter the supplied caption", check: "Caption contains fresh text", action: "fill", target: "Caption", input: "caption"},
  {goal: "Save the draft", check: "Saved receipt appears", action: "click", target: "Save draft"},
  {goal: "Verify retained draft", check: "Draft id and both inputs match retained storage", action: "verify_draft"},
];
function collectSteps() {
  return [...$("steps").querySelectorAll(".step")].map(d => {
    const step = {goal: d.querySelector('[data-field="goal"]').value, check: d.querySelector('[data-field="check"]').value};
    const action = d.querySelector('[data-field="action"]').value;
    if (action) {
      step.action = action;
      if (action !== "verify_draft") step.target = d.querySelector('[data-field="target"]').value;
      if (action === "upload" || action === "select_media") step.input = "filename";
      if (action === "fill") step.input = "caption";
    }
    return step;
  });
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  setTimeout(() => $("toast").classList.remove("show"), 3500);
}
function guidedMessage(message) {
  guidedStatusText = message;
  $("guidedStatus").textContent = message;
}
function safeTrialFailure(message) {
  const value = String(message || "");
  if (/bundled browser unavailable|playwright|chromium|browser could not start|executable doesn't exist/i.test(value)) {
    return "The practice browser is unavailable. Run `holdmybeer doctor`; if Chromium is missing, install it in the same Python environment with `python -m playwright install chromium`, then retry.";
  }
  if (/failed to fetch|networkerror|load failed|connection refused|could not reach/i.test(value)) {
    return "Could not reach the local workspace. Check that HoldMyBeer is still running on its loopback preview, then refresh and retry.";
  }
  if (/traceback|exception|no module named|\.py:\d+/i.test(value)) {
    return "The local trial hit a runtime error. Run `holdmybeer doctor`, check the local server log for details, repair the reported issue, then retry.";
  }
  return value.slice(0, 300) || "The trial did not verify. Review the checkpoint evidence, repair the local setup, then authorize and retry.";
}
async function api(path, options = {}) {
  const r = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!r.ok) {
    if (r.status >= 500) throw Error("The local workspace returned an error. Check its local server log and retry.");
    const raw = await r.text();
    let d;
    try {
      d = JSON.parse(raw);
    } catch {
      d = { detail: raw };
    }
    throw Error(
      typeof d.detail === "string" ? d.detail : `Request failed (${r.status})`,
    );
  }
  return r.json();
}
function textEl(tag, text, className) {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  return el;
}
function formatTime(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
function setTab(name) {
  document
    .querySelectorAll(".tab-panel")
    .forEach((p) => (p.hidden = p.id !== name));
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
  });
  $("guidedConfirmInspect").disabled = !guidedActive || name !== "teach" || guidedInspected;
}
document
  .querySelectorAll("[data-tab]")
  .forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));
function renderNav() {
  const nav = $("sessions");
  nav.replaceChildren();
  for (const s of sessions) {
    const b = textEl("button", s.title, s.id === session?.id ? "selected" : "");
    b.onclick = () => selectSession(s.id);
    nav.append(b);
  }
}
function renderQuestions() {
  const box = $("questions");
  box.replaceChildren();
  for (const [key, prompt] of prompts) {
    const d = textEl("div", "", "question");
    const l = textEl("label", prompt);
    l.htmlFor = `answer-${key}`;
    const a = document.createElement("textarea");
    a.id = `answer-${key}`;
    a.value = session.answers?.[key] || "";
    a.placeholder = "Add your guidance…";
    d.append(l, a);
    box.append(d);
  }
}
function renderSteps() {
  const box = $("steps");
  box.replaceChildren();
  for (const [i, step] of (session.procedure?.steps?.length
    ? session.procedure.steps
    : defaultSteps
  ).entries()) {
    const d = textEl("div", "", "step");
    for (const [field, label] of [
      ["goal", `${String(i + 1).padStart(2, "0")} / ACTION`],
      ["check", "SUCCESS CHECK"],
    ]) {
      const l = textEl("label", label);
      l.htmlFor = `step-${i}-${field}`;
      const inp = document.createElement("input");
      inp.id = l.htmlFor;
      inp.dataset.field = field;
      inp.value = step[field] || "";
      d.append(l, inp);
    }
    const label = textEl("label", "EXECUTABLE ACTION");
    label.htmlFor = `step-${i}-action`;
    const action = document.createElement("select");
    action.id = label.htmlFor;
    action.dataset.field = "action";
    for (const [value, name] of [["", "Notes only"], ["select_media", "Select media by filename"], ["upload", "Upload fresh file (legacy)"], ["fill", "Fill fresh caption"], ["click", "Click exact button"], ["verify_draft", "Verify retained draft"]]) {
      const option = textEl("option", name); option.value = value; action.append(option);
    }
    action.value = step.action || "";
    const targetLabel = textEl("label", "EXACT LABEL / BUTTON NAME");
    targetLabel.htmlFor = `step-${i}-target`;
    const target = document.createElement("input"); target.id = targetLabel.htmlFor;
    target.dataset.field = "target"; target.value = step.target || "";
    const updateTarget = () => { target.disabled = !action.value || action.value === "verify_draft"; $("reviewed").checked = false; };
    action.onchange = updateTarget;
    updateTarget();
    const remove = textEl("button", "Remove step", "quiet");
    remove.type = "button";
    remove.onclick = () => { session.procedure.steps = collectSteps().filter((_, n) => n !== i); dirty = true; renderSteps(); };
    d.append(label, action, targetLabel, target, remove);
    box.append(d);
  }
  $("revision").textContent = session.procedure?.revision || 1;
}
async function renderProcedureHistory() {
  const id = session.id;
  const box = $("procedureHistory");
  box.replaceChildren(textEl("p", "Loading saved revisions…", "muted"));
  async function page(before) {
    const data = await api(`/api/sessions/${id}/procedure-revisions${before ? `?before_revision=${before}` : ""}`);
    if (session.id !== id) return;
    if (!before) box.replaceChildren();
    for (const entry of data.revisions) {
      const details = document.createElement("details");
      details.append(textEl("summary", `Revision ${entry.procedure.revision} · ${entry.source === "legacy_current" ? "retained at upgrade" : "saved"} ${new Date(entry.saved_at).toLocaleString()}`));
      const steps = document.createElement("ol");
      for (const step of entry.procedure.steps) {
        steps.append(textEl("li", `${step.goal}${step.target ? ` — ${step.target}` : ""}. Check: ${step.check}`));
      }
      details.append(steps);
      if (!entry.procedure.steps.length) details.append(textEl("p", "No steps saved in this revision.", "muted"));
      box.append(details);
    }
    if (data.next_before_revision) {
      const more = textEl("button", "Older revisions", "quiet");
      more.onclick = async () => {
        more.disabled = true;
        try { await page(data.next_before_revision); more.remove(); }
        catch (error) { more.disabled = false; toast(error.message); }
      };
      box.append(more);
    }
  }
  try { await page(); }
  catch (error) { if (session.id === id) box.replaceChildren(textEl("p", `Could not load history: ${error.message}`)); }
}
function renderMoments() {
  const box = $("moments");
  box.replaceChildren();
  $("momentCount").textContent = `${moments.length} marked`;
  if (!moments.length) {
    box.append(
      textEl(
        "p",
        "Pause your video at a decision and mark the moment.",
        "empty",
      ),
    );
    return;
  }
  moments.forEach((m, i) => {
    const row = textEl("div", "", "moment");
    const seek = textEl("button", formatTime(m.time));
    seek.onclick = () => {
      $("video").currentTime = m.time;
    };
    const note = document.createElement("input");
    note.setAttribute("aria-label", `Note at ${formatTime(m.time)}`);
    note.value = m.note;
    note.maxLength = 70;
    note.placeholder = "What matters at this moment?";
    note.oninput = () => ((moments[i].note = note.value), (dirty = true));
    const remove = textEl("button", "×");
    remove.setAttribute("aria-label", "Remove moment");
    remove.onclick = () => {
      moments.splice(i, 1);
      dirty = true;
      renderMoments();
    };
    row.append(seek, note, remove);
    box.append(row);
  });
}
function renderSingleRun(run, box = $("results"), includeStatus = true) {
  if (includeStatus) $("runStatus").textContent = (run.status || "unknown").replaceAll("_", " ").toUpperCase();
  if (includeStatus) box.replaceChildren();
  box.append(
    textEl(
      "div",
      run.status === "verified"
        ? "Draft saved. Evidence retained."
        : run.status === "needs_teaching"
          ? "A teaching moment."
          : "Trial failed.",
      "run-summary",
    ),
  );
  if (run.failure) box.append(textEl("div", safeTrialFailure(run.failure), "failure"));
  for (const step of run.steps || []) {
    const row = textEl("div", "", "run-step");
    row.append(textEl("span", step.status === "passed" ? "✓" : "↳", "tick"));
    const body = document.createElement("div");
    body.append(textEl("strong", step.goal), textEl("p", step.evidence));
    row.append(body);
    box.append(row);
  }
  if (run.draft_id)
    box.append(
      textEl(
        "div",
        `Retained draft: ${run.draft_id} · ${run.mode === "procedure" ? "Reviewed revision " + run.revision : "Legacy practice routine"}`,
        "receipt",
      ),
    );
  if (run.screenshot_url) {
    const img = document.createElement("img");
    img.className = "run-image";
    try {
      const screenshot = new URL(run.screenshot_url, location.href);
      if (screenshot.origin !== location.origin) return;
      img.src = screenshot.href;
    } catch { return; }
    img.alt = "Actual browser screenshot from this trial";
    box.append(img);
  }
}
function renderRun(run) {
  const box = $("results");
  box.replaceChildren();
  const batchRuns = Array.isArray(run.runs) ? run.runs : run.items;
  if (Array.isArray(batchRuns)) {
    $("runStatus").textContent = (run.status || "completed").replaceAll("_", " ").toUpperCase();
    const attempted = Number.isInteger(run.completed) ? run.completed : batchRuns.length;
    const requested = Number.isInteger(run.requested) ? run.requested : batchRuns.length;
    const stopped = Boolean(run.stopped_on_failure);
    const summary = `${attempted} of ${requested} items attempted${stopped ? " · stopped after a failure" : ""}`;
    box.append(textEl("div", summary, "run-summary"));
    batchRuns.forEach((item, index) => {
      const section = textEl("section", "", "batch-item");
      section.append(textEl("h4", `Item ${index + 1} · ${item.filename || "Media"}`));
      renderSingleRun(item.run || item, section, false);
      box.append(section);
    });
    return;
  }
  renderSingleRun(run);
}
async function selectSession(id) {
  if (dirty && session) {
    try {
      await save();
    } catch (e) {
      toast("Save failed; keeping this workflow open. " + e.message);
      return;
    }
  }
  if (recorder?.state === "recording") {
    toast("Stop recording before changing workflows.");
    return;
  }
  try {
    session = await api(`/api/sessions/${id}`);
    document.dispatchEvent(new CustomEvent("hmb-session-selected"));
    guidedActive = session.id === guidedSessionId;
    $("reviewed").checked = false;
    $("reviewed").disabled = guidedActive && !guidedInspected;
    setTab(document.querySelector("[data-tab].active")?.dataset.tab || "record");
    savedProcedure = structuredClone(session.procedure);
    queuedItems = []; renderQueue();
    dirty = false;
    $("title").value = session.title;
    $("notes").value = session.notes || "";
    try {
      moments = JSON.parse(session.answers?.moments || "[]");
    } catch {
      moments = [];
    }
    try {
      const proposedQuestions = JSON.parse(session.answers?.agent_questions || "[]");
      prompts = [...basePrompts, ...proposedQuestions.map(q => ["agent-" + q.id, q.question])];
    } catch { prompts = [...basePrompts]; }
    renderNav();
    renderObservations();
    renderQuestions();
    renderSteps();
    await renderProcedureHistory();
    renderMoments();
    $("video").hidden = !session.media_url;
    $("videoEmpty").hidden = !!session.media_url;
    $("video").src = session.media_url || "";
    $("mediaState").textContent = session.media_url
      ? "RECORDING RETAINED"
      : "NO RECORDING YET";
    renderHistory();
    if (guidedActive) {
      const latest = session.runs?.at(-1);
      $("filename").value = latest?.filename || "guided-first-use.txt";
      $("caption").value = latest?.caption || "A fresh caption for the guided practice draft.";
      $("variant").value = latest?.inputs?.variant || "normal";
      $("mediaMode").value = "new";
      syncMediaMode();
      guidedMessage(guidedStatusText);
    }
    if (session.runs?.length) renderRun(session.runs.at(-1));
    else {
      $("runStatus").textContent = "AWAITING TRIAL";
      $("results").replaceChildren(
        textEl(
          "p",
          "Run the practice workflow to collect real browser evidence.",
          "empty",
        ),
      );
    }
  } catch (e) {
    toast(e.message);
  }
}
async function loadReusableDrafts() {
  const oldId = reusableDrafts[Number($("existingDraft").value)]?.id;
  const oldCaption = $("caption").value;
  try {
    const data = await api("/api/fixture/drafts");
    reusableDrafts = Array.isArray(data.drafts) ? data.drafts : [];
  } catch (e) {
    reusableDrafts = [];
    toast(`Could not load saved media: ${e.message}`);
  }
  const select = $("existingDraft");
  select.replaceChildren();
  reusableDrafts.forEach((draft, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = `${draft.filename || "(no filename)"} — ${draft.caption || "(no caption)"}`;
    select.append(opt);
  });
  const oldIndex = reusableDrafts.findIndex(draft => draft.id === oldId);
  if (oldIndex >= 0) select.value = String(oldIndex);
  syncMediaMode();
  $("caption").value = oldCaption;
}
function syncMediaMode() {
  const reuse = $("mediaMode").value === "reuse";
  $("existingDraft").hidden = $("existingDraftLabel").hidden = !reuse;
  $("filename").disabled = reuse;
  $("mediaHelp").textContent = reuse
    ? "The fixture reconstructs a generated media file from its saved filename. It does not retain real video content."
    : "The fixture creates a generated text file. This is not video-platform acceptance.";
  if (reuse) syncDraftFields();
  $("reviewed").checked = false;
}
function syncDraftFields() {
  if ($("mediaMode").value !== "reuse") return;
  const draft = reusableDrafts[Number($("existingDraft").value)];
  if (!draft) return;
  $("filename").value = draft.filename || "";
  $("caption").value = draft.caption || "";
  $("reviewed").checked = false;
}
function currentItem() {
  const reuse = $("mediaMode").value === "reuse";
  const draft = reuse ? reusableDrafts[Number($("existingDraft").value)] : null;
  return {
    caption: $("caption").value,
    filename: reuse ? (draft?.filename || $("filename").value) : $("filename").value,
    media_mode: reuse ? "reuse" : "new",
    ...(reuse && draft ? { existing_draft_id: draft.id } : {}),
  };
}
function runItemPayload(item) {
  if (item.media_mode !== "reuse") return item;
  const {filename, ...payload} = item;
  return payload;
}
function renderQueue() {
  const box = $("itemQueue"); box.replaceChildren();
  queuedItems.forEach((item, i) => {
    const row = textEl("div", "", "run-step");
    const details = `${item.filename} · ${item.caption.slice(0, 60)} · ${item.media_mode}`;
    row.append(textEl("span", `${i + 1}.`, "tick"), textEl("span", details));
    const remove = textEl("button", "Remove", "quiet"); remove.type = "button";
    remove.onclick = () => { queuedItems.splice(i, 1); renderQueue(); $("reviewed").checked = false; };
    row.append(remove); box.append(row);
  });
  $("addItem").disabled = queuedItems.length >= 10;
  $("addItem").textContent = queuedItems.length >= 10 ? "Queue limit reached (10)" : "+ Add item to run";
}
async function refresh() {
  sessions = (await api("/api/sessions")).sessions;
  renderNav();
}
async function newSession() {
  try {
    if (dirty) await save();
    const title = "New workflow";
    if (!title?.trim()) return;
    const s = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ title: title.trim() }),
    });
    await refresh();
    await selectSession(s.id);
  } catch (e) {
    toast(e.message);
  }
}
$("newSession").onclick = newSession;
function initializeGuidedWorkflow() {
  session.procedure.steps = structuredClone(practiceSteps);
  dirty = true;
  renderSteps();
  $("filename").value = "guided-first-use.txt";
  $("caption").value = "A fresh caption for the guided practice draft.";
  $("variant").value = "normal";
  $("mediaMode").value = "new";
  syncMediaMode();
  $("reviewed").checked = false;
  $("reviewed").disabled = true;
  guidedActive = true;
  guidedInspected = false;
  guidedInitialized = true;
  setTab("teach");
  guidedMessage("1/4 · A separate fixture workflow is ready. Inspect the four actions below, then confirm you reviewed them.");
}
$("guidedStart").onclick = async () => {
  if (guidedStarting) return;
  guidedStarting = true;
  $("guidedStart").disabled = true;
  $("guidedDemo").hidden = false;
  try {
    if (guidedActive && session?.id === guidedSessionId) {
      guidedMessage(guidedStatusText);
      return;
    }
    if (dirty) {
      guidedMessage("Not started: save your unsaved edits or leave them as they are. The demo will not replace a workflow with unsaved changes.");
      toast("Save notes before starting the separate guided workflow; no edits were changed.");
      return;
    }
    if (recorder?.state === "recording") {
      guidedMessage("Not started: stop and save the current recording first.");
      toast("Stop recording before starting the guided demo.");
      return;
    }
    if (guidedSessionId) {
      if (session?.id !== guidedSessionId) await selectSession(guidedSessionId);
      if (session?.id !== guidedSessionId) return;
      guidedActive = true;
      if (!guidedInitialized) {
        initializeGuidedWorkflow();
        return;
      }
      guidedMessage(guidedStatusText);
      return;
    }
    guidedInspected = false;
    guidedMessage("Creating a separate fixture workflow; your current workflow stays saved.");
    const created = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "Guided practice · Save a draft" }),
    });
    guidedSessionId = created.id;
    guidedInitialized = false;
    await refresh();
    await selectSession(created.id);
    if (session?.id !== created.id) throw Error("Could not select the new practice workflow.");
    initializeGuidedWorkflow();
  } catch (error) {
    guidedMessage("Could not create the separate practice workflow. Check the local preview connection, then try again.");
  } finally {
    guidedStarting = false;
    $("guidedStart").disabled = false;
  }
};
$("guidedConfirmInspect").onclick = () => {
  if (!guidedActive || $("teach").hidden) return;
  guidedInspected = true;
  $("reviewed").disabled = false;
  setTab("test");
  guidedMessage("2/4 · Actions inspected. In Let it try, review the fresh filename and caption, then explicitly check the authorization box.");
};
$("reviewed").addEventListener("change", () => {
  if (!guidedActive) return;
  guidedMessage($("reviewed").checked
    ? "3/4 · Trial authorized. Press Run reviewed procedure when you are ready; it has not run yet."
    : "2/4 · Authorization cleared. Review the inputs and explicitly check the box before running.");
});
async function save(revision = false) {
  if (!session) return;
  const answers = { ...session.answers, moments: JSON.stringify(moments) };
  for (const [key] of prompts) answers[key] = $(`answer-${key}`).value;
  const steps = collectSteps();
  session = await api(`/api/sessions/${session.id}`, {
    method: "PUT",
    body: JSON.stringify({
      title: $("title").value.trim(),
      notes: $("notes").value,
      answers,
      procedure: {
        revision: savedProcedure.revision + (revision || JSON.stringify(steps) !== JSON.stringify(savedProcedure.steps, (key, value) => value === null ? undefined : value) ? 1 : 0),
        steps,
      },
    }),
  });
  savedProcedure = structuredClone(session.procedure);
  $("revision").textContent = session.procedure.revision;
  dirty = false;
  await refresh();
  await renderProcedureHistory();
  toast(revision ? "Teaching revision saved." : "Notes saved.");
  return session;
}
$("save").onclick = () => save().catch((e) => toast(e.message));
$("saveProcedure").onclick = () => save(true).catch((e) => toast(e.message));
$("addStep").onclick = () => {
  session.procedure.steps = collectSteps();
  if (session.procedure.steps.length >= 20) {
    toast("Keep this procedure to 20 checkpoints.");
    return;
  }
  dirty = true;
  session.procedure.steps.push({ goal: "", check: "" });
  renderSteps();
};
$("addMoment").onclick = () => {
  if (!$("video").src && !recordingStarted) {
    toast("Record or import a video first.");
    return;
  }
  const time =
    recorder?.state === "recording"
      ? (Date.now() - recordingStarted) / 1000
      : $("video").currentTime;
  if (moments.length >= 15) {
    toast("Preview limit: 15 teaching moments.");
    return;
  }
  dirty = true;
  moments.push({
    time: Math.max(0, Number.isFinite(time) ? time : 0),
    note: "",
  });
  renderMoments();
};
async function uploadVideo(blob) {
  if (blob.size > 100 * 1024 * 1024)
    throw Error("Video exceeds the 100 MB preview limit.");
  $("mediaState").textContent = "SAVING RECORDING…";
  const result = await api(`/api/sessions/${session.id}/media`, {
    method: "POST",
    headers: { "Content-Type": blob.type.split(";")[0] || "video/webm" },
    body: blob,
  });
  session.media_url = result.url;
  $("video").src = `${result.url}?t=${Date.now()}`;
  $("video").hidden = false;
  $("videoEmpty").hidden = true;
  $("mediaState").textContent = "RECORDING RETAINED";
  toast("Recording saved locally.");
  await save();
}
$("recordStart").onclick = async () => {
  try {
    if (!navigator.mediaDevices?.getDisplayMedia)
      throw Error(
        "Screen capture needs a supported browser on localhost or HTTPS. You can import a video instead.",
      );
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: false,
    });
    chunks = [];
    const mime = ["video/webm;codecs=vp9", "video/webm"].find((t) =>
      MediaRecorder.isTypeSupported(t),
    );
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    recorder.onstop = async () => {
      clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
      $("recordStart").hidden = false;
      $("recordStop").hidden = true;
      recordingStarted = 0;
      try {
        await uploadVideo(new Blob(chunks, { type: recorder.mimeType }));
      } catch (e) {
        toast(e.message);
        $("mediaState").textContent = "RECORDING SAVE FAILED";
      }
    };
    stream.getVideoTracks()[0].onended = () => {
      if (recorder.state === "recording") recorder.stop();
    };
    recordingStarted = Date.now();
    recorder.start(1000);
    $("recordStart").hidden = true;
    $("recordStop").hidden = false;
    $("mediaState").textContent = "● RECORDING";
    timer = setInterval(
      () =>
        ($("timer").textContent = formatTime(
          (Date.now() - recordingStarted) / 1000,
        )),
      500,
    );
  } catch (e) {
    stream?.getTracks().forEach((t) => t.stop());
    toast(e.message);
  }
};
$("recordStop").onclick = () => {
  if (recorder?.state === "recording") recorder.stop();
};
$("importVideo").onchange = async (e) => {
  if (recorder?.state === "recording") {
    toast("Stop recording before importing.");
    e.target.value = "";
    return;
  }
  const file = e.target.files[0];
  if (!file) return;
  try {
    await uploadVideo(file);
  } catch (e) {
    toast(e.message);
  }
  e.target.value = "";
};
$("run").onclick = async () => {
  const b = $("run");
  if (recorder?.state === "recording") {
    toast("Stop recording before running a trial.");
    return;
  }
  if (!$("reviewed").checked) {
    toast("Review the actions in Explain the why, then authorize this trial.");
    if (guidedActive) guidedMessage("2/4 · Review the procedure, confirm inspection, then explicitly check the authorization box.");
    return;
  }
  b.disabled = true;
  b.textContent = "Browser trial running…";
  $("runStatus").textContent = "RUNNING";
  if (guidedActive) guidedMessage("3/4 · Running the reviewed local fixture in Chromium. This may take a few seconds.");
  $("results").replaceChildren(
    textEl("p", queuedItems.length ? `Opening the practice app for ${queuedItems.length} queued item${queuedItems.length === 1 ? "" : "s"}…` : "Opening the practice app and checking the selected inputs…", "empty"),
  );
  try {
    await save();
    const item = currentItem();
    if (!queuedItems.length && $("mediaMode").value === "reuse" && !item.existing_draft_id) throw Error("Choose a saved draft before running in reuse mode.");
    const payload = {
      ...(queuedItems.length ? { items: queuedItems.map(runItemPayload) } : runItemPayload(item)),
      variant: $("variant").value,
      repair: false,
      mode: "procedure",
    };
    const result = await api(`/api/sessions/${session.id}/run`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    // Reload the canonical session so history reflects every per-item receipt.
    session = await api(`/api/sessions/${session.id}`);
    queuedItems = result.stopped_on_failure
      ? queuedItems.slice(Number.isInteger(result.verified_count) ? result.verified_count : 0)
      : [];
    renderQueue();
    renderHistory();
    renderRun(result);
    if (guidedActive) {
      const actual = Array.isArray(result.runs) ? result.runs[0] : result;
      if (actual?.status === "verified" && actual.filename === item.filename && actual.caption === item.caption && actual.draft_id) {
        guidedMessage(`4/4 · Verified and persisted. Filename: ${actual.filename}. Caption: ${actual.caption}. Draft ID: ${actual.draft_id}.`);
      } else {
        guidedMessage(`Trial did not verify. ${safeTrialFailure(actual?.failure || "Review the checkpoint evidence below, repair the local setup, then explicitly authorize a retry.")}`);
      }
    }
    await loadReusableDrafts();
    toast(
      result.status === "verified"
        ? "Draft verified in retained storage."
        : "Trial stopped. Review the evidence.",
    );
  } catch (e) {
    const message = safeTrialFailure(e.message);
    toast(guidedActive ? message : e.message);
    $("runStatus").textContent = "FAILED";
    if (guidedActive) guidedMessage(`Trial failed. ${message}`);
  } finally {
    b.disabled = false;
    b.textContent = "Run reviewed procedure ↗";
  }
};
async function boot() {
  try {
    await api("/api/status");
    await refresh();
    if (!sessions.length) {
      const s = await api("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ title: "Prepare a video draft" }),
      });
      await refresh();
      await selectSession(s.id);
    } else await selectSession(sessions[0].id);
  } catch (e) {
    toast(`Could not load workspace: ${e.message}`);
  }
}
boot();

$("mediaMode").onchange = syncMediaMode;
$("existingDraft").onchange = syncDraftFields;
$("addItem").onclick = () => {
  if (queuedItems.length >= 10) return;
  const item = currentItem();
  if (!item.filename.trim() || !item.caption.trim()) { toast("Add a filename and caption before queueing this item."); return; }
  if (item.media_mode === "reuse" && !item.existing_draft_id) { toast("Choose a saved draft before queueing this item."); return; }
  queuedItems.push(item);
  renderQueue();
  $("reviewed").checked = false;
  toast(`${queuedItems.length} item${queuedItems.length === 1 ? "" : "s"} queued. Add up to 10.`);
};
loadReusableDrafts();

document.addEventListener("input", (e) => {
  if (["filename", "caption", "variant"].includes(e.target.id)) {
    $("reviewed").checked = false;
    if (guidedActive) guidedMessage("Inputs changed. Review them, then explicitly authorize the trial again.");
  }
  if (
    ["title", "notes"].includes(e.target.id) ||
    e.target.closest("#questions,#steps")
  )
    {
      dirty = true;
      if (e.target.closest("#steps")) {
        $("reviewed").checked = false;
        if (guidedActive) {
          guidedInspected = false;
          $("reviewed").disabled = true;
          guidedMessage("Procedure changed. Inspect all four actions again before authorizing another trial.");
          setTab($("teach").hidden ? "test" : "teach");
        }
      }
    }
});
window.addEventListener("beforeunload", (e) => {
  if (dirty || recorder?.state === "recording") {
    e.preventDefault();
    e.returnValue = "";
  }
});

function renderHistory() {
  const select = $("runHistory");
  select.replaceChildren();
  for (const [i, run] of (session.runs || []).entries()) {
    const option = textEl(
      "option",
      `Trial ${i + 1} · ${run.status.replaceAll("_", " ")} · ${run.caption.slice(0, 30)}`,
    );
    option.value = run.id;
    select.append(option);
  }
  select.hidden = !session.runs?.length;
  if (session.runs?.length) select.value = session.runs.at(-1).id;
}
$("runHistory").onchange = () => {
  const run = session.runs.find((r) => r.id === $("runHistory").value);
  if (run) renderRun(run);
};

$("loadPractice").onclick = () => {
  session.procedure.steps = structuredClone(practiceSteps);
  dirty = true; renderSteps(); toast("Practice actions loaded. Review them before saving.");
};
$("importProcedure").onchange = async e => {
  const file = e.target.files[0]; if (!file) return;
  try {
    if (file.size > 30000) throw Error("Procedure JSON must be smaller than 30 KB.");
    const proposal = JSON.parse(await file.text());
    if (!Array.isArray(proposal.steps) || proposal.steps.length > 20) throw Error("Expected a procedure with up to 20 steps.");
    if (proposal.steps.some(step => !step || typeof step.goal !== "string" || typeof step.check !== "string" || (step.target != null && typeof step.target !== "string"))) throw Error("Each step needs text goal, check and optional target.");
    if (proposal.steps.some(step => step.action && !["upload", "select_media", "fill", "click", "verify_draft"].includes(step.action))) throw Error("Unsupported action. Use select_media, upload, fill, click or verify_draft.");
    session.procedure.steps = proposal.steps; dirty = true; renderSteps(); setTab("teach");
    toast("Agent proposal imported for review. Nothing has run.");
  } catch (error) { toast(error.message); }
  e.target.value = "";
};

function renderObservations() {
  const box = $("observations"); box.replaceChildren();
  let observations = [];
  try { observations = JSON.parse(session.answers?.agent_observations || "[]"); } catch {}
  if (!observations.length) return;
  box.append(textEl("h3", "Agent observations · review against your recording"));
  for (const observation of observations) {
    const row = textEl("p", `${formatTime(observation.timestamp)} · ${observation.text}`);
    box.append(row);
  }
}
$("loadProposal").onclick = async () => {
  try {
    const {proposal} = await api(`/api/sessions/${session.id}/proposal`);
    if (!proposal) { toast("No agent proposal yet. Connect the MCP tools and ask your agent to inspect this recording."); return; }
    const observations = JSON.stringify(proposal.observations);
    for (const [key] of prompts) session.answers[key] = $(`answer-${key}`).value;
    session.answers.agent_observations = observations;
    session.answers.agent_questions = JSON.stringify(proposal.questions);
    session.answers.proposal_id = proposal.id;
    prompts = [...basePrompts, ...proposal.questions.map(q => ["agent-" + q.id, q.question])];
    session.procedure.steps = proposal.procedure.steps;
    dirty = true; renderObservations(); renderQuestions(); renderSteps();
    toast("Agent proposal loaded for review. Save a reviewed revision before trying it.");
  } catch (error) { toast(error.message); }
};
