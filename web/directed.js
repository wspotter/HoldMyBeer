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
      const mcQuickBox = document.createElement("div");
      panel.append(mcQuickBox);
      if (current?.id) {
        request(`/api/sessions/${current.id}/auto-review`, {method: "POST", body: JSON.stringify({})})
          .then(rev => renderMultipleChoiceUI(mcQuickBox, current.id, rev))
          .catch(() => {});
      }
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

  function renderMultipleChoiceUI(container, sessionId, reviewData) {
    const useModal = Boolean($("mcModalOverlay") && $("mcModalBody") && container?.id === "oneClickReviewCard");
    const target = useModal ? $("mcModalBody") : container;
    if (useModal) {
      $("mcModalOverlay").hidden = false;
      container.hidden = false;
      container.replaceChildren();
      const reopen = add("button", "✨ Open AI Review Popup", container, "quiet");
      reopen.type = "button";
      reopen.onclick = () => { $("mcModalOverlay").hidden = false; };
    } else {
      container.hidden = false;
    }

    target.replaceChildren();
    const heading = add("h2", "Here’s what I saw — tap to confirm", target);
    heading.style.fontSize = "19px";
    heading.style.margin = "0 0 10px";
    heading.tabIndex = -1;

    // Compact Top Grid: Video Preview (left) + Task Name Pills (right)
    const topGrid = document.createElement("div");
    topGrid.className = "mc-top-grid";
    const vidWrap = document.createElement("div");
    const vid = document.createElement("video");
    vid.controls = true;
    vid.playsInline = true;
    vid.preload = "auto";
    const mediaUrl = reviewData.media_url || `/api/sessions/${sessionId}/media`;
    vid.src = `${mediaUrl}?t=${Date.now()}`;
    vidWrap.append(vid);
    topGrid.append(vidWrap);

    let selectedName = reviewData.task_name || (reviewData.suggested_names?.[0]) || "Quick Workflow";
    const rightCol = document.createElement("div");
    add("small", "Task Name (tap pill to switch):", rightCol);
    const pillRow = document.createElement("div");
    pillRow.className = "mc-pill-row";
    pillRow.style.margin = "6px 0 0";
    const namePills = [];
    for (const candidate of (reviewData.suggested_names || [selectedName])) {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "mc-name-pill" + (candidate === selectedName ? " selected" : "");
      pill.textContent = candidate;
      pill.onclick = () => {
        selectedName = candidate;
        for (const p of namePills) p.classList.toggle("selected", p.textContent === selectedName);
      };
      namePills.push(pill);
      pillRow.append(pill);
    }
    rightCol.append(pillRow);
    topGrid.append(rightCol);
    target.append(topGrid);

    // Step-by-Step Single Question Card (1 question visible at a time; auto-advances on tap)
    const questions = reviewData.multiple_choice_questions || [];
    const selectedChoices = {};
    for (const q of questions) {
      selectedChoices[q.id] = q.selected || q.options?.[0]?.id || "";
    }

    let currentStep = 0;
    const stepHolder = document.createElement("div");
    target.append(stepHolder);

    function renderStepQuestion() {
      stepHolder.replaceChildren();
      if (!questions.length) return;
      const q = questions[currentStep];
      if ($("mcStepBadge")) {
        $("mcStepBadge").textContent = `AI AUTO-REVIEW · QUESTION ${currentStep + 1} OF ${questions.length}`;
      }
      const card = document.createElement("div");
      card.className = "mc-question-card";
      card.style.margin = "8px 0";
      add("h3", q.question, card);
      const list = document.createElement("div");
      list.className = "mc-options-list";
      for (const opt of (q.options || [])) {
        const btn = document.createElement("button");
        btn.type = "button";
        const isSel = opt.id === selectedChoices[q.id];
        btn.className = "mc-option-btn" + (isSel ? " selected" : "");
        btn.textContent = `${isSel ? "🔘" : "⚪"} ${opt.label}`;
        btn.onclick = () => {
          selectedChoices[q.id] = opt.id;
          if (currentStep < questions.length - 1) {
            currentStep += 1;
            renderStepQuestion();
          } else {
            renderStepQuestion();
          }
        };
        list.append(btn);
      }
      card.append(list);

      const nav = document.createElement("div");
      nav.className = "mc-step-nav";
      const prevBtn = add("button", "← Previous", nav, "quiet");
      prevBtn.type = "button";
      prevBtn.disabled = currentStep === 0;
      prevBtn.onclick = () => { if (currentStep > 0) { currentStep -= 1; renderStepQuestion(); } };

      const stepInfo = add("small", `Step ${currentStep + 1} of ${questions.length} (tap any option to advance)`, nav);
      stepInfo.style.margin = "0";

      const nextBtn = add("button", currentStep < questions.length - 1 ? "Next →" : "Done", nav, "quiet");
      nextBtn.type = "button";
      nextBtn.disabled = currentStep >= questions.length - 1;
      nextBtn.onclick = () => { if (currentStep < questions.length - 1) { currentStep += 1; renderStepQuestion(); } };
      card.append(nav);
      stepHolder.append(card);
    }

    renderStepQuestion();

    const approveBtn = add("button", "✅ Confirm Answers & Test in Safe Sandbox", target, "mc-approve-btn");
    approveBtn.id = "oneClickApproveBtn";
    approveBtn.type = "button";

    const resultBox = document.createElement("div");
    resultBox.id = "oneClickResultBox";
    resultBox.hidden = true;
    target.append(resultBox);

    approveBtn.onclick = async () => {
      approveBtn.disabled = true;
      approveBtn.textContent = "Running Safe Sandbox Dry-Run…";
      try {
        const res = await request(`/api/sessions/${sessionId}/answer-choices`, {
          method: "POST",
          body: JSON.stringify({
            selected_name: selectedName,
            choices: selectedChoices,
            run_sandbox: true,
          }),
        });
        stepHolder.hidden = true;
        resultBox.replaceChildren();
        resultBox.className = "mc-verified-banner";
        resultBox.hidden = false;
        add("h3", `✅ Approved & Verified in Safe Sandbox: ${res.task_name}`, resultBox);
        if (res.recipe_card) {
          add("p", `When you give me: ${(res.recipe_card.when_you_give_me || []).join("; ")}`, resultBox);
          add("p", `I will do: ${(res.recipe_card.i_will_do || []).join(" → ")}`, resultBox);
          add("p", `You will get: ${res.recipe_card.you_will_get}`, resultBox);
        }
        const filesAfter = res.sandbox_result?.before_after_diff?.files_after || [];
        if (filesAfter.length) {
          add("p", `Sandbox output files verified (real files untouched): ${filesAfter.join(", ")}`, resultBox, "task-status");
        }
        approveBtn.textContent = "✅ Done — Close Popup";
        approveBtn.onclick = () => {
          if ($("mcModalOverlay")) $("mcModalOverlay").hidden = true;
        };
        ocStatus(`Approved "${res.task_name}" and verified in Safe Sandbox!`);
      } catch (err) {
        ocStatus(`Could not confirm choices: ${err.message}`);
      } finally {
        approveBtn.disabled = false;
      }
    };

    heading.focus();
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
