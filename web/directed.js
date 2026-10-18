(() => {
  const $ = id => document.getElementById(id);
  let current = null, trainingTask = null, recorder = null, mediaStream = null, chunks = [], recording = false, completeMedia = false, busy = false, failedBlob = null, sizeTotal = 0, readOnly = false, historicalView = false, failedCapture = false;
  const say = message => { $("directedStatus").textContent = message; };
  async function request(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...(options.body instanceof Blob ? {} : {"Content-Type":"application/json"}), ...options.headers } });
    if (!response.ok) {
      if (response.status >= 500) throw new Error("The local workspace returned an error. Check its local server log and retry.");
      const raw = await response.text(); let data;
      try { data = JSON.parse(raw); } catch { data = {detail:raw}; }
      throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
    }
    return response.json();
  }
  function refreshReady() { $("directedReview").disabled = (readOnly ? !current?.media_url : (!$("directedGoal").value.trim() || !$("directedDone").value.trim() || !completeMedia || !$("directedComplete").checked)) || recording || busy; syncControls(); }
  function stopTracks() { mediaStream?.getTracks().forEach(track => track.stop()); mediaStream = null; }
  function waitForPlayable(video) {
    return new Promise((resolve, reject) => {
      const finish = error => { clearTimeout(timeout); video.onloadeddata = null; video.onerror = null; error ? reject(error) : resolve(); };
      const timeout = setTimeout(() => finish(new Error("The video did not become playable.")), 10000);
      video.onloadeddata = () => finish();
      video.onerror = () => finish(new Error("The video could not be played."));
      video.load();
    });
  }
  function syncControls() {
    const locked = busy || recording;
    for (const id of ["directedEditDetails", "directedRecord", "directedReview"]) $(id).disabled = locked || (readOnly && id === "directedRecord") || (id === "directedReview" && (readOnly ? !current?.media_url : (!completeMedia || !$("directedComplete").checked)));
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
  function detailsChanged() {
    $("directedComplete").checked = false;
    $("directedReviewPanel").hidden = true;
    refreshReady();
  }
  async function ensureSession() {
    const goal = $("directedGoal").value.trim(), done = $("directedDone").value.trim();
    // A name-only task (no pre-record goal/done) can still record; goal/done are inferred
    // later from the recording, so recording entry must not require them here.
    if (!current?.id) throw new Error("Choose an app and save a task before recording.");
    current = await request(`/api/sessions/${current.id}`);
    const name = trainingTask?.name || current.answers?.teaching_task_name || "Task";
    if ((current.answers?.teaching_task_name || "Task") === name && current.answers?.teaching_goal === goal && current.answers?.teaching_done === done) return current;
    if (readOnly) throw new Error("This tested version is read-only. Edit the task to create a new training version first.");
    const answers = {...(current.answers || {}), teaching_task_name:name, teaching_goal:goal, teaching_done:done};
    current = await request(`/api/sessions/${current.id}`, {method:"PUT", body:JSON.stringify({title:`Training · ${answers.teaching_task_name}`, answers})});
    return current;
  }
  async function retain(blob) {
    busy = true; refreshReady();
    try {
      if (!blob.size) throw new Error("The video is empty. Record or import another example.");
      if (blob.size > 100 * 1024 * 1024) throw new Error("Video exceeds the 100 MB preview limit.");
      failedBlob = blob;
      const task = await ensureSession();
      const result = await request(`/api/sessions/${task.id}/media`, {method:"POST", headers:{"Content-Type":blob.type || "video/webm"}, body:blob});
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
      mediaStream = await navigator.mediaDevices.getDisplayMedia({video:true, audio:false});
      mediaStream.getVideoTracks().forEach(track => { track.onended = () => { if (recorder?.state === "recording") recorder.stop(); }; });
      chunks = []; sizeTotal = 0;
      const mime = ["video/webm;codecs=vp9", "video/webm"].find(type => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(mediaStream, mime ? {mimeType:mime} : {});
      failedCapture = false;
      recorder.ondataavailable = event => {
        if (!event.data.size) return;
        sizeTotal += event.data.size;
        if (sizeTotal > 100 * 1024 * 1024) { failedCapture = true; chunks = []; say("The video exceeded 100 MB and was discarded. Record a shorter example."); if (recorder.state === "recording") recorder.stop(); return; }
        chunks.push(event.data);
      };
      recorder.onerror = () => { failedCapture = true; stopTracks(); recording = false; $("directedRecord").hidden = false; $("directedStop").hidden = true; say("Recording failed. The partial video will be discarded; try again or import a video."); refreshReady(); };
      recorder.onstop = async () => {
        recording = false; $("directedRecord").hidden = false; $("directedStop").hidden = true;
        stopTracks();
        if (failedCapture) { chunks = []; refreshReady(); return; }
        await retain(new Blob(chunks, {type:recorder.mimeType || "video/webm"}));
      };
      recorder.start(1000); recording = true; busy = false; $("directedRecord").hidden = true; $("directedStop").hidden = false;
      say("Recording. Perform the whole task, then choose Done showing."); refreshReady();
    } catch (error) { busy = false; stopTracks(); say(`Screen recording did not start. ${error.message}`); refreshReady(); }
  };
  $("directedStop").onclick = () => { if (recorder?.state === "recording") recorder.stop(); };
  $("directedImport").onchange = async event => { const file = event.target.files?.[0]; event.target.value = ""; if (file) await retain(file); };
  document.addEventListener("click", event => {
    if (!recording && !busy) return;
    if (event.target.closest("#directedStop")) return;
    if (event.target.closest("[data-view], .brand, #trainingBackToApps, #trainingBackToTasks, #trainingRecordContinue, #directedEditDetails") && !event.target.closest("#directedStop")) { event.preventDefault(); event.stopImmediatePropagation(); say("Stop and save this recording before leaving the task."); }
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
      task = await request(`/api/sessions/${task.id}`, {method:"PUT", body:JSON.stringify({answers:{...(task.answers || {}), teaching_recording_confirmed:"yes"}})});
      current = task;
      const panel = $("directedReviewPanel"); panel.replaceChildren(); panel.hidden = false;
      const response = await request(`/api/sessions/${task.id}/teaching-review`);
      renderReview(response);
    } catch (error) { say(`Review is not available yet. Your recording and task details are saved. ${error.message}`); }
    finally { busy = false; refreshReady(); }
  };
  function add(tag, value, parent, className) { const element = document.createElement(tag); element.textContent = value; if (className) element.className = className; parent.append(element); return element; }
  function renderReview(data) {
    const panel = $("directedReviewPanel"); panel.replaceChildren();
    document.dispatchEvent(new CustomEvent("hmb-training-review"));
    const back = add("button", "← Back to recording", panel, "back-link"); back.type = "button"; back.onclick = () => { if (!busy) { panel.hidden = true; document.dispatchEvent(new CustomEvent("hmb-training-record")); } };
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
        for (const step of proposal.procedure.steps) { const li = document.createElement("li"); li.textContent = `${step.goal || "Step"}${step.check ? ` — Check: ${step.check}` : ""}`; list.append(li); }
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
        autoBtn.disabled = true;
        autoBtn.textContent = "Analyzing recording…";
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
    if (["waiting", "stale", "questions", "ready"].includes(status)) { const refresh = add("button", "Refresh review", panel, "quiet"); refresh.type = "button"; refresh.onclick = async () => { if (busy) return; busy = true; refreshReady(); refresh.disabled = true; try { renderReview(await request(`/api/sessions/${current.id}/teaching-review`)); } catch (error) { say(error.message); } finally { busy = false; refreshReady(); } }; }
    if (["questions", "ready"].includes(status) && !readOnly) {
      if (status === "questions") add("p", "The interpretation has open questions. Review them and ask your assistant to submit an updated interpretation before approving.", panel, "task-status");
      const correctionLabel = add("label", "What should be corrected in this interpretation?", panel); correctionLabel.htmlFor = "directedCorrection";
      const correction = document.createElement("textarea"); correction.id = "directedCorrection"; correction.maxLength = 1000; panel.append(correction);
      const saveCorrection = add("button", "Save correction", panel, "quiet"); saveCorrection.type = "button";
      saveCorrection.disabled = true; correction.oninput = () => { saveCorrection.disabled = !correction.value.trim() || busy; };
      saveCorrection.onclick = async () => {
        if (busy) return;
        busy = true; refreshReady(); saveCorrection.disabled = true;
        try {
          const fresh = await request(`/api/sessions/${current.id}`);
          current = await request(`/api/sessions/${fresh.id}`, {method:"PUT", body:JSON.stringify({answers:{...(fresh.answers || {}), teaching_correction:correction.value.trim()}})});
          renderReview(await request(`/api/sessions/${current.id}/teaching-review`));
          add("p", "Correction saved in this task. It was not sent to an assistant; the prior review may now be stale.", panel, "task-status");
        } catch (error) { say(`Could not save the correction. ${error.message}`); saveCorrection.disabled = false; }
        finally { busy = false; refreshReady(); }
      };
    }
    if (status === "ready" && !readOnly) {
      const approve = add("button", "Approve this understanding", panel, "primary"); approve.type = "button";
      approve.onclick = async () => {
        if (busy) return;
        busy = true; refreshReady(); approve.disabled = true;
        try {
          renderReview(await request(`/api/sessions/${current.id}/teaching-review/approve`, {method:"POST", body:JSON.stringify({proposal_id:data.proposal.id, consent:true})}));
        } catch (error) { say(`Could not approve the interpretation. ${error.message}`); approve.disabled = false; }
        finally { busy = false; refreshReady(); }
      };
    }
    if (status === "approved") add("p", "Nothing has been executed.", panel);
    if (readOnly) add("p", "This tested version is read-only. You can view its saved understanding; edit the task to create a new training version.", panel, "task-status");
    title.focus();
    say("Review updated.");
  }
  document.addEventListener("hmb-new-directed", () => {
    current = null; trainingTask = null; completeMedia = false; failedBlob = null; readOnly = false; historicalView = false;
    $("directedGoal").value = ""; $("directedDone").value = ""; $("directedComplete").checked = false;
    $("directedVideo").removeAttribute("src"); $("directedVideo").hidden = true;
    $("directedRetryUpload").hidden = true; $("directedReviewPanel").replaceChildren(); $("directedReviewPanel").hidden = true;
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
      // A return from the review panel may emit this event without detail. Any
      // read-only session must remain GET-only, including that path.
      const task = (event.detail?.historical || readOnly) ? current : await ensureSession();
      $("directedComplete").checked = false; completeMedia = false;
      $("directedVideo").removeAttribute("src"); $("directedVideo").hidden = true;
      if (task.media_url) {
        const video = $("directedVideo"); video.src = `${task.media_url}?t=${Date.now()}`; video.hidden = false;
        try { await waitForPlayable(video); completeMedia = true; say("Saved video loaded. Review it and confirm it shows one complete example."); }
        catch (error) { completeMedia = false; say(`Saved video could not be played. ${error.message}`); }
      } else say("Record or import one complete example.");
      showStage("record"); $("directedRecordTitle").focus();
      if (readOnly) say(`${historicalView ? "Historical" : "Last tested"} version is read-only. You can review its saved video; return to current task details to edit or create a new training version.`);
    } catch (error) { say(`Could not open this version. ${error.message}`); document.dispatchEvent(new CustomEvent("hmb-training-back-to-details")); }
    finally { busy = false; refreshReady(); }
  });
  $("directedEditDetails").onclick = () => { if (!busy && !recording) document.dispatchEvent(new CustomEvent("hmb-training-back-to-details")); };
  document.addEventListener("hmb-training-review", () => { showStage("review"); });

  function renderRecipeCard(card) {
    const panel = $("recipeCardPanel");
    if (!panel || !card) return;
    panel.replaceChildren();
    add("p", "3-LINE RECIPE CARD", panel, "eyebrow");
    add("h3", card.title || "Workflow Recipe", panel);
    const dl = document.createElement("dl");
    dl.className = "receipt-fields";
    add("dt", "When you give me", dl);
    add("dd", Array.isArray(card.when_you_give_me) ? card.when_you_give_me.join("; ") : String(card.when_you_give_me || ""), dl);
    add("dt", "I will do", dl);
    add("dd", Array.isArray(card.i_will_do) ? card.i_will_do.join(" → ") : String(card.i_will_do || ""), dl);
    add("dt", "You will get", dl);
    add("dd", String(card.you_will_get || ""), dl);
    panel.append(dl);
    panel.hidden = false;
  }

  async function refreshRecipeCard() {
    const tid = trainingTask?.id || current?.id;
    if (!tid || !$("recipeCardPanel")) return;
    try {
      const card = await request(`/api/tasks/${encodeURIComponent(tid)}/recipe-card`);
      renderRecipeCard(card);
    } catch {
      /* ignore for sessions without recipe card */
    }
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
        current = qr.session;
        trainingTask = qr.task;
        readOnly = false;
        historicalView = false;
        completeMedia = false;
        $("directedGoal").value = "";
        $("directedDone").value = "";
        $("directedComplete").checked = false;
        $("directedVideo").removeAttribute("src");
        $("directedVideo").hidden = true;
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
      } finally {
        busy = false;
        refreshReady();
      }
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
          method: "PUT",
          body: JSON.stringify({task_name: newName}),
        });
        if (trainingTask) trainingTask.name = res.task_name;
        if (current?.answers) current.answers.teaching_task_name = res.task_name;
        showStage("record");
        renderRecipeCard(res.recipe_card);
        say(`Renamed workflow to ${res.task_name}.`);
      } catch (error) {
        say(`Could not rename workflow. ${error.message}`);
      } finally {
        busy = false;
        refreshReady();
      }
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
          method: "POST",
          body: JSON.stringify({dry_run: true}),
        });
        const out = $("sandboxDiffOutput");
        if (out) {
          out.replaceChildren();
          const diff = res.before_after_diff || {};
          const filesAfter = (diff.files_after || []).join(", ");
          add(
            "p",
            `Sandbox Dry-Run ${res.status === "verified" ? "Verified" : "Needs Agent Assist"} (real files untouched). Files after: ${filesAfter}`,
            out
          );
          out.hidden = false;
        }
        await refreshRecipeCard();
      } catch (error) {
        say(`Sandbox dry-run failed. ${error.message}`);
      } finally {
        busy = false;
        $("sandboxDryRunBtn").disabled = false;
        refreshReady();
      }
    };
  }


  // -------------------------------------------------------------------------
  // 1-Button Record -> 1-Button Stop -> Instant AI Auto-Review + Multiple Choice
  // -------------------------------------------------------------------------
  let ocRecorder = null;
  let ocStream = null;
  let ocChunks = [];
  let ocTimerInterval = null;
  let ocStartTime = 0;
  let ocSession = null;
  let ocNativeSessionId = null;
  let ocWindowTitle = "";

  function ocStatus(msg) {
    if ($("oneClickStatus")) $("oneClickStatus").textContent = msg;
  }

  function stopOcStream() {
    if (ocTimerInterval) { clearInterval(ocTimerInterval); ocTimerInterval = null; }
    if (ocStream) { ocStream.getTracks().forEach(t => t.stop()); ocStream = null; }
  }

  if ($("mcModalClose")) {
    $("mcModalClose").onclick = () => {
      if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
    };
  }

  // Option A wizard: Name it -> Quick questions (max 3) -> Done (say-this + try it)
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
    const badge = text => { if ($("mcStepBadge")) $("mcStepBadge").textContent = text; };
    const state = {
      app: reviewData.detected_app || reviewData.app_name || "",
      task: (reviewData.task_options || reviewData.suggested_names || [])[0] || reviewData.task_name || "",
      taskId: reviewData.task_id,
      choices: {},
    };
    const rawQuestions = reviewData.adaptive_questions || reviewData.multiple_choice_questions || [];
    let questions = rawQuestions.slice(0, 3);
    for (const q of questions) state.choices[q.id] = q.selected || q.options?.[0]?.id || "";

    function chipRow(options, current, onPick) {
      const row = document.createElement("div");
      row.className = "mc-pill-row";
      const pills = [];
      for (const value of options) {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "mc-name-pill" + (value === current ? " selected" : "");
        pill.textContent = value;
        pill.onclick = () => { for (const other of pills) other.classList.toggle("selected", other === pill); onPick(value); };
        pills.push(pill);
        row.append(pill);
      }
      row.sync = value => { for (const pill of pills) pill.classList.toggle("selected", pill.textContent === value); };
      return row;
    }

    // ---------- Page 1: Name it ----------
    function pageName() {
      badge("STEP 1 OF 3 · NAME IT");
      target.replaceChildren();
      const head = add("h2", "What did you just teach me?", target, "hmb-wiz-title");
      head.tabIndex = -1;
      const grid = document.createElement("div");
      grid.className = "mc-top-grid";
      const vid = document.createElement("video");
      vid.controls = true; vid.playsInline = true; vid.preload = "metadata"; vid.muted = true;
      vid.src = `${reviewData.media_url || `/api/sessions/${sessionId}/media`}?t=${Date.now()}`;
      grid.append(vid);
      const fields = document.createElement("div");
      fields.className = "hmb-fields";

      const appLabel = add("label", "App", fields); appLabel.htmlFor = "hmbAppInput";
      const appInput = document.createElement("input");
      appInput.id = "hmbAppInput"; appInput.maxLength = 100; appInput.value = state.app;
      appInput.placeholder = "e.g. GIMP, MS Word";
      fields.append(appInput);
      const appChips = chipRow(reviewData.app_options || [], state.app, value => { appInput.value = value; validate(); });
      fields.append(appChips);

      const taskLabel = add("label", "Task", fields); taskLabel.htmlFor = "hmbTaskInput";
      const taskInput = document.createElement("input");
      taskInput.id = "hmbTaskInput"; taskInput.maxLength = 160; taskInput.value = state.task;
      taskInput.placeholder = "e.g. Resize image to 1080px";
      fields.append(taskInput);
      const taskChips = chipRow(reviewData.task_options || reviewData.suggested_names || [], state.task, value => { taskInput.value = value; validate(); });
      fields.append(taskChips);
      grid.append(fields);
      target.append(grid);

      const next = add("button", "Looks right →", target, "mc-approve-btn");
      next.id = "hmbNameNext"; next.type = "button";
      const note = add("p", "", target, "task-status");
      function validate() {
        appChips.sync(appInput.value.trim()); taskChips.sync(taskInput.value.trim());
        next.disabled = !appInput.value.trim() || !taskInput.value.trim();
      }
      appInput.oninput = validate; taskInput.oninput = validate;
      for (const input of [appInput, taskInput]) input.onkeydown = event => { if (event.key === "Enter" && !next.disabled) next.click(); };
      validate();
      next.onclick = async () => {
        next.disabled = true; next.textContent = "Saving…";
        try {
          const saved = await request(`/api/sessions/${sessionId}/name`, {
            method: "POST",
            body: JSON.stringify({app_name: appInput.value.trim(), task_name: taskInput.value.trim()}),
          });
          state.app = saved.app_name; state.task = saved.task_name; state.taskId = saved.task_id;
          if (saved.questions && saved.questions.length) {
            questions = saved.questions.slice(0, 3);
            for (const q of questions) state.choices[q.id] = q.selected || q.options?.[0]?.id || "";
          }
          pageSmartTuning();
        } catch (err) {
          note.textContent = `Could not save the name: ${err.message}`;
          next.disabled = false; next.textContent = "Looks right →";
        }
      };
      (appInput.value ? taskInput : appInput).focus();
    }

    // ---------- Page 2: Easy Mode by default + Expandable Admin Mode ----------
    function pageSmartTuning() {
      badge("STEP 2 OF 3 · ACTIVATE");
      target.replaceChildren();

      state.choices.q_action = state.choices.q_action || "recorded_flow";
      state.choices.q_input = state.choices.q_input || "same_target";
      state.choices.q_done = state.choices.q_done || "window_minimized";
      state.choices.q_safety = state.choices.q_safety || "sandbox_first";

      let adminMode = localStorage.getItem("hmb_admin_mode") === "true";

      const top = document.createElement("div");
      top.style.marginBottom = "8px";
      const heading = add("h2", "Ready to activate your assistant?", top, "hmb-wiz-title");
      heading.tabIndex = -1;
      add("p", `${state.task} in ${state.app}`, top, "eyebrow");
      target.append(top);

      // Trigger box (displayed in both easy and admin mode)
      const triggerBox = document.createElement("div");
      triggerBox.className = "hmb-say-box";
      triggerBox.style.margin = "6px 0 10px";
      const triggerStrong = document.createElement("strong");
      function updateTrigger() {
        const ask = state.choices.q_input === "ask_each_time";
        triggerStrong.textContent = ask ? `🗣️ “${state.task} for [input] in ${state.app}”` : `🗣️ “${state.task} in ${state.app}”`;
        updatePills();
      }
      triggerBox.append(triggerStrong);
      target.append(triggerBox);

      // Easy Mode Summary Pills
      const pillRow = document.createElement("div");
      pillRow.className = "hmb-easy-summary";
      function updatePills() {
        pillRow.innerHTML = `
          <span class="hmb-easy-pill">⚡ ${state.choices.q_input === "ask_each_time" ? "Ask for Input" : "Exact Replay"}</span>
          <span class="hmb-easy-pill">👁️ ${state.choices.q_done === "verified_output" ? "File Output Checked" : "App Completes"}</span>
          <span class="hmb-easy-pill">🛡️ ${state.choices.q_safety === "pause_immediately" ? "Pause & Ask" : "Safe Sandbox First"}</span>
        `;
      }
      updatePills();
      target.append(pillRow);

      // Admin Mode Options Container (collapsed by default in Easy Mode)
      const adminContainer = document.createElement("div");
      adminContainer.id = "hmbAdminContainer";
      adminContainer.hidden = !adminMode;

      const grid = document.createElement("div");
      grid.className = "hmb-tune-grid";

      grid.append(createTuneRow({
        icon: "⚡",
        title: "Input & Target",
        desc: "Does this repeat the exact same actions, or need input each time?",
        options: [
          { id: "same_target", label: "Exact Replay", desc: "Always repeat what was recorded" },
          { id: "ask_each_time", label: "Ask for Input", desc: "Ask for target/parameters before running" },
        ],
        current: state.choices.q_input,
        onSelect: val => { state.choices.q_input = val; updateTrigger(); },
      }));

      grid.append(createTuneRow({
        icon: "👁️",
        title: "Completion Check",
        desc: "How does your assistant confirm the task succeeded?",
        options: [
          { id: "window_minimized", label: "App Completes", desc: "When window closes or action completes" },
          { id: "verified_output", label: "Receipt / File Saved", desc: "When verified output file exists" },
        ],
        current: state.choices.q_done,
        onSelect: val => { state.choices.q_done = val; updateTrigger(); },
      }));

      grid.append(createTuneRow({
        icon: "🛡️",
        title: "Safety & Sandboxing",
        desc: "Protect real system files before execution",
        options: [
          { id: "sandbox_first", label: "Safe Sandbox First", desc: "Simulate and verify before real changes" },
          { id: "pause_immediately", label: "Pause & Ask Me", desc: "Always confirm before running" },
        ],
        current: state.choices.q_safety,
        onSelect: val => { state.choices.q_safety = val; updateTrigger(); },
      }));

      adminContainer.append(grid);
      target.append(adminContainer);

      // Primary Navigation & Action
      const nav = document.createElement("div");
      nav.className = "mc-step-nav";
      nav.style.marginTop = "14px";
      const back = add("button", "← Back to naming", nav, "quiet"); back.type = "button";
      back.onclick = pageName;

      const finishBtn = add("button", "Looks Great — Save & Activate ✨", nav, "primary");
      finishBtn.id = "oneClickApproveBtn"; finishBtn.type = "button";
      finishBtn.style.padding = "10px 22px";
      finishBtn.style.fontSize = "15px";
      finishBtn.onclick = finish;
      target.append(nav);

      // Toggle for Admin Mode
      const toggleWrap = document.createElement("div");
      toggleWrap.style.textAlign = "center";
      toggleWrap.style.marginTop = "10px";
      const toggleBtn = add("button", adminMode ? "▲ Hide Admin Options (Easy Mode)" : "⚙️ Admin Mode (Customize behavior & safety) ▼", toggleWrap, "hmb-admin-toggle");
      toggleBtn.type = "button";
      toggleBtn.onclick = () => {
        adminMode = !adminMode;
        localStorage.setItem("hmb_admin_mode", adminMode ? "true" : "false");
        adminContainer.hidden = !adminMode;
        toggleBtn.textContent = adminMode ? "▲ Hide Admin Options (Easy Mode)" : "⚙️ Admin Mode (Customize behavior & safety) ▼";
      };
      target.append(toggleWrap);

      heading.focus();
    }

    function createTuneRow({icon, title, desc, options, current, onSelect}) {
      const row = document.createElement("div");
      row.className = "hmb-tune-row";
      const hdr = document.createElement("div");
      hdr.className = "hmb-tune-header";
      hdr.innerHTML = `<span class="hmb-tune-icon">${icon}</span><div><strong>${title}</strong><small>${desc}</small></div>`;
      row.append(hdr);

      const pills = document.createElement("div");
      pills.className = "hmb-tune-pills";
      const btns = [];
      for (const opt of options) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "hmb-tune-pill" + (opt.id === current ? " selected" : "");
        btn.innerHTML = `<span class="pill-title">${opt.label}</span><span class="pill-desc">${opt.desc}</span>`;
        btn.onclick = () => {
          btns.forEach(b => b.classList.remove("selected"));
          btn.classList.add("selected");
          onSelect(opt.id);
        };
        btns.push(btn);
        pills.append(btn);
      }
      row.append(pills);
      return row;
    }

    // ---------- Page 3: Done — what to say + try it ----------
    // ---------- Page 3: Done — Human & Intuitive Celebration ----------
    async function finish() {
      badge("STEP 3 OF 3 · COMPLETE");
      target.replaceChildren();
      add("h2", "Teaching your assistant…", target, "hmb-wiz-title");
      let res;
      try {
        res = await request(`/api/sessions/${sessionId}/answer-choices`, {
          method: "POST",
          body: JSON.stringify({selected_name: state.task, choices: state.choices, run_sandbox: true}),
        });
      } catch (err) {
        target.replaceChildren();
        add("h2", "Could not save workflow", target, "hmb-wiz-title");
        add("p", err.message, target, "task-status");
        const retry = add("button", "Try again", target, "mc-approve-btn"); retry.type = "button"; retry.onclick = finish;
        return;
      }
      state.taskId = res.task_id || state.taskId;
      target.replaceChildren();

      // Clean, human task and app names (strip any accidental trailing '#2')
      const cleanTask = (res.task_name || state.task).replace(/\s*#\d+\b/g, "").trim();
      const cleanApp = (res.app_name || state.app || "the app").trim();

      // 1. Warm Header
      const headBox = document.createElement("div");
      headBox.style.marginBottom = "14px";
      const title = add("h2", `🎉 Skill Learned: ${cleanTask}`, headBox, "hmb-wiz-title");
      title.tabIndex = -1;
      add("p", `Taught in ${cleanApp} · Your AI assistants can now run this for you.`, headBox, "eyebrow");
      target.append(headBox);

      // 2. Natural Voice / Chat Speech Bubble
      const speechCard = document.createElement("div");
      speechCard.className = "hmb-speech-bubble";
      speechCard.id = "oneClickResultBox";

      const speechContent = document.createElement("div");
      speechContent.innerHTML = `
        <span style="font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:#4a6828; font-weight:700; display:block; margin-bottom:4px;">🗣️ How to talk to your assistant</span>
        <strong>“${res.say_this}”</strong>
      `;
      speechCard.append(speechContent);

      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "quiet";
      copyBtn.style.padding = "8px 14px";
      copyBtn.style.fontSize = "13px";
      copyBtn.style.fontWeight = "700";
      copyBtn.textContent = "📋 Copy Phrase";
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(res.say_this);
          copyBtn.textContent = "Copied ✓";
          setTimeout(() => { copyBtn.textContent = "📋 Copy Phrase"; }, 2500);
        } catch {
          copyBtn.textContent = "Select & copy";
        }
      };
      speechCard.append(copyBtn);
      target.append(speechCard);

      // 3. Clear Test Drive Simulation Card
      const simCard = document.createElement("div");
      simCard.className = "hmb-done-card";

      const simHdr = document.createElement("div");
      simHdr.innerHTML = `
        <h3>🧪 Test Drive Simulation</h3>
        <small style="color:var(--muted); font-size:12px; display:block; margin-top:2px;">
          Test how your assistant runs this task safely before using it live:
        </small>
      `;
      simCard.append(simHdr);

      const simRow = document.createElement("div");
      simRow.className = "hmb-try-row";
      simRow.style.marginTop = "10px";

      let tryInput = null;
      if (res.try_param) {
        tryInput = document.createElement("input");
        tryInput.id = "hmbTryInput";
        tryInput.value = res.try_param.default ?? "yahoo.com";
        tryInput.placeholder = res.try_param.label || "Target or parameter (e.g. yahoo.com)";
        tryInput.setAttribute("aria-label", res.try_param.label || "Target");
        simRow.append(tryInput);
      }

      const simBtn = add("button", "▶ Run Test Simulation", simRow, "primary");
      simBtn.id = "hmbTryBtn"; simBtn.type = "button";
      simBtn.style.padding = "8px 18px";
      simBtn.style.whiteSpace = "nowrap";
      simCard.append(simRow);

      const simReceipt = document.createElement("div");
      simReceipt.id = "hmbTryResult";
      simReceipt.className = "hmb-receipt-box";
      simReceipt.style.display = "none";
      simCard.append(simReceipt);

      simBtn.onclick = async () => {
        simBtn.disabled = true;
        simBtn.textContent = "Simulating…";
        simReceipt.style.display = "block";
        simReceipt.innerHTML = `<span style="color:#777;">⏳ Running isolated sandbox simulation…</span>`;
        try {
          const parameters = res.try_param && tryInput ? {[res.try_param.name]: tryInput.value.trim()} : {};
          const run = await request(`/api/tasks/${encodeURIComponent(state.taskId)}/hybrid-run`, {
            method: "POST", body: JSON.stringify({dry_run: true, parameters}),
          });
          if (run.status === "verified") {
            const stepsCount = (run.steps || []).length || 1;
            const targetVal = tryInput ? tryInput.value.trim() : cleanTask;
            simReceipt.innerHTML = `
              <div style="color:#2d6914; font-weight:700; margin-bottom:4px;">✔ Test Simulation Passed (${stepsCount} step${stepsCount === 1 ? "" : "s"} verified)</div>
              <div style="font-size:11px; color:#555;">Target: <strong>${targetVal}</strong></div>
              <div style="font-size:11px; color:#555;">Sandbox: Real files and desktop untouched. Safe for live use.</div>
            `;
          } else {
            simReceipt.innerHTML = `
              <div style="color:#b25900; font-weight:700;">⚠️ Needs Attention</div>
              <div style="font-size:11px; color:#555;">${run.diagnostic_snapshot?.observed_state || "Action completed with warnings"}.</div>
            `;
          }
        } catch (err) {
          simReceipt.innerHTML = `<span style="color:#a1261d;">❌ Test failed: ${err.message}</span>`;
        } finally {
          simBtn.disabled = false;
          simBtn.textContent = "▶ Run Test Simulation";
        }
      };

      target.append(simCard);

      // 4. Human Action Buttons
      const actions = document.createElement("div");
      actions.className = "hmb-done-actions";

      const anotherBtn = add("button", "+ Teach Another Task", actions, "quiet");
      anotherBtn.type = "button";
      anotherBtn.onclick = () => {
        if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
        container.hidden = true;
        $("oneClickRecordBtn")?.focus();
      };

      const allDoneBtn = add("button", "All Done ✓", actions, "primary");
      allDoneBtn.type = "button";
      allDoneBtn.style.padding = "10px 28px";
      allDoneBtn.style.fontSize = "15px";
      allDoneBtn.onclick = () => {
        if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
        container.hidden = true;
      };

      target.append(actions);

      ocStatus(`Learned “${cleanTask}”. Say: “${res.say_this}”.`);
      title.focus();
    }

    pageName();
  }

  async function processOneClickBlob(blob, windowTitle, durationSec) {
    ocStatus("Saving recording & opening AI Review popup…");
    try {
      if (!ocSession) {
        const qr = await request("/api/quick-record", {
          method: "POST",
          body: JSON.stringify({window_title: windowTitle || undefined}),
        });
        ocSession = qr.session;
      }
      const cleanMime = (blob.type || "video/webm").split(";")[0];
      await request(`/api/sessions/${ocSession.id}/media`, {
        method: "POST",
        headers: {"Content-Type": cleanMime},
        body: blob,
      });
      const reviewData = await request(`/api/sessions/${ocSession.id}/auto-review`, {
        method: "POST",
        body: JSON.stringify({
          window_title: windowTitle || undefined,
          duration_seconds: durationSec || 2.0,
        }),
      });
      ocStatus("AI review ready.");
      if ($("oneClickReviewCard")) {
        renderMultipleChoiceUI($("oneClickReviewCard"), ocSession.id, reviewData);
      }
    } catch (err) {
      ocStatus(`Auto-review failed: ${err.message}`);
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
        // 1. Try 1-Click Native Desktop Capture first (bypasses Chrome Share Screen popup completely!)
        const nativeRes = await request("/api/native-record/start", {method: "POST", body: JSON.stringify({})});
        if (nativeRes && nativeRes.supported && nativeRes.session_id) {
          ocNativeSessionId = nativeRes.session_id;
          startTimerTick();
          $("oneClickRecordBtn").hidden = true;
          $("oneClickStopBtn").hidden = false;
          ocStatus("Recording your desktop now (no browser popup needed) — click Stop Recording when done.");
          return;
        }
      } catch {
        /* Fall back to browser capture or instant review */
      }

      // 2. Fallback if native display is not present
      try {
        if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) {
          throw new Error("No local display");
        }
        ocStream = await navigator.mediaDevices.getDisplayMedia({video: true, audio: false});
        const vTrack = ocStream.getVideoTracks()[0];
        ocWindowTitle = vTrack?.label || "";
        const qr = await request("/api/quick-record", {
          method: "POST",
          body: JSON.stringify({window_title: ocWindowTitle || undefined}),
        });
        ocSession = qr.session;
        ocChunks = [];
        const mime = ["video/webm;codecs=vp8", "video/webm"].find(t => MediaRecorder.isTypeSupported(t));
        ocRecorder = new MediaRecorder(ocStream, mime ? {mimeType: mime} : {});
        ocRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) ocChunks.push(e.data); };
        startTimerTick();
        if (vTrack) {
          vTrack.onended = () => { if (ocRecorder?.state === "recording") ocRecorder.stop(); };
        }
        ocRecorder.onstop = async () => {
          const elapsed = Math.max(1, (Date.now() - ocStartTime) / 1000);
          stopOcStream();
          $("oneClickRecordBtn").hidden = false;
          $("oneClickStopBtn").hidden = true;
          const blob = new Blob(ocChunks, {type: ocRecorder?.mimeType || "video/webm"});
          if (blob.size > 0) {
            await processOneClickBlob(blob, ocWindowTitle, elapsed);
          }
        };
        ocRecorder.start();
        $("oneClickRecordBtn").hidden = true;
        $("oneClickStopBtn").hidden = false;
        ocStatus("Recording live — perform your task, then click Stop Recording.");
      } catch {
        stopOcStream();
        $("oneClickRecordBtn").hidden = false;
        $("oneClickStopBtn").hidden = true;
        const qr = await request("/api/quick-record", {method: "POST", body: JSON.stringify({})});
        ocSession = qr.session;
        const reviewData = await request(`/api/sessions/${ocSession.id}/auto-review`, {
          method: "POST",
          body: JSON.stringify({duration_seconds: 2.5}),
        });
        if ($("oneClickReviewCard")) {
          renderMultipleChoiceUI($("oneClickReviewCard"), ocSession.id, reviewData);
        }
      }
    };
  }

  if ($("oneClickStopBtn")) {
    $("oneClickStopBtn").onclick = async () => {
      if (ocNativeSessionId) {
        const sid = ocNativeSessionId;
        ocNativeSessionId = null;
        stopOcStream();
        $("oneClickRecordBtn").hidden = false;
        $("oneClickStopBtn").hidden = true;
        ocStatus("Stopping recording & opening AI Review popup…");
        try {
          const reviewData = await request(`/api/native-record/${sid}/stop`, {
            method: "POST",
            body: JSON.stringify({}),
          });
          ocStatus("AI review ready.");
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
