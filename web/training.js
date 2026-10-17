/* App → task → versioned session selection for the compact first-use flow. */
(() => {
  const $ = id => document.getElementById(id);
  let apps = [], selectedApp = null, selectedTask = null, detail = null, busy = false;
  async function trainingApi(path, options = {}) {
    const response = await fetch(path, { ...options, headers: {"Content-Type":"application/json", ...(options.headers || {})} });
    if (!response.ok) {
      if (response.status >= 500) throw new Error("The local workspace returned an error. Check its local server log and retry.");
      let body = {}; try { body = await response.json(); } catch {}
      throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
    }
    return response.json();
  }
  const setStatus = (id, message) => { $(id).textContent = message; };
  function switchStage(stage) {
    $("trainingAppStage").hidden = stage !== "app";
    $("trainingTaskStage").hidden = stage !== "task";
    $("trainingDescriptionStage").hidden = stage !== "description";
    $("directedForm").hidden = stage !== "record";
    $("directedReviewPanel").hidden = stage !== "review";
    if (stage === "app") $("trainingAppTitle").focus();
    if (stage === "task") ($("trainingTaskCreateForm").hidden ? $("trainingTaskTitle") : $("trainingTaskName")).focus();
    if (stage === "description") $("trainingDescriptionTitle").focus();
  }
  document.addEventListener("hmb-training-record", () => {
    if (!detail?.session?.id || busy) return;
    switchStage("record");
    document.dispatchEvent(new CustomEvent("hmb-training-start-record"));
  });
  document.addEventListener("hmb-training-review", () => switchStage("review"));
  document.addEventListener("click", event => {
    if (!busy && !window.hmbDirectedIsBusy?.()) return;
    const target = event.target;
    if (target.closest(".saved-task")) {
      event.preventDefault(); event.stopImmediatePropagation();
      setStatus("savedStatus", "Finish the current save or review before opening another task.");
      return;
    }
    if (target.closest("[data-view], .brand, #trainingBackToApps, #trainingBackToTasks, #trainingRecordContinue, #trainingAppCreateToggle, #trainingTaskCreateToggle, #trainingAppContinue, #trainingTaskContinue, #trainingEdit, #trainingRestore, #trainingViewVersion, #directedEditDetails") && !target.closest("#directedStop")) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  window.addEventListener("beforeunload", event => { if (busy) { event.preventDefault(); event.returnValue = ""; } });
  async function loadApps() {
    const payload = await trainingApi("/api/training/apps");
    apps = payload.apps || [];
    const select = $("trainingAppSelect"); select.replaceChildren();
    for (const app of apps) {
      const option = document.createElement("option"); option.value = app.id; option.textContent = app.name; select.append(option);
    }
    if (selectedApp && apps.some(item => item.id === selectedApp)) select.value = selectedApp;
    if (!apps.length) {
      setStatus("trainingAppStatus", "Create an app to keep its task training together.");
      $("trainingAppCreateForm").hidden = false;
      $("trainingAppCreateToggle").hidden = true;
      $("trainingAppContinue").hidden = true;
    } else {
      $("trainingAppCreateForm").hidden = true;
      $("trainingAppCreateToggle").hidden = false;
      $("trainingAppCreateToggle").textContent = "Create an app";
      $("trainingAppContinue").hidden = false;
      setStatus("trainingAppStatus", "Choose an app, or create a separate one.");
    }
  }
  function clearSelection() { selectedApp = null; selectedTask = null; detail = null; }
  document.addEventListener("hmb-new-directed", async () => {
    clearSelection();
    $("trainingAppCreateForm").reset(); $("trainingTaskCreateForm").reset();
    $("trainingTaskCreateForm").hidden = true; $("trainingTaskCreateToggle").hidden = false;
    $("trainingEditForm").hidden = true;
    $("directedReviewPanel").replaceChildren();
    switchStage("app");
    try { await loadApps(); } catch (error) { setStatus("trainingAppStatus", `Could not load apps. ${error.message}`); }
  });
  $("trainingAppSelect").onchange = () => { selectedApp = $("trainingAppSelect").value || null; };
  $("trainingAppContinue").onclick = async () => {
    if (busy) return;
    selectedApp = $("trainingAppSelect").value || null;
    if (!selectedApp) { setStatus("trainingAppStatus", "Choose or create an app first."); return; }
    busy = true; $("trainingAppContinue").disabled = true;
    try {
      const app = apps.find(item => item.id === selectedApp);
      $("trainingAppNameSummary").textContent = app?.name || "";
      renderTasks(app?.tasks || []);
      switchStage("task");
    } catch (error) { setStatus("trainingAppStatus", error.message); }
    finally { busy = false; $("trainingAppContinue").disabled = false; }
  };
  function renderTasks(tasks) {
    const list = $("trainingTasks"); list.replaceChildren(); selectedTask = null;
    $("trainingTaskCreateForm").reset(); $("trainingTaskCreateForm").hidden = true;
    $("trainingTaskCreateToggle").hidden = false; $("trainingTaskCreateToggle").textContent = "Create a task";
    $("trainingTaskContinue").disabled = true;
    $("trainingTaskTitle").textContent = tasks.length ? "2. Choose a task" : "2. Create your first task";
    for (const task of tasks) {
      const label = document.createElement("label"); label.className = "training-task-choice";
      const radio = document.createElement("input"); radio.type = "radio"; radio.name = "training-task-choice"; radio.value = task.id;
      radio.onchange = () => { selectedTask = task.id; $("trainingTaskContinue").disabled = false; };
      label.append(radio);
      const copy = document.createElement("span"); add("strong", task.name, copy);
      if (task.description) add("span", task.description, copy);
      const version = task.latest_version ? `Training version ${task.latest_version}${task.working_version ? ` · Practice-tested version ${task.working_version}` : " · No tested version"}` : "No saved version";
      add("small", version, copy); label.append(copy); list.append(label);
    }
    $("trainingTaskCreateForm").hidden = tasks.length > 0;
    $("trainingTaskCreateToggle").hidden = !tasks.length;
    $("trainingTaskContinue").hidden = !tasks.length;
    $("trainingTaskStatus").textContent = tasks.length ? "Choose a task or create a separate one." : "Each task has its own recording and version history.";
  }
  function add(tag, value, parent, className) { const element = document.createElement(tag); element.textContent = value; if (className) element.className = className; parent.append(element); return element; }
  $("trainingAppCreateToggle").onclick = () => { $("trainingAppCreateForm").hidden = false; $("trainingAppCreateToggle").hidden = true; $("trainingAppName").focus(); };
  $("trainingAppCreateForm").onsubmit = async event => {
    event.preventDefault(); if (busy || !event.currentTarget.reportValidity()) return;
    busy = true; setStatus("trainingAppStatus", "Saving app…");
    try {
      const created = await trainingApi("/api/training/apps", {method:"POST", body:JSON.stringify({name:$("trainingAppName").value.trim()})});
      selectedApp = created.id; await loadApps(); $("trainingAppSelect").value = selectedApp;
      setStatus("trainingAppStatus", `Saved ${created.name}.`);
      $("trainingAppNameSummary").textContent = created.name;
      renderTasks(created.tasks || []); switchStage("task");
    } catch (error) { setStatus("trainingAppStatus", `Could not save app. ${error.message}`); }
    finally { busy = false; }
  };
  $("trainingBackToApps").onclick = () => switchStage("app");
  $("trainingBackToTasks").onclick = async () => {
    if (busy) return;
    busy = true;
    try {
      const payload = await trainingApi("/api/training/apps"); apps = payload.apps || [];
      switchStage("task");
      if (selectedApp) renderTasks(apps.find(item => item.id === selectedApp)?.tasks || []);
    } catch (error) { setStatus("trainingDescriptionStatus", `Could not refresh tasks. ${error.message}`); }
    finally { busy = false; }
  };
  $("trainingTaskCreateToggle").onclick = () => {
    $("trainingTaskCreateForm").hidden = false; $("trainingTaskCreateToggle").hidden = true;
    $("trainingTaskContinue").hidden = true; $("trainingTaskName").focus();
  };
  $("trainingTaskCreateForm").onsubmit = async event => {
    event.preventDefault(); if (busy || !event.currentTarget.reportValidity()) return;
    busy = true; setStatus("trainingTaskStatus", "Saving task…");
    try {
      // Name only: the task name is an organizational label, not intent. Intent is
      // inferred later from a real recording examined by a connected agent.
      detail = await trainingApi(`/api/training/apps/${selectedApp}/tasks`, {method:"POST", body:JSON.stringify({
        name:$("trainingTaskName").value.trim(),
      })});
      selectedTask = detail.id;
    } catch (error) {
      setStatus("trainingTaskStatus", `Could not save task. ${error.message}`);
      return;
    } finally { busy = false; }
    // The name-only task is persisted; hand off to the real recording/import path now
    // that busy is cleared. Persisted task identity and recording/session linkage mean
    // reload/reopen returns here without creating a duplicate session.
    document.dispatchEvent(new CustomEvent("hmb-training-session", {detail:{task: detail, session: detail.session}}));
    document.dispatchEvent(new CustomEvent("hmb-training-record"));
  };
  $("trainingTaskContinue").onclick = async () => {
    if (busy || !selectedTask) return;
    busy = true; $("trainingTaskContinue").disabled = true;
    document.querySelectorAll("#trainingTasks input").forEach(input => { input.disabled = true; });
    try { await showTask(await trainingApi(`/api/training/tasks/${selectedTask}`)); }
    catch (error) { setStatus("trainingTaskStatus", `Could not open task. ${error.message}`); }
    finally { busy = false; $("trainingTaskContinue").disabled = !selectedTask; document.querySelectorAll("#trainingTasks input").forEach(input => { input.disabled = false; }); }
  };
  function renderVersionHistory(task) {
    const versions = task.versions || [], latest = task.latest_version, working = task.working_version;
    const info = $("trainingVersionInfo"); info.replaceChildren();
    add("dt", "Current training", info); add("dd", latest ? `Version ${latest}` : "None", info);
    add("dt", "Last tested version", info); add("dd", working ? `Version ${working} · tested in the practice app only` : "None tested", info);
    add("dt", "Availability", info); add("dd", "Recording and review are supported. General recorded-app replay is not available.", info);
    const history = $("trainingHistory"); history.replaceChildren();
    for (const version of versions.filter(item => item.version !== latest).sort((a,b) => b.version - a.version)) {
      const option = document.createElement("option"); option.value = version.version;
      option.textContent = `Version ${version.version}${version.version === working ? " · last tested" : ""}${version.parent_version ? ` · from ${version.parent_version}` : ""}`;
      history.append(option);
    }
    $("trainingRestore").disabled = !history.options.length;
    $("trainingViewVersion").disabled = !history.value;
  }
  function taskCopy(task) {
    const session = task.session || {};
    const answers = session.answers || {};
    const name = answers.teaching_task_name || task.name || "Untitled task";
    const goal = answers.teaching_goal || task.description || "";
    const done = answers.teaching_done || "";
    $("trainingDescriptionText").textContent = `${name}\n\n${goal}${done ? `\n\nDone when: ${done}` : ""}`;
  }
  async function showTask(task) {
    detail = task; selectedTask = task.id; taskCopy(task); renderVersionHistory(task);
    $("trainingEditForm").hidden = true;
    $("trainingRecordContinue").hidden = false;
    switchStage("description");
    $("directedReviewPanel").replaceChildren(); $("directedReviewPanel").hidden = true;
    document.dispatchEvent(new CustomEvent("hmb-training-session", {detail:{task, session:task.session}}));
  }
  $("trainingRecordContinue").onclick = () => {
    if (!detail?.session?.id) { setStatus("trainingDescriptionStatus", "This task has no saved training version yet."); return; }
    document.dispatchEvent(new CustomEvent("hmb-training-record"));
  };
  $("trainingEdit").onclick = async () => {
    if (busy || !detail?.latest_version) return;
    busy = true; $("trainingEdit").disabled = true; setStatus("trainingDescriptionStatus", "Creating a separate training version…");
    try {
      detail = await trainingApi(`/api/training/tasks/${detail.id}/edit`, {method:"POST", body:JSON.stringify({base_version:detail.latest_version})});
      const answers = detail.session?.answers || {};
      $("trainingEditName").value = answers.teaching_task_name || detail.name || "";
      $("trainingEditGoal").value = answers.teaching_goal || "";
      $("trainingEditDone").value = answers.teaching_done || "";
      $("trainingEditForm").hidden = false; $("trainingRecordContinue").hidden = true; $("trainingEditName").focus();
      taskCopy(detail); renderVersionHistory(detail);
      document.dispatchEvent(new CustomEvent("hmb-training-session", {detail:{task:detail, session:detail.session}}));
    } catch (error) { setStatus("trainingDescriptionStatus", `Could not create an edit version. ${error.message}`); }
    finally { busy = false; $("trainingEdit").disabled = false; }
  };
  $("trainingEditForm").onsubmit = async event => {
    event.preventDefault(); if (busy || !event.currentTarget.reportValidity()) return;
    busy = true; setStatus("trainingDescriptionStatus", "Saving this training version…");
    try {
      const fresh = await trainingApi(`/api/sessions/${detail.session.id}`);
      const answers = {...(fresh.answers || {}), teaching_task_name:$("trainingEditName").value.trim(), teaching_goal:$("trainingEditGoal").value.trim(), teaching_done:$("trainingEditDone").value.trim()};
      detail.session = await trainingApi(`/api/sessions/${detail.session.id}`, {method:"PUT", body:JSON.stringify({title:`Training · ${answers.teaching_task_name}`, answers})});
      detail = await trainingApi(`/api/training/tasks/${detail.id}`);
      $("trainingEditForm").hidden = true; $("trainingRecordContinue").hidden = false; taskCopy(detail); renderVersionHistory(detail);
      document.dispatchEvent(new CustomEvent("hmb-training-session", {detail:{task:detail, session:detail.session}}));
      setStatus("trainingDescriptionStatus", `Saved training version ${detail.latest_version}. The previous tested version remains available.`);
    } catch (error) { setStatus("trainingDescriptionStatus", `Could not save version. ${error.message}`); }
    finally { busy = false; }
  };
  $("trainingEditCancel").onclick = () => { $("trainingEditForm").hidden = true; $("trainingRecordContinue").hidden = false; };
  $("trainingHistory").onchange = () => {
    $("trainingRestore").disabled = !$("trainingHistory").value;
    $("trainingViewVersion").disabled = !$("trainingHistory").value;
  };
  $("trainingViewVersion").onclick = async () => {
    if (busy || !detail || !$("trainingHistory").value) return;
    const version = (detail.versions || []).find(item => item.version === Number($("trainingHistory").value));
    if (!version?.session_id) { setStatus("trainingDescriptionStatus", "That version has no saved session to view."); return; }
    const taskSnapshot = detail;
    busy = true; $("trainingViewVersion").disabled = true;
    setStatus("trainingDescriptionStatus", `Loading version ${version.version}…`);
    try {
      const session = await trainingApi(`/api/sessions/${encodeURIComponent(version.session_id)}`);
      if (detail !== taskSnapshot) return;
      switchStage("record");
      document.dispatchEvent(new CustomEvent("hmb-training-session", {detail:{task:taskSnapshot, session, historical:true}}));
      document.dispatchEvent(new CustomEvent("hmb-training-start-record", {detail:{readOnly:true, historical:true}}));
    } catch (error) { setStatus("trainingDescriptionStatus", `Could not open that version. ${error.message}`); }
    finally { busy = false; $("trainingViewVersion").disabled = !$("trainingHistory").value; }
  };
  $("trainingRestore").onclick = async () => {
    if (busy || !detail || !$("trainingHistory").value) return;
    busy = true; $("trainingRestore").disabled = true; setStatus("trainingDescriptionStatus", "Copying that version into a new training version…");
    try {
      detail = await trainingApi(`/api/training/tasks/${detail.id}/restore`, {method:"POST", body:JSON.stringify({base_version:detail.latest_version, source_version:Number($("trainingHistory").value)})});
      taskCopy(detail); renderVersionHistory(detail);
      document.dispatchEvent(new CustomEvent("hmb-training-session", {detail:{task:detail, session:detail.session}}));
      setStatus("trainingDescriptionStatus", `Copied as training version ${detail.latest_version}. Review and test it again before using it.`);
    } catch (error) { setStatus("trainingDescriptionStatus", `Could not restore version. ${error.message}`); }
    finally { busy = false; $("trainingRestore").disabled = !$("trainingHistory").options.length; }
  };
  document.addEventListener("hmb-training-back-to-details", async () => {
    if (!detail || busy) return;
    busy = true;
    try { detail = await trainingApi(`/api/training/tasks/${detail.id}`); await showTask(detail); }
    catch (error) { setStatus("trainingDescriptionStatus", `Could not reload task details. ${error.message}`); }
    finally { busy = false; }
  });
  window.hmbLoadTrainingSaved = async () => {
    const list = $("savedList"); list.replaceChildren(); setStatus("savedStatus", "Loading apps and tasks…");
    try {
      const data = await trainingApi("/api/training/apps"); apps = data.apps || [];
      let taskCount = 0;
      for (const app of apps) {
        add("h2", app.name, list);
        if (!app.tasks.length) add("p", "No tasks saved for this app.", list, "task-status");
        for (const task of app.tasks) {
          taskCount += 1;
          const button = add("button", `${task.name} · training version ${task.latest_version || "—"}${task.working_version ? ` · practice-tested ${task.working_version}` : " · no tested version"}`, list, "saved-task");
          button.type = "button";
          button.onclick = () => { window.hmbShowView("directed"); document.dispatchEvent(new CustomEvent("hmb-resume-training-task", {detail:task.id})); };
        }
      }
      const legacyCount = await window.hmbAppendLegacySaved(list);
      setStatus("savedStatus", taskCount + legacyCount ? "Choose a task, result, or older workflow to continue." : "No saved tasks yet. I’ll show you one task to get started.");
    } catch (error) { setStatus("savedStatus", `Could not load saved tasks. ${error.message}`); }
  };
  document.addEventListener("hmb-resume-training-task", async event => {
    if (busy) return;
    busy = true; clearSelection(); switchStage("app");
    try {
      detail = await trainingApi(`/api/training/tasks/${event.detail}`); selectedTask = detail.id; selectedApp = detail.app_id;
      await loadApps(); await showTask(detail);
    } catch (error) { setStatus("trainingAppStatus", `Could not open task. ${error.message}`); }
    finally { busy = false; }
  });
})();
