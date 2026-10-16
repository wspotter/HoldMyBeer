/* Read-only GitHub task. Plans and approval remain owned by the server. */
(() => {
  let current = null, sessionId = null, poll = null, busy = false;
  const labels = {awaiting_approval: "Check the steps below. Nothing has run yet.", approved: "Steps approved. Choose Run this task when you’re ready.", running: "Reading GitHub… this may take a few seconds.", verified: "Report saved on this computer.", cancelled: "Task cancelled. You can choose another search.", interrupted: "The app restarted before this task finished. Review any saved details, then try a new search.", needs_teaching: "The page didn’t match the expected layout. The task stopped for review.", failed: "The task could not finish. Try a new search or check the details below."};
  const status = message => { $("briefStatus").textContent = message; };
  function controls() {
    $("briefPrepare").disabled = busy;
    $("briefApprove").disabled = busy || !$("briefConsent").checked;
    $("briefStart").disabled = busy || current?.status !== "approved";
    $("briefStart").hidden = current?.status !== "approved";
    $("briefCancel").disabled = busy || !["awaiting_approval", "approved", "running"].includes(current?.status);
    $("briefCancel").hidden = !["awaiting_approval", "approved", "running"].includes(current?.status);
    if ($("briefChange")) $("briefChange").disabled = busy || current?.status === "running";
  }
  function show(job) {
    const changed = current?.id !== job.id || current?.status !== job.status;
    current = job;
    sessionId = job.plan.session_id;
    $("briefForm").hidden = true;
    $("briefHistory").hidden = false;
    $("briefPlan").hidden = job.status === "verified";
    $("briefApprovalControls").hidden = job.status !== "awaiting_approval";
    $("briefPlanText").textContent = JSON.stringify(job.plan, null, 2);
    const summary = $("briefPlanSummary");
    summary.replaceChildren();
    summary.append(textEl("p", `Read up to ${job.plan.limit} open issues from ${job.plan.repository}${job.plan.keyword ? ` matching “${job.plan.keyword}”` : ""}.`));
    const steps = document.createElement("ol"); steps.className = "plain-steps";
    for (const text of ["Open the project’s public issue list.", "Read the matching titles and links.", "Save a report here for you to review."]) steps.append(textEl("li", text));
    summary.append(steps, textEl("p", "No sign-in. No comments, posts, or changes to the project.", "task-status"));
    status(labels[job.status] || "Task stopped. Review its saved details.");
    const box = $("briefResult"); box.replaceChildren();
    if (job.status === "verified" && job.result) {
      const result = document.createElement("section"); result.className = "task-surface result-surface";
      const issues = job.result.issues || [];
      result.append(textEl("p", "3. YOUR RESULT", "eyebrow"), textEl("h2", `${issues.length} open issue${issues.length === 1 ? "" : "s"} found`));
      if (!issues.length) result.append(textEl("p", "No matches in this search. Try different words or leave the search words blank."));
      const list = document.createElement("ol"); list.className = "issue-list";
      for (const issue of issues) {
        const item = document.createElement("li"), link = textEl("a", `#${issue.number} · ${issue.title}`);
        // Only link the exact public repository's numbered issues.
        const expected = `https://github.com/${job.plan.repository}/issues/${issue.number}`;
        if (issue.url === expected && Number.isInteger(issue.number)) { link.href = expected; link.target = "_blank"; link.rel = "noopener"; }
        item.append(link); list.append(item);
      }
      result.append(list);
      if (job.result.truncated) result.append(textEl("p", "This is a limited list. There may be more matching issues on GitHub.", "task-status"));
      const link = textEl("a", "Download report (JSON)"); link.href = `/api/issue-briefs/${job.id}/report`; result.append(link);
      const details = document.createElement("details"); details.className = "technical-details";
      details.append(textEl("summary", "Reviewed steps and saved details"), textEl("pre", JSON.stringify({plan: job.plan, result: job.result}, null, 2)));
      const another = textEl("button", "Try another search", "primary"); another.type = "button";
      another.onclick = () => $("briefChange").click();
      result.append(details, another);
      box.append(result);
    } else if (job.failure || job.result?.failure) box.append(textEl("p", safeTrialFailure(job.failure || job.result.failure), "task-status"));
    let change = $("briefChange");
    if (!change) {
      change = textEl("button", "Change search", "back-link"); change.id = "briefChange"; change.type = "button";
      $("briefPlan").append(change);
      change.onclick = () => action(async () => {
        if (["awaiting_approval", "approved"].includes(current?.status))
          await api(`/api/issue-briefs/${current.id}/cancel`, {method: "POST", body: "{}"});
        clearTimeout(poll); current = null;
        $("briefPlan").hidden = true; $("briefResult").replaceChildren(); $("briefForm").hidden = false;
        $("briefConsent").checked = false;
        status("Choose your search, then review a fresh plan."); $("briefRepository").focus();
      });
    }
    controls();
    if (changed) {
      const target = job.status === "verified" ? box.querySelector("h2") : job.status === "approved" ? $("briefStart") : $("briefPlan").querySelector("h2");
      if (target) { target.tabIndex = -1; target.focus(); }
    }
    clearTimeout(poll);
    if (job.status === "running") poll = setTimeout(refreshJob, 1000);
  }
  async function refreshJob() {
    if (!current) return;
    const id = current.id;
    try { const job = await api(`/api/issue-briefs/${id}`); if (current?.id === id) show(job); }
    catch (error) { status(`Could not check progress. Open Saved tasks to reload this task. ${error.message}`); }
  }
  async function action(fn) {
    if (busy) return;
    busy = true; controls();
    try { await fn(); }
    catch (error) { status(error.message); }
    finally { busy = false; controls(); }
  }
  $("briefConsent").addEventListener("change", controls);
  $("briefForm").addEventListener("submit", event => {
    event.preventDefault();
    if (!$("briefForm").reportValidity()) return;
    action(async () => {
      status("Preparing the steps… nothing is running yet.");
      const repository = $("briefRepository").value.trim();
      if (!sessionId) {
        const created = await api("/api/sessions", {method: "POST", body: JSON.stringify({title: `GitHub report · ${repository}`})});
        sessionId = created.id;
      }
      await api(`/api/sessions/${sessionId}`, {method: "PUT", body: JSON.stringify({title: `GitHub report · ${repository}`})});
      const job = await api("/api/issue-briefs", {method: "POST", body: JSON.stringify({session_id: sessionId,
        repository, keyword: $("briefKeyword").value.trim(), limit: Number($("briefLimit").value),
      })});
      $("briefConsent").checked = false; show(job);
    });
  });
  $("briefApprove").addEventListener("click", () => action(async () => {
    if (!current || current.status !== "awaiting_approval" || !$("briefConsent").checked) throw Error("Check the plan and give permission first.");
    const auth = await api("/api/issue-briefs/approval-session");
    show(await api(`/api/issue-briefs/${current.id}/approve`, {method: "POST", headers: {"X-HMB-Approval": auth.csrf},
      body: JSON.stringify({plan_hash: current.plan_hash, consent: true})}));
  }));
  $("briefStart").addEventListener("click", () => action(async () => {
    if (current) show(await api(`/api/issue-briefs/${current.id}/start`, {method: "POST", body: "{}"}));
  }));
  $("briefCancel").addEventListener("click", () => action(async () => {
    if (current) show(await api(`/api/issue-briefs/${current.id}/cancel`, {method: "POST", body: "{}"}));
  }));
  async function history(id) {
    clearTimeout(poll); current = null; sessionId = id;
    $("briefPlan").hidden = true; $("briefForm").hidden = true; $("briefHistory").hidden = false;
    const box = $("briefResult"); box.replaceChildren();
    const data = await api(`/api/issue-briefs?session_id=${encodeURIComponent(id)}`);
    if (!data.jobs.length) { $("briefForm").hidden = false; status("No reports saved for this task yet. Choose a search to get started."); return; }
    status("Choose a saved report or unfinished task.");
    for (const job of data.jobs) {
      const button = textEl("button", `${job.plan.repository} · ${job.plan.keyword || "all open issues"} · ${job.status.replaceAll("_", " ")}`, "saved-task");
      button.type = "button";
      button.onclick = () => { $("briefConsent").checked = false; show(job); };
      box.append(button);
    }
  }
  $("briefHistory").onclick = () => action(() => history(sessionId));
  document.addEventListener("hmb-open-brief", event => action(() => history(event.detail)));
})();
