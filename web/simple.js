/* A small first-use path over the existing session and reviewed-run APIs. */
(() => {
  let demoSession = null;
  let running = false;
  let pendingAttempt = null;
  const status = message => { $("demoStatus").textContent = message; };
  const views = ["home", "directed", "demo", "brief", "saved", "settings", "advanced"];
  function showView(name) {
    if (!views.includes(name)) return;
    if (recorder?.state === "recording") {
      toast("Stop and save your recording before leaving this screen.");
      return;
    }
    for (const view of views) $(view + "View").hidden = view !== name;
    $("simpleApp").hidden = name === "advanced";
    for (const button of document.querySelectorAll(".app-nav [data-view]")) {
      if (button.dataset.view === name) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    $(name + "View").querySelector("h1,h2")?.focus();
    if (name === "saved") loadSaved();
  }
  window.hmbShowView = showView;
  document.querySelectorAll("[data-view]").forEach(button => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  $("demoBegin").onclick = () => showView("demo");
  $("openBrief").onclick = () => showView("brief");
  $("openDeveloperTools").onclick = () => showView("advanced");
  $("workbenchBackSettings").onclick = () => showView("settings");
  $("directedBegin").onclick = () => { showView("directed"); document.dispatchEvent(new CustomEvent("hmb-new-directed")); };
  const consent = () => { $("demoRun").disabled = running || !!pendingAttempt || !$("demoConsent").checked; };
  $("demoConsent").onchange = () => {
    consent();
    status($("demoConsent").checked ? "Ready. Choose Save my practice draft to begin." : "Nothing will run until you give permission.");
  };
  for (const id of ["demoFilename", "demoCaption"]) $(id).addEventListener("input", () => {
    $("demoConsent").checked = false;
    consent();
    status("Details changed. Check the steps and give permission again.");
  });
  function showDraft(run) {
    const box = $("demoResult");
    box.replaceChildren();
    box.append(textEl("p", "3. YOUR RESULT", "eyebrow"), textEl("h2", "Draft saved."),
      textEl("p", "LikeThis did the clicks and checked the saved draft. Nothing was posted."));
    const fields = document.createElement("dl");
    fields.className = "receipt-fields";
    for (const [label, value] of [["File", run.filename], ["Caption", run.caption]]) {
      fields.append(textEl("dt", label), textEl("dd", value));
    }
    box.append(fields);
    if (/^\/api\/artifacts\/[a-f0-9-]+\.png$/.test(run.screenshot_url || "")) {
      const link = textEl("a", "View the screenshot");
      link.href = run.screenshot_url;
      link.target = "_blank";
      link.rel = "noopener";
      box.append(link);
    }
    const detail = document.createElement("details");
    detail.className = "technical-details";
    detail.append(textEl("summary", "Saved proof"), textEl("p", `Draft reference: ${run.draft_id}`));
    box.append(detail);
    const again = textEl("button", "Try different details", "primary");
    again.type = "button";
    again.onclick = () => {
      box.hidden = true;
      $("demoForm").hidden = false;
      $("demoConsent").checked = false;
      consent();
      status("Change the details, then check the steps again.");
      $("demoFilename").focus();
    };
    box.append(again);
    $("demoForm").hidden = true;
    box.hidden = false;
    box.querySelector("h2").tabIndex = -1;
    box.querySelector("h2").focus();
  }
  const normalizeSteps = steps => JSON.stringify(steps, (key, value) => value === null ? undefined : value);
  $("demoForm").onsubmit = async event => {
    event.preventDefault();
    if (running || !!pendingAttempt || !$("demoConsent").checked || !$("demoForm").reportValidity()) return;
    const filename = $("demoFilename").value.trim(), caption = $("demoCaption").value.trim();
    if (!filename || !caption) { status("Add both a file name and caption first."); return; }
    running = true;
    $("demoForm").setAttribute("aria-busy", "true");
    for (const input of $("demoForm").querySelectorAll("input,button")) input.disabled = true;
    status("Saving your practice draft… this may take a few seconds.");
    try {
      if (!demoSession) {
        const created = await api("/api/sessions", {method: "POST", body: JSON.stringify({title: "Practice · Save a draft"})});
        // Keep the ID even if saving the steps fails; never silently create another task on retry.
        demoSession = created;
      }
      demoSession = await api(`/api/sessions/${demoSession.id}`);
      if (!demoSession.procedure.steps.length && demoSession.procedure.revision === 1) {
        demoSession = await api(`/api/sessions/${demoSession.id}`, {method: "PUT", body: JSON.stringify({
          procedure: {revision: 2, steps: practiceSteps},
        })});
      }
      if (normalizeSteps(demoSession.procedure.steps) !== normalizeSteps(practiceSteps))
        throw Error("This saved task’s steps have changed. Open Advanced to review them before running it.");
      pendingAttempt = {sessionId: demoSession.id, filename, caption, earlier: new Set(demoSession.runs.map(run => run.id))};
      const run = await api(`/api/sessions/${demoSession.id}/run`, {method: "POST", body: JSON.stringify({
        filename, caption, variant: "normal", repair: false, mode: "procedure", media_mode: "new",
      })});
      pendingAttempt.runId = run.id;
      const retained = await api(`/api/sessions/${demoSession.id}/runs/${run.id}`);
      pendingAttempt = null;
      if (retained.status !== "verified" || retained.filename !== filename || retained.caption !== caption || !retained.draft_id)
        throw Error(safeTrialFailure(retained.failure || "The draft could not be checked. Review the details and try again."));
      showDraft(retained);
      await refresh();
    } catch (error) {
      if (pendingAttempt) {
        status("The connection was interrupted. Your draft may already be saved. Check for its result before trying again.");
        $("demoCheck").hidden = false;
      } else status(safeTrialFailure(error.message));
    } finally {
      running = false;
      $("demoForm").removeAttribute("aria-busy");
      for (const input of $("demoForm").querySelectorAll("input,button")) input.disabled = !!pendingAttempt;
      $("demoConsent").checked = false;
      consent();
    }
  };
  async function checkSavedAttempt() {
    if (!pendingAttempt) return;
    $("demoCheck").disabled = true;
    try {
      const attempt = pendingAttempt;
      const saved = await api(`/api/sessions/${attempt.sessionId}`);
      const found = saved.runs.find(run => !attempt.earlier.has(run.id) &&
        (!attempt.runId || attempt.runId === run.id) && run.filename === attempt.filename && run.caption === attempt.caption);
      if (!found) {
        status("No result is saved yet. It may still be running. Check again in a moment; another attempt is blocked.");
        return;
      }
      pendingAttempt = null;
      demoSession = saved;
      $("demoCheck").hidden = true;
      for (const input of $("demoForm").querySelectorAll("input,button")) input.disabled = false;
      $("demoConsent").checked = false;
      consent();
      if (found.status === "verified" && found.draft_id) showDraft(found);
      else status("The previous attempt stopped without a verified result. Check the details and give permission before trying again.");
    } catch (error) { status("Could not check the saved result. Keep this page open and try Check for a saved result again when the app is available."); }
    finally { $("demoCheck").disabled = false; }
  }
  $("demoCheck").onclick = checkSavedAttempt;
  async function appendLegacySaved(list) {
    const data = await api("/api/sessions");
    const sessions = (data.sessions || []).filter(item => !item.training_task);
    if (!sessions.length) return 0;
    list.append(textEl("h2", "Other saved work"));
    for (const item of sessions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "saved-task";
      button.append(textEl("strong", item.title));
      const last = item.runs?.at(-1);
      button.append(textEl("span", last?.status === "verified" ? "Draft saved · View result" : item.title.startsWith("GitHub report ·") ? "View report history" : "Open task"));
      button.onclick = async () => {
        try {
          if (item.title === "Practice · Save a draft") {
            if (pendingAttempt?.sessionId === item.id) { showView("demo"); await checkSavedAttempt(); return; }
            demoSession = await api(`/api/sessions/${item.id}`);
            $("demoConsent").checked = false;
            consent();
            showView("demo");
            const recent = demoSession.runs?.at(-1);
            $("demoForm").hidden = false;
            $("demoResult").hidden = true;
            if (recent?.status === "verified" && recent.draft_id) showDraft(recent);
            else status("Check the steps and give permission to try this task.");
          } else if (item.title.startsWith("GitHub report ·")) {
            showView("brief");
            document.dispatchEvent(new CustomEvent("hmb-open-brief", {detail: item.id}));
          } else {
            showView("advanced");
            await selectSession(item.id);
          }
        } catch (error) { $("savedStatus").textContent = error.message; toast(error.message); }
      };
      list.append(button);
      if (item.title !== "Practice · Save a draft" && !item.title.startsWith("GitHub report ·")) {
        const reports = textEl("button", "Find GitHub reports in this older task", "back-link");
        reports.type = "button";
        reports.onclick = () => { showView("brief"); document.dispatchEvent(new CustomEvent("hmb-open-brief", {detail: item.id})); };
        list.append(reports);
      }
    }
    return sessions.length;
  }
  window.hmbAppendLegacySaved = appendLegacySaved;
  async function loadSaved() {
    if (window.hmbLoadTrainingSaved) { await window.hmbLoadTrainingSaved(); return; }
    $("savedStatus").textContent = "Loading saved tasks…";
    const list = $("savedList");
    list.replaceChildren();
    try {
      const count = await appendLegacySaved(list);
      $("savedStatus").textContent = count ? "Choose a task to see its details or results." : "No saved tasks yet. Show me one task to get started.";
    } catch (error) { $("savedStatus").textContent = `Could not load saved tasks. ${error.message}`; }
  }
})();
