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
    if (!goal || !done || !current?.id) throw new Error("Choose an app and save a task before recording.");
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

})();
