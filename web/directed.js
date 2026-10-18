(() => {
  const $ = id => document.getElementById(id);
  let current = null, trainingTask = null, recorder = null, mediaStream = null,
      chunks = [], recording = false, completeMedia = false, busy = false,
      failedBlob = null, sizeTotal = 0, readOnly = false, historicalView = false, failedCapture = false;

  const say = msg => { $("directedStatus").textContent = msg; };

  async function request(path, options = {}) {
    const isBlob = options.body instanceof Blob;
    const response = await fetch(path, {
      ...options,
      headers: { ...(isBlob ? {} : {"Content-Type": "application/json"}), ...options.headers },
    });
    if (!response.ok) {
      if (response.status >= 500) throw new Error("The local workspace returned an error. Check its local server log and retry.");
      const raw = await response.text();
      let data;
      try { data = JSON.parse(raw); } catch { data = { detail: raw }; }
      throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
    }
    return response.json();
  }

  function add(tag, value, parent, className) {
    const el = document.createElement(tag);
    if (value) el.textContent = value;
    if (className) el.className = className;
    if (parent) parent.append(el);
    return el;
  }

  function refreshReady() {
    $("directedReview").disabled = (readOnly ? !current?.media_url : (!$("directedGoal").value.trim() || !$("directedDone").value.trim() || !completeMedia || !$("directedComplete").checked)) || recording || busy;
    syncControls();
  }

  function stopTracks() {
    mediaStream?.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }

  function waitForPlayable(video) {
    return new Promise((resolve, reject) => {
      const finish = error => {
        clearTimeout(timeout);
        video.onloadeddata = null;
        video.onerror = null;
        error ? reject(error) : resolve();
      };
      const timeout = setTimeout(() => finish(new Error("The video did not become playable.")), 10000);
      video.onloadeddata = () => finish();
      video.onerror = () => finish(new Error("The video could not be played."));
      video.load();
    });
  }

  function syncControls() {
    const locked = busy || recording;
    for (const id of ["directedEditDetails", "directedRecord", "directedReview"]) {
      $(id).disabled = locked || (readOnly && id === "directedRecord") || (id === "directedReview" && (readOnly ? !current?.media_url : (!completeMedia || !$("directedComplete").checked)));
    }
    $("directedImport").disabled = locked || readOnly;
    $("directedComplete").disabled = locked || readOnly || !completeMedia;
    $("directedReview").textContent = readOnly ? "View saved understanding" : "Review what it learned";
    const replacing = !!current?.media_url;
    $("directedRecord").textContent = replacing ? "Replace recording" : "Record screen";
    $("directedImportLabel").querySelector("span").textContent = replacing ? "Import replacement" : "Import video";
    $("directedReplacementNote").hidden = !replacing || readOnly;
    window.hmbDirectedIsBusy = () => busy || recording;
  }

  function showStage(which) {
    $("directedDescribeStage").hidden = which !== "describe";
    $("directedRecordStage").hidden = which !== "record";
    $("directedForm").hidden = which !== "record";
    if (which === "record") {
      const name = trainingTask?.name || current?.answers?.teaching_task_name || "Task";
      $("directedTaskSummary").textContent = `${name} · ${$("directedGoal").value.trim()} · Done when: ${$("directedDone").value.trim()}`;
      const version = current?.training?.version || trainingTask?.latest_version || 1;
      const label = historicalView ? "Historical" : readOnly ? "Last tested" : "Training";
      $("directedVersionSummary").textContent = `${label} version ${version}. ${readOnly ? "Read-only. Return to current task details to edit or create a new training version." : "Recording is saved only to this version."}`;
    }
  }

  function resetRecordingInputs() {
    $("directedGoal").value = "";
    $("directedDone").value = "";
    $("directedComplete").checked = false;
    $("directedVideo").removeAttribute("src");
    $("directedVideo").hidden = true;
  }

  async function ensureSession() {
    const goal = $("directedGoal").value.trim(), done = $("directedDone").value.trim();
    if (!current?.id) throw new Error("Choose an app and save a task before recording.");
    current = await request(`/api/sessions/${current.id}`);
    const name = trainingTask?.name || current.answers?.teaching_task_name || "Task";
    if ((current.answers?.teaching_task_name || "Task") === name && current.answers?.teaching_goal === goal && current.answers?.teaching_done === done) return current;
    if (readOnly) throw new Error("This tested version is read-only. Edit the task to create a new training version first.");
    const answers = {...(current.answers || {}), teaching_task_name: name, teaching_goal: goal, teaching_done: done};
    current = await request(`/api/sessions/${current.id}`, {method: "PUT", body: JSON.stringify({title: `Training · ${answers.teaching_task_name}`, answers})});
    return current;
  }

  async function retain(blob) {
    busy = true; refreshReady();
    try {
      if (!blob.size) throw new Error("The video is empty. Record or import another example.");
      if (blob.size > 100 * 1024 * 1024) throw new Error("Video exceeds the 100 MB preview limit.");
      failedBlob = blob;
      const task = await ensureSession();
      const result = await request(`/api/sessions/${task.id}/media`, {method: "POST", headers: {"Content-Type": blob.type || "video/webm"}, body: blob});
      current.media_url = result.url;
      const video = $("directedVideo");
      video.src = `${result.url}?t=${Date.now()}`;
      video.hidden = false;
      await waitForPlayable(video);
      completeMedia = true;
      failedBlob = null;
      $("directedRetryUpload").hidden = true;
      $("directedComplete").checked = false;
      $("directedReviewPanel").hidden = true;
      say("Recording saved locally. Review the video, then confirm it shows one complete example.");
    } catch (error) {
      completeMedia = false;
      $("directedRetryUpload").hidden = !failedBlob;
      say(`Could not save the recording. ${error.message}`);
    } finally { busy = false; refreshReady(); }
  }

  $("directedRetryUpload").onclick = () => { if (failedBlob && !busy) retain(failedBlob); };

  $("directedRecord").onclick = async () => {
    if (busy || recording) return;
    busy = true; refreshReady();
    try {
      if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) throw new Error("Screen recording is unavailable here. Import a video instead.");
      mediaStream = await navigator.mediaDevices.getDisplayMedia({video: true, audio: false});
      mediaStream.getVideoTracks().forEach(track => { track.onended = () => { if (recorder?.state === "recording") recorder.stop(); }; });
      chunks = []; sizeTotal = 0;
      const mime = ["video/webm;codecs=vp9", "video/webm"].find(type => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(mediaStream, mime ? {mimeType: mime} : {});
      failedCapture = false;
      recorder.ondataavailable = event => {
        if (!event.data.size) return;
        sizeTotal += event.data.size;
        if (sizeTotal > 100 * 1024 * 1024) {
          failedCapture = true; chunks = [];
          say("The video exceeded 100 MB and was discarded. Record a shorter example.");
          if (recorder.state === "recording") recorder.stop();
          return;
        }
        chunks.push(event.data);
      };
      recorder.onerror = () => {
        failedCapture = true; stopTracks(); recording = false;
        $("directedRecord").hidden = false; $("directedStop").hidden = true;
        say("Recording failed. The partial video will be discarded; try again or import a video.");
        refreshReady();
      };
      recorder.onstop = async () => {
        recording = false; $("directedRecord").hidden = false; $("directedStop").hidden = true;
        stopTracks();
        if (failedCapture) { chunks = []; refreshReady(); return; }
        await retain(new Blob(chunks, {type: recorder.mimeType || "video/webm"}));
      };
      recorder.start(1000); recording = true; busy = false;
      $("directedRecord").hidden = true; $("directedStop").hidden = false;
      say("Recording. Perform the whole task, then choose Done showing.");
      refreshReady();
    } catch (error) {
      busy = false; stopTracks();
      say(`Screen recording did not start. ${error.message}`);
      refreshReady();
    }
  };

  $("directedStop").onclick = () => { if (recorder?.state === "recording") recorder.stop(); };

  $("directedImport").onchange = async event => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) await retain(file);
  };

  document.addEventListener("click", event => {
    if (!recording && !busy) return;
    if (event.target.closest("#directedStop")) return;
    if (event.target.closest("[data-view], .brand, #trainingBackToApps, #trainingBackToTasks, #trainingRecordContinue, #directedEditDetails")) {
      event.preventDefault(); event.stopImmediatePropagation();
      say("Stop and save this recording before leaving the task.");
    }
  }, true);

  window.addEventListener("beforeunload", event => { if (recording || busy) { event.preventDefault(); event.returnValue = ""; } });
  $("directedComplete").onchange = refreshReady;

  $("directedReview").onclick = async () => {
    if (readOnly) {
      if (!current?.id || busy) return;
      busy = true; refreshReady(); say("Loading the saved understanding…");
      try { renderReview(await request(`/api/sessions/${current.id}/teaching-review`)); }
      catch (error) { say(`Could not load the saved understanding. ${error.message}`); }
      finally { busy = false; refreshReady(); }
      return;
    }
    if (!completeMedia || !$("directedComplete").checked || busy) return;
    busy = true; refreshReady(); say("Saving your task details and requesting the review…");
    try {
      let task = await ensureSession();
      task = await request(`/api/sessions/${task.id}`, {method: "PUT", body: JSON.stringify({answers: {...(task.answers || {}), teaching_recording_confirmed: "yes"}})});
      current = task;
      const panel = $("directedReviewPanel");
      panel.replaceChildren(); panel.hidden = false;
      renderReview(await request(`/api/sessions/${task.id}/teaching-review`));
    } catch (error) {
      say(`Review is not available yet. Your recording and task details are saved. ${error.message}`);
    } finally { busy = false; refreshReady(); }
  };

  function renderReview(data) {
    const panel = $("directedReviewPanel");
    panel.replaceChildren();
    document.dispatchEvent(new CustomEvent("hmb-training-review"));
    const back = add("button", "← Back to recording", panel, "back-link");
    back.type = "button";
    back.onclick = () => { if (!busy) { panel.hidden = true; document.dispatchEvent(new CustomEvent("hmb-training-record")); } };
    const status = data.status;
    const title = add("h2", status === "ready" ? "Here’s what I understood" : status === "questions" ? "A few things need your input" : status === "stale" ? "This review is out of date" : status === "approved" ? "Understanding approved" : "Review not ready yet", panel);
    title.id = "directedReviewTitle"; title.tabIndex = -1;

    if (status === "stale" && current?.answers?.teaching_correction) {
      add("h3", "Saved correction", panel);
      add("p", current.answers.teaching_correction, panel);
      add("p", "This note is saved with the task but has not been sent to an assistant.", panel, "task-status");
    }

    if (data.proposal && status !== "stale") {
      const proposal = data.proposal;
      for (const observation of proposal.observations || []) add("p", `${Number(observation.timestamp || 0).toFixed(1)}s · ${observation.text}`, panel);
      for (const question of proposal.questions || []) add("p", question.question, panel);
      if (proposal.procedure?.steps?.length) {
        add("h3", "Proposed steps", panel);
        const list = document.createElement("ol");
        for (const step of proposal.procedure.steps) {
          const li = document.createElement("li");
          li.textContent = `${step.goal || "Step"}${step.check ? ` — Check: ${step.check}` : ""}`;
          list.append(li);
        }
        panel.append(list);
      }
    }
    add("p", "Approval records that this interpretation matches your example. It does not authorize running the task. No automatic replay is available here.", panel, "task-status");

    if (status === "waiting") {
      const taskName = trainingTask?.name || current?.answers?.teaching_task_name || "this task";
      add("p", `Your recording is saved. Assistant review is not connected automatically. Ask your connected assistant to review “${taskName}” in HoldMyBeer, then choose Refresh review here.`, panel, "task-status");
      const autoBtn = add("button", "✨ Auto-Review Now (Multiple-Choice — Zero Typing)", panel, "mc-approve-btn");
      autoBtn.type = "button";
      autoBtn.onclick = async () => {
        if (!current?.id || busy) return;
        autoBtn.disabled = true; autoBtn.textContent = "Analyzing recording…";
        try {
          const reviewData = await request(`/api/sessions/${current.id}/auto-review`, {method: "POST", body: JSON.stringify({})});
          const mcContainer = document.createElement("div");
          panel.append(mcContainer);
          renderMultipleChoiceUI(mcContainer, current.id, reviewData);
        } catch (err) {
          say(err.message);
        } finally {
          autoBtn.hidden = true;
        }
      };
    }

    if (["waiting", "stale", "questions", "ready"].includes(status)) {
      const refresh = add("button", "Refresh review", panel, "quiet");
      refresh.type = "button";
      refresh.onclick = async () => {
        if (busy) return;
        busy = true; refreshReady(); refresh.disabled = true;
        try { renderReview(await request(`/api/sessions/${current.id}/teaching-review`)); }
        catch (error) { say(error.message); }
        finally { busy = false; refreshReady(); }
      };
    }

    if (["questions", "ready"].includes(status) && !readOnly) {
      if (status === "questions") add("p", "The interpretation has open questions. Review them and ask your assistant to submit an updated interpretation before approving.", panel, "task-status");
      const correctionLabel = add("label", "What should be corrected in this interpretation?", panel);
      correctionLabel.htmlFor = "directedCorrection";
      const correction = document.createElement("textarea");
      correction.id = "directedCorrection"; correction.maxLength = 1000;
      panel.append(correction);
      const saveCorrection = add("button", "Save correction", panel, "quiet");
      saveCorrection.type = "button"; saveCorrection.disabled = true;
      correction.oninput = () => { saveCorrection.disabled = !correction.value.trim() || busy; };
      saveCorrection.onclick = async () => {
        if (busy) return;
        busy = true; refreshReady(); saveCorrection.disabled = true;
        try {
          const fresh = await request(`/api/sessions/${current.id}`);
          current = await request(`/api/sessions/${fresh.id}`, {method: "PUT", body: JSON.stringify({answers: {...(fresh.answers || {}), teaching_correction: correction.value.trim()}})});
          renderReview(await request(`/api/sessions/${current.id}/teaching-review`));
          add("p", "Correction saved in this task. It was not sent to an assistant; the prior review may now be stale.", panel, "task-status");
        } catch (error) {
          say(`Could not save the correction. ${error.message}`);
          saveCorrection.disabled = false;
        } finally { busy = false; refreshReady(); }
      };
    }

    if (status === "ready" && !readOnly) {
      const approve = add("button", "Approve this understanding", panel, "primary");
      approve.type = "button";
      approve.onclick = async () => {
        if (busy) return;
        busy = true; refreshReady(); approve.disabled = true;
        try {
          renderReview(await request(`/api/sessions/${current.id}/teaching-review/approve`, {method: "POST", body: JSON.stringify({proposal_id: data.proposal.id, consent: true})}));
        } catch (error) {
          say(`Could not approve the interpretation. ${error.message}`);
          approve.disabled = false;
        } finally { busy = false; refreshReady(); }
      };
    }

    if (status === "approved") add("p", "Nothing has been executed.", panel);
    if (readOnly) add("p", "This tested version is read-only. You can view its saved understanding; edit the task to create a new training version.", panel, "task-status");
    title.focus();
    say("Review updated.");
  }

  document.addEventListener("hmb-new-directed", () => {
    current = null; trainingTask = null; completeMedia = false; failedBlob = null; readOnly = false; historicalView = false;
    resetRecordingInputs();
    $("directedRetryUpload").hidden = true;
    $("directedReviewPanel").replaceChildren(); $("directedReviewPanel").hidden = true;
    showStage("describe"); say("Choose an app and task to get started."); refreshReady();
  });

  document.addEventListener("hmb-training-session", event => {
    current = event.detail.session || null; trainingTask = event.detail.task || null;
    historicalView = !!event.detail.historical;
    readOnly = historicalView || !!(trainingTask?.working_version && current?.training?.version === trainingTask.working_version);
    $("directedGoal").value = current?.answers?.teaching_goal || trainingTask?.description || "";
    $("directedDone").value = current?.answers?.teaching_done || "";
    $("directedVideo").removeAttribute("src"); $("directedVideo").hidden = true;
    completeMedia = false; $("directedComplete").checked = false;
    $("directedReviewPanel").replaceChildren(); $("directedReviewPanel").hidden = true;
    refreshReady();
  });

  document.addEventListener("hmb-training-start-record", async event => {
    if (!current?.id || busy) return;
    busy = true; refreshReady();
    try {
      const task = (event.detail?.historical || readOnly) ? current : await ensureSession();
      $("directedComplete").checked = false; completeMedia = false;
      $("directedVideo").removeAttribute("src"); $("directedVideo").hidden = true;
      if (task.media_url) {
        const video = $("directedVideo");
        video.src = `${task.media_url}?t=${Date.now()}`;
        video.hidden = false;
        try { await waitForPlayable(video); completeMedia = true; say("Saved video loaded. Review it and confirm it shows one complete example."); }
        catch (error) { completeMedia = false; say(`Saved video could not be played. ${error.message}`); }
      } else say("Record or import one complete example.");
      showStage("record"); $("directedRecordTitle").focus();
      if (readOnly) say(`${historicalView ? "Historical" : "Last tested"} version is read-only. You can review its saved video; return to current task details to edit or create a new training version.`);
    } catch (error) {
      say(`Could not open this version. ${error.message}`);
      document.dispatchEvent(new CustomEvent("hmb-training-back-to-details"));
    } finally { busy = false; refreshReady(); }
  });

  $("directedEditDetails").onclick = () => {
    if (!busy && !recording) document.dispatchEvent(new CustomEvent("hmb-training-back-to-details"));
  };
  document.addEventListener("hmb-training-review", () => { showStage("review"); });

  function renderRecipeCard(card) {
    const panel = $("recipeCardPanel");
    if (!panel || !card) return;
    panel.replaceChildren();
    add("p", "3-LINE RECIPE CARD", panel, "eyebrow");
    add("h3", card.title || "Workflow Recipe", panel);
    const dl = add("dl", "", panel, "receipt-fields");
    add("dt", "When you give me", dl);
    add("dd", Array.isArray(card.when_you_give_me) ? card.when_you_give_me.join("; ") : String(card.when_you_give_me || ""), dl);
    add("dt", "I will do", dl);
    add("dd", Array.isArray(card.i_will_do) ? card.i_will_do.join(" → ") : String(card.i_will_do || ""), dl);
    add("dt", "You will get", dl);
    add("dd", String(card.you_will_get || ""), dl);
    panel.hidden = false;
  }

  async function refreshRecipeCard() {
    const tid = trainingTask?.id || current?.id;
    if (!tid || !$("recipeCardPanel")) return;
    try { renderRecipeCard(await request(`/api/tasks/${encodeURIComponent(tid)}/recipe-card`)); }
    catch { /* ignore for sessions without recipe card */ }
  }

  if ($("quickRecordBegin")) {
    $("quickRecordBegin").onclick = async () => {
      if (busy || recording) return;
      busy = true;
      try {
        const qr = await request("/api/quick-record", {method: "POST", body: JSON.stringify({})});
        window.hmbShowView?.("directed");
        for (const id of ["trainingAppStage", "trainingTaskStage", "trainingDescriptionStage"]) {
          if ($(id)) $(id).hidden = true;
        }
        current = qr.session; trainingTask = qr.task;
        readOnly = false; historicalView = false; completeMedia = false;
        resetRecordingInputs();
        if ($("quickRecordBanner")) {
          $("quickRecordBanner").hidden = false;
          $("quickRecordNameInput").value = qr.task_name || "Quick Workflow #1";
        }
        if ($("sandboxDiffOutput")) {
          $("sandboxDiffOutput").hidden = true;
          $("sandboxDiffOutput").replaceChildren();
        }
        showStage("record");
        renderRecipeCard(qr.recipe_card);
        say("Instant record ready. Record or import one example, or rename anytime.");
      } catch (error) {
        say(`Could not start instant record. ${error.message}`);
      } finally { busy = false; refreshReady(); }
    };
  }

  if ($("quickRecordSaveName")) {
    $("quickRecordSaveName").onclick = async () => {
      const tid = trainingTask?.id || current?.id;
      const newName = $("quickRecordNameInput")?.value.trim();
      if (!tid || !newName || busy) return;
      busy = true;
      try {
        const res = await request(`/api/tasks/${encodeURIComponent(tid)}/quick-rename`, {
          method: "PUT", body: JSON.stringify({task_name: newName}),
        });
        if (trainingTask) trainingTask.name = res.task_name;
        if (current?.answers) current.answers.teaching_task_name = res.task_name;
        showStage("record");
        renderRecipeCard(res.recipe_card);
        say(`Renamed workflow to ${res.task_name}.`);
      } catch (error) {
        say(`Could not rename workflow. ${error.message}`);
      } finally { busy = false; refreshReady(); }
    };
  }

  if ($("sandboxDryRunBtn")) {
    $("sandboxDryRunBtn").onclick = async () => {
      const tid = trainingTask?.id || current?.id;
      if (!tid || busy) return;
      busy = true;
      $("sandboxDryRunBtn").disabled = true;
      try {
        const res = await request(`/api/tasks/${encodeURIComponent(tid)}/hybrid-run`, {
          method: "POST", body: JSON.stringify({dry_run: true}),
        });
        const out = $("sandboxDiffOutput");
        if (out) {
          out.replaceChildren();
          const diff = res.before_after_diff || {};
          const filesAfter = (diff.files_after || []).join(", ");
          add("p", `Sandbox Dry-Run ${res.status === "verified" ? "Verified" : "Needs Agent Assist"} (real files untouched). Files after: ${filesAfter}`, out);
          out.hidden = false;
        }
        await refreshRecipeCard();
      } catch (error) {
        say(`Sandbox dry-run failed. ${error.message}`);
      } finally {
        busy = false; $("sandboxDryRunBtn").disabled = false; refreshReady();
      }
    };
  }

  // -------------------------------------------------------------------------
  // Record -> Stop -> Name and save. Agent review remains a separate step.
  // -------------------------------------------------------------------------
  let ocRecorder = null, ocStream = null, ocChunks = [], ocTimerInterval = null,
      ocStartTime = 0, ocSession = null, ocNativeSessionId = null, ocWindowTitle = "";

  const ocStatus = msg => { if ($("oneClickStatus")) $("oneClickStatus").textContent = msg; };

  function stopOcStream() {
    if (ocTimerInterval) { clearInterval(ocTimerInterval); ocTimerInterval = null; }
    if (ocStream) { ocStream.getTracks().forEach(t => t.stop()); ocStream = null; }
  }

  function setOcRecordingUI(isRec) {
    if ($("oneClickRecordBtn")) $("oneClickRecordBtn").hidden = isRec;
    if ($("oneClickStopBtn")) $("oneClickStopBtn").hidden = !isRec;
  }

  if ($("mcModalClose")) {
    $("mcModalClose").onclick = () => { if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true; };
  }

  // Easy: name and save. Admin: configure a template and inspect tools.
  function renderMultipleChoiceUI(container, sessionId, reviewData) {
    const useModal = Boolean($("mcModalOverlay") && $("mcModalBody") && container?.id === "oneClickReviewCard");
    const target = useModal ? $("mcModalBody") : container;
    if (useModal) {
      $("mcModalOverlay").hidden = false;
      container.hidden = false;
      container.replaceChildren();
      const reopen = add("button", "Continue setting up your last recording", container, "quiet");
      reopen.type = "button";
      reopen.onclick = () => { $("mcModalOverlay").hidden = false; };
    } else {
      container.hidden = false;
    }

    let currentMode = localStorage.getItem("hmb_user_mode") || "easy";
    let currentPageRenderer = null;

    function syncModeUI() {
      const easy = currentMode === "easy";
      $("hmbModeEasyBtn")?.classList.toggle("active", easy);
      $("hmbModeAdminBtn")?.classList.toggle("active", !easy);
    }

    function setMode(mode) {
      currentMode = mode;
      localStorage.setItem("hmb_user_mode", mode);
      syncModeUI();
      if (currentPageRenderer) currentPageRenderer();
    }

    if ($("hmbModeEasyBtn")) $("hmbModeEasyBtn").onclick = () => setMode("easy");
    if ($("hmbModeAdminBtn")) $("hmbModeAdminBtn").onclick = () => setMode("admin");
    syncModeUI();

    const badge = text => { if ($("mcStepBadge")) $("mcStepBadge").textContent = text; };
    const state = {
      app: "",
      task: "",
      taskId: reviewData.task_id,
      choices: {
        q_action: "recorded_flow",
        q_input: "same_target",
        q_done: "window_minimized",
        q_safety: "sandbox_first",
      },
    };
    const rawQuestions = reviewData.adaptive_questions || reviewData.multiple_choice_questions || [];
    let questions = rawQuestions.slice(0, 3);
    for (const q of questions) state.choices[q.id] = q.selected || q.options?.[0]?.id || "";

    // ---------- Step 1: Name it ----------
    function pageName() {
      currentPageRenderer = pageName;
      badge(currentMode === "admin" ? "STEP 1 OF 3 · NAME IT" : "NAME YOUR RECORDING");
      target.replaceChildren();
      const head = add("h2", "Give this task a name", target, "hmb-wiz-title");
      head.tabIndex = -1;

      const grid = add("div", "", target, "mc-top-grid");
      const vid = document.createElement("video");
      vid.controls = true; vid.playsInline = true; vid.preload = "metadata"; vid.muted = true;
      vid.src = `${reviewData.media_url || `/api/sessions/${sessionId}/media`}?t=${Date.now()}`;
      grid.append(vid);

      const fields = add("div", "", grid, "hmb-fields");

      // App Name combobox
      const appLabel = add("label", "App", fields);
      appLabel.htmlFor = "hmbAppInput";
      const appInput = document.createElement("input");
      appInput.id = "hmbAppInput";
      appInput.setAttribute("list", "hmbAppList");
      appInput.maxLength = 100;
      appInput.value = state.app || "";
      appInput.placeholder = "Choose an app, or type a new one…";
      appInput.autocomplete = "off";
      fields.append(appInput);

      const datalist = add("datalist", "", fields);
      datalist.id = "hmbAppList";
      add("small", "Enter the name of your app", fields, "hmb-field-hint");

      let appOptions = Array.from(new Set([
        ...(reviewData.app_options || []),
        ...(reviewData.detected_app ? [reviewData.detected_app] : []),
      ])).filter(Boolean);

      function populateAppDropdown(options) {
        datalist.replaceChildren();
        for (const opt of options) {
          const dOpt = document.createElement("option");
          dOpt.value = opt;
          datalist.append(dOpt);
        }
      }
      populateAppDropdown(appOptions);

      request("/api/training/apps").then(res => {
        if (res?.apps) {
          let updated = false;
          for (const a of res.apps) {
            if (a.name && !appOptions.includes(a.name)) {
              appOptions.push(a.name);
              updated = true;
            }
          }
          if (updated) populateAppDropdown(appOptions);
        }
      }).catch(() => {});

      appInput.onclick = () => {
        try { appInput.showPicker?.(); } catch {}
      };

      // Task Name
      const taskLabel = add("label", "Task title", fields);
      taskLabel.htmlFor = "hmbTaskInput";
      const taskInput = document.createElement("input");
      taskInput.id = "hmbTaskInput";
      taskInput.maxLength = 160;
      taskInput.value = state.task || "";
      taskInput.placeholder = "e.g. Resize image to 1080px, Organize files…";
      fields.append(taskInput);
      add("small", "Use a short title you’ll recognize later. You’ll review the steps with your assistant.", fields, "hmb-field-hint");

      if (currentMode === "admin") {
        const adminBox = add("div", "", fields, "hmb-admin-section");
        adminBox.style.marginTop = "10px";
        adminBox.innerHTML = `
          <div class="hmb-admin-section-title">⚙️ Admin Metadata</div>
          <div style="font-size:11px; color:#555; line-height:1.6;">
            <div>Window: <strong>${escapeText(reviewData.window_title || reviewData.detected_app || "Not supplied")}</strong></div>
            <div>Display: <code>${escapeText(reviewData.display || "Not supplied")}</code></div>
            <div>Duration: <strong>${escapeText(reviewData.duration_seconds || "Not supplied")}</strong></div>
            <div>Session ID: <code>${escapeText(sessionId)}</code></div>
          </div>
        `;
      }

      const next = add("button", currentMode === "admin" ? "Next →" : "Save recording", target, "mc-approve-btn");
      next.id = "hmbNameNext";
      next.type = "button";
      const note = add("p", "", target, "task-status");

      function validate() {
        state.app = appInput.value.trim();
        state.task = taskInput.value.trim();
        next.disabled = !state.app || !state.task;
      }

      appInput.oninput = validate;
      taskInput.oninput = validate;
      for (const inp of [appInput, taskInput]) {
        inp.onkeydown = e => { if (e.key === "Enter" && !next.disabled) next.click(); };
      }
      validate();

      next.onclick = async () => {
        next.disabled = true; next.textContent = "Saving…";
        try {
          const saved = await request(`/api/sessions/${sessionId}/name`, {
            method: "POST",
            body: JSON.stringify({app_name: appInput.value.trim(), task_name: taskInput.value.trim()}),
          });
          state.app = saved.app_name;
          state.task = saved.task_name;
          state.taskId = saved.task_id;
          if (saved.questions?.length) {
            questions = saved.questions.slice(0, 3);
            for (const q of questions) state.choices[q.id] = q.selected || q.options?.[0]?.id || "";
          }
          pageSmartTuning();
        } catch (err) {
          note.textContent = `Could not save the name: ${err.message}`;
          next.disabled = false; next.textContent = currentMode === "admin" ? "Next →" : "Save recording";
        }
      };

      (appInput.value ? taskInput : appInput).focus();
    }

    // ---------- Step 2: Smart Tuning / Activation ----------
    function pageSmartTuning() {
      if (currentMode !== "admin") { finish(); return; }
      currentPageRenderer = pageSmartTuning;
      badge("STEP 2 OF 3 · TEMPLATE SETTINGS");
      target.replaceChildren();

      const top = add("div", "", target);
      top.style.marginBottom = "8px";
      const heading = add("h2", "Task template settings", top, "hmb-wiz-title");
      heading.tabIndex = -1;
      add("p", `${state.task} in ${state.app}`, top, "eyebrow");

      // Admin Mode: Full Tuning Grid
      const grid = add("div", "", target, "hmb-tune-grid");
      const tuneRows = [
        {
          icon: "⚡", title: "Input & Target", desc: "Save your preference for an assistant to review.",
          options: [
            { id: "same_target", label: "Same Target", desc: "Request the same target each time" },
            { id: "ask_each_time", label: "Ask for Input", desc: "Ask for target/parameters before running" },
          ],
          current: state.choices.q_input,
          onSelect: val => { state.choices.q_input = val; },
        },
        {
          icon: "👁️", title: "Completion Check", desc: "What result should the assistant check?",
          options: [
            { id: "window_minimized", label: "App Completes", desc: "When window closes or action completes" },
            { id: "verified_output", label: "Receipt / File Saved", desc: "When verified output file exists" },
          ],
          current: state.choices.q_done,
          onSelect: val => { state.choices.q_done = val; },
        },
        {
          icon: "🛡️", title: "Safety & Sandboxing", desc: "Save a preference. This does not authorize a live run.",
          options: [
            { id: "sandbox_first", label: "Safe Sandbox First", desc: "Check supported file actions with samples" },
            { id: "pause_immediately", label: "Pause & Ask Me", desc: "Always confirm before running" },
          ],
          current: state.choices.q_safety,
          onSelect: val => { state.choices.q_safety = val; },
        },
      ];
      for (const rowConfig of tuneRows) grid.append(createTuneRow(rowConfig));

      // Step Navigation
      const nav = add("div", "", target, "mc-step-nav");
      nav.style.marginTop = "14px";
      const back = add("button", "← Back to naming", nav, "quiet");
      back.type = "button"; back.onclick = pageName;

      const finishBtn = add("button", "Save task settings", nav, "primary");
      finishBtn.id = "oneClickApproveBtn"; finishBtn.type = "button";
      finishBtn.style.padding = "10px 22px"; finishBtn.style.fontSize = "15px";
      finishBtn.onclick = finish;

      const toggleWrap = add("div", "", target);
      toggleWrap.style.textAlign = "center"; toggleWrap.style.marginTop = "10px";
      const toggleBtn = add("button", "Switch to Simple Mode", toggleWrap, "hmb-admin-toggle");
      toggleBtn.type = "button";
      toggleBtn.onclick = () => setMode("easy");

      heading.focus();
    }

    function createTuneRow({icon, title, desc, options, current, onSelect}) {
      const row = document.createElement("div");
      row.className = "hmb-tune-row";
      const hdr = add("div", "", row, "hmb-tune-header");
      hdr.innerHTML = `<span class="hmb-tune-icon">${icon}</span><div><strong>${title}</strong><small>${desc}</small></div>`;

      const pills = add("div", "", row, "hmb-tune-pills");
      for (const opt of options) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `hmb-tune-pill${opt.id === current ? " selected" : ""}`;
        btn.innerHTML = `<span class="pill-title">${opt.label}</span><span class="pill-desc">${opt.desc}</span>`;
        btn.onclick = () => {
          pills.querySelectorAll(".hmb-tune-pill").forEach(b => b.classList.remove("selected"));
          btn.classList.add("selected");
          onSelect(opt.id);
        };
        pills.append(btn);
      }
      return row;
    }

    // ---------- Admin tools after saving ----------
    let finishData = null;

    function returnToSaved() {
      if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
      container.hidden = true;
      window.hmbShowView?.("saved");
      toast("Your recording is saved.");
    }

    async function finish() {
      badge("STEP 3 OF 3 · SAVING");
      target.replaceChildren();
      add("h2", "Saving your recording…", target, "hmb-wiz-title");
      try {
        finishData = await request(`/api/sessions/${sessionId}/answer-choices`, {
          method: "POST",
          body: JSON.stringify({selected_name: state.task, choices: state.choices, run_sandbox: false}),
        });
      } catch (err) {
        target.replaceChildren();
        add("h2", "Could not save workflow", target, "hmb-wiz-title");
        add("p", err.message, target, "task-status");
        const retry = add("button", "Try again", target, "mc-approve-btn");
        retry.type = "button"; retry.onclick = finish;
        return;
      }
      state.taskId = finishData.task_id || state.taskId;
      if (currentMode === "admin") renderFinishPage();
      else returnToSaved();
    }

    const escapeText = value => { const node = document.createElement("span"); node.textContent = value; return node.innerHTML; };

    function renderFinishPage() {
      currentPageRenderer = renderFinishPage;
      const isAdmin = currentMode === "admin";
      if (!isAdmin) { returnToSaved(); return; }
      badge("ADMIN · TASK TOOLS");
      target.replaceChildren();

      const res = finishData || {};
      const cleanTask = (res.task_name || state.task).trim();
      const cleanApp = (res.app_name || state.app || "the app").trim();

      async function runSandbox({btn, receipt, parameters, successTitle, successBody, failTitle, idleText}) {
        btn.disabled = true;
        btn.textContent = "Checking sample files…";
        receipt.style.display = "block";
        receipt.innerHTML = `<span style="color:#777;">Checking a template with temporary sample files…</span>`;
        try {
          const run = await request(`/api/tasks/${encodeURIComponent(state.taskId)}/hybrid-run`, {
            method: "POST", body: JSON.stringify({dry_run: true, parameters: parameters || {}}),
          });
          if (run.status === "verified") {
            const count = (run.steps || []).length || 1;
            receipt.innerHTML = `
              <div style="color:#2d6914; font-weight:700; margin-bottom:4px;">✔ ${successTitle(count)}</div>
              ${successBody}
            `;
          } else {
            const observed = run.diagnostic_snapshot?.observed_state;
            const reason = typeof observed === "string" ? observed : observed?.reason;
            receipt.innerHTML = `
              <div style="color:#b25900; font-weight:700;">⚠️ ${failTitle}</div>
              <div style="font-size:12px; color:#444;">${escapeText(reason || "This task needs assistant review before it can run.")}</div>
            `;
          }
        } catch (err) {
          receipt.innerHTML = `<span style="color:#a1261d;">❌ Could not run: ${escapeText(err.message)}</span>`;
        } finally {
          btn.disabled = false;
          btn.textContent = idleText;
        }
      }


      {
        // Admin Mode: Technical admin metadata, agent connectors, parameter test drive
        const headBox = add("div", "", target);
        headBox.style.marginBottom = "10px";
        const title = add("h2", `🛠️ Task Administration: ${cleanTask}`, headBox, "hmb-wiz-title");
        title.tabIndex = -1;
        add("p", `Task ID: ${state.taskId} · App: ${cleanApp} · Unverified recipe template`, headBox, "eyebrow");

        // Agent connection options
        const agentSection = add("div", "", target, "hmb-admin-section");
        agentSection.innerHTML = `
          <div class="hmb-admin-section-title">🤖 Agent connection options</div>
          <div class="hmb-agent-row">
            <div><strong>Claude Code / Desktop</strong><br><small style="color:#666;">MCP dynamic tool</small></div>
            <code>claude mcp add holdmybeer uvx holdmybeer mcp</code>
          </div>
          <div class="hmb-agent-row">
            <div><strong>Hermes / Ollie</strong><br><small style="color:#666;">Autonomous worker tool</small></div>
            <code>${escapeText(res.tool_name || "Reconnect your client to discover tools")}</code>
          </div>
          <div class="hmb-agent-row">
            <div><strong>OpenAI / Codex API</strong><br><small style="color:#666;">JSON Schema endpoint</small></div>
            <a href="/api/tools/openai" target="_blank" style="font-size:11px; font-weight:700;">View Tools JSON ↗</a>
          </div>
          <div class="hmb-agent-row">
            <div><strong>Portable SKILL.md</strong><br><small style="color:#666;">Universal skill bundle</small></div>
            <button id="hmbExportSkillBtn" type="button" class="quiet hmb-copy-mini-btn">📥 Export SKILL.md</button>
          </div>
        `;

        const exportBtn = agentSection.querySelector("#hmbExportSkillBtn");
        exportBtn.onclick = async () => {
          exportBtn.disabled = true; exportBtn.textContent = "Exporting…";
          try {
            const exp = await request(`/api/tasks/${encodeURIComponent(state.taskId)}/export-skill`, {method: "POST"});
            exportBtn.textContent = exp.export_dir ? "Exported ✓" : "Downloaded ✓";
            alert(`SKILL.md bundle exported to:\n${exp.export_dir || "downloads"}`);
          } catch (err) {
            alert(`Export note: ${err.message}`);
          } finally { exportBtn.disabled = false; }
        };

        // Test Drive Simulation with Parameters
        const simCard = add("div", "", target, "hmb-done-card");
        simCard.style.marginTop = "10px";
        const simHdr = add("div", "", simCard);
        simHdr.innerHTML = `
          <h3>🧪 Sandbox Test Drive & Diff Inspector</h3>
          <small style="color:var(--muted); font-size:12px; display:block; margin-top:2px;">
            Simulate parameter bindings and inspect before/after sandbox state:
          </small>
        `;

        const simRow = add("div", "", simCard, "hmb-try-row");
        simRow.style.marginTop = "10px";

        const tryInput = document.createElement("input");
        tryInput.id = "hmbTryInput";
        if (res.try_param) {
          tryInput.value = res.try_param.default ?? "yahoo.com";
          tryInput.placeholder = res.try_param.label || "Target or parameter";
          tryInput.setAttribute("aria-label", res.try_param.label || "Target");
        } else {
          tryInput.value = "test-target";
          tryInput.placeholder = "Optional parameter input";
          tryInput.setAttribute("aria-label", "Target");
        }
        simRow.append(tryInput);

        const simBtn = add("button", "Check with sample files", simRow, "primary");
        simBtn.id = "hmbTryBtn"; simBtn.type = "button";
        simBtn.style.padding = "8px 18px"; simBtn.style.whiteSpace = "nowrap";

        const simReceipt = add("div", "", simCard, "hmb-receipt-box");
        simReceipt.id = "hmbTryResult";
        simReceipt.style.display = "none";

        simBtn.onclick = () => {
          const targetVal = tryInput.value.trim() || cleanTask;
          const parameters = res.try_param ? {[res.try_param.name]: tryInput.value.trim()} : {};
          return runSandbox({
            btn: simBtn,
            receipt: simReceipt,
            parameters,
            successTitle: count => `Sample check passed (${count} step${count === 1 ? "" : "s"})`,
            successBody: `
              <div style="font-size:11px; color:#555;">Target: <strong>${escapeText(targetVal)}</strong></div>
              <div style="font-size:11px; color:#555;">Sample files only. This does not test the recorded app or authorize live execution.</div>
            `,
            failTitle: "Needs Attention",
            idleText: "Check with sample files",
          });
        };

        // Natural Voice Speech Box in Admin
        if (res.say_this) {
          const speechCard = add("div", "", target, "hmb-speech-bubble");
          speechCard.id = "oneClickResultBox";
          speechCard.style.marginTop = "10px";
          speechCard.innerHTML = `
            <div>
              <span style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#4a6828; font-weight:700; display:block; margin-bottom:2px;">Suggested phrase (connection required)</span>
              <strong>“${escapeText(res.say_this)}”</strong>
            </div>
          `;
        }
      }

      // Actions in both modes
      const actions = add("div", "", target, "hmb-done-actions");
      actions.style.marginTop = "16px";

      const anotherBtn = add("button", "+ Teach Another Task", actions, "quiet");
      anotherBtn.type = "button";
      anotherBtn.onclick = () => {
        if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
        container.hidden = true;
        $("oneClickRecordBtn")?.focus();
      };

      const allDoneBtn = add("button", "All Done ✓", actions, "primary");
      allDoneBtn.type = "button";
      allDoneBtn.style.padding = "10px 28px"; allDoneBtn.style.fontSize = "15px";
      allDoneBtn.onclick = () => {
        if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
        container.hidden = true;
      };

      const toggleWrap = add("div", "", target);
      toggleWrap.style.textAlign = "center"; toggleWrap.style.marginTop = "12px";
      const toggleBtn = add("button", isAdmin ? "🐣 Switch to Simple Mode" : "⚙️ View Agent MCP Configs & Admin Tools", toggleWrap, "hmb-admin-toggle");
      toggleBtn.type = "button";
      toggleBtn.onclick = () => setMode("easy");

      ocStatus(`Saved “${cleanTask}” for review.`);
    }

    pageName();
  }

  async function processOneClickBlob(blob, windowTitle, durationSec) {
    ocStatus("Saving your recording…");
    try {
      if (!ocSession) {
        const qr = await request("/api/quick-record", {
          method: "POST", body: JSON.stringify({window_title: windowTitle || undefined}),
        });
        ocSession = qr.session;
      }
      const cleanMime = (blob.type || "video/webm").split(";")[0];
      await request(`/api/sessions/${ocSession.id}/media`, {
        method: "POST", headers: {"Content-Type": cleanMime}, body: blob,
      });
      const reviewData = await request(`/api/sessions/${ocSession.id}/auto-review`, {
        method: "POST",
        body: JSON.stringify({
          window_title: windowTitle || undefined,
          duration_seconds: durationSec || 2.0,
        }),
      });
      ocStatus("Recording saved. Give it a name.");
      if ($("oneClickReviewCard")) {
        renderMultipleChoiceUI($("oneClickReviewCard"), ocSession.id, reviewData);
      }
    } catch (err) {
      ocStatus(`Could not prepare recording: ${err.message}`);
    }
  }

  function startTimerTick() {
    ocStartTime = Date.now();
    if ($("oneClickTimer")) $("oneClickTimer").textContent = "00:00";
    if (ocTimerInterval) clearInterval(ocTimerInterval);
    ocTimerInterval = setInterval(() => {
      const sec = Math.max(0, Math.floor((Date.now() - ocStartTime) / 1000));
      const mm = String(Math.floor(sec / 60)).padStart(2, "0");
      const ss = String(sec % 60).padStart(2, "0");
      if ($("oneClickTimer")) $("oneClickTimer").textContent = `${mm}:${ss}`;
    }, 500);
  }

  if ($("oneClickRecordBtn")) {
    $("oneClickRecordBtn").onclick = async () => {
      if (ocRecorder?.state === "recording" || ocNativeSessionId) return;
      try {
        const nativeRes = await request("/api/native-record/start", {method: "POST", body: JSON.stringify({})});
        if (nativeRes?.supported && nativeRes.session_id) {
          ocNativeSessionId = nativeRes.session_id;
          startTimerTick();
          setOcRecordingUI(true);
          ocStatus("Recording your desktop now (no browser popup needed) — click Stop Recording when done.");
          return;
        }
      } catch {
        /* Fall back to the browser screen picker. */
      }

      try {
        if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) {
          ocStatus("Screen recording is unavailable here. Open HoldMyBeer on localhost or import a video file.");
          return;
        }
        ocStream = await navigator.mediaDevices.getDisplayMedia({video: true, audio: false});
        const vTrack = ocStream.getVideoTracks()[0];
        ocWindowTitle = vTrack?.label || "";
        const qr = await request("/api/quick-record", {
          method: "POST", body: JSON.stringify({window_title: ocWindowTitle || undefined}),
        });
        ocSession = qr.session;
        ocChunks = [];
        const mime = ["video/webm;codecs=vp8", "video/webm"].find(t => MediaRecorder.isTypeSupported(t));
        ocRecorder = new MediaRecorder(ocStream, mime ? {mimeType: mime} : {});
        ocRecorder.ondataavailable = e => { if (e.data?.size > 0) ocChunks.push(e.data); };
        startTimerTick();
        if (vTrack) {
          vTrack.onended = () => { if (ocRecorder?.state === "recording") ocRecorder.stop(); };
        }
        ocRecorder.onstop = async () => {
          const elapsed = Math.max(1, (Date.now() - ocStartTime) / 1000);
          stopOcStream();
          setOcRecordingUI(false);
          const blob = new Blob(ocChunks, {type: ocRecorder?.mimeType || "video/webm"});
          if (blob.size > 0) {
            await processOneClickBlob(blob, ocWindowTitle, elapsed);
          }
        };
        ocRecorder.start();
        setOcRecordingUI(true);
        ocStatus("Recording live — perform your task, then click Stop Recording.");
      } catch {
        stopOcStream();
        setOcRecordingUI(false);
        ocStatus("Recording wasn’t started. Choose Start Recording to try again, or import a video file.");
      }
    };
  }

  if ($("oneClickStopBtn")) {
    $("oneClickStopBtn").onclick = async () => {
      if (ocNativeSessionId) {
        const sid = ocNativeSessionId;
        ocNativeSessionId = null;
        stopOcStream();
        setOcRecordingUI(false);
        ocStatus("Saving your recording…");
        try {
          const reviewData = await request(`/api/native-record/${sid}/stop`, {
            method: "POST", body: JSON.stringify({}),
          });
          ocStatus("Recording saved. Give it a name.");
          if ($("oneClickReviewCard")) {
            renderMultipleChoiceUI($("oneClickReviewCard"), sid, reviewData);
          }
        } catch (err) {
          ocStatus(`Error stopping recording: ${err.message}`);
        }
        return;
      }
      if (ocRecorder?.state === "recording") ocRecorder.stop();
    };
  }

  if ($("oneClickImportInput")) {
    $("oneClickImportInput").onchange = async event => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) return;
      ocSession = null;
      await processOneClickBlob(file, file.name.replace(/\.[^.]+$/, ""), 2.5);
    };
  }
})();
