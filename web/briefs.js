/* Named real-site workflow. The server owns approval and job state. */
(() => {
  let current = null;
  let poll = null;
  let busy = false;
  const status = (message) => { $("briefStatus").textContent = message; };
  function checkCurrentSession() {
    if (!session || current?.plan.session_id !== session.id)
      throw Error("Load an issue brief for the selected workflow first.");
    if (dirty || recorder?.state === "recording")
      throw Error("Save your edits and stop recording before approving or running a procedure.");
  }
  document.addEventListener("hmb-session-selected", () => {
    clearTimeout(poll);
    current = null;
    $("briefPlan").hidden = true;
    $("briefStart").disabled = true;
    $("briefCancel").disabled = true;
    $("briefResult").replaceChildren();
    status("Prepare a procedure or load this workflow's issue brief history.");
  });
  function show(job) {
    current = job;
    $("briefPlan").hidden = false;
    $("briefApprovalControls").hidden = job.status !== "awaiting_approval";
    $("briefPlanText").textContent = JSON.stringify(job.plan, null, 2);
    $("briefStart").disabled = job.status !== "approved";
    $("briefCancel").disabled = !["awaiting_approval", "approved", "running"].includes(job.status);
    status(`${job.status}: ${job.id}${job.failure ? " — " + job.failure : ""}`);
    const box = $("briefResult");
    box.replaceChildren();
    if (job.result) {
      const text = document.createElement("pre");
      text.style.whiteSpace = "pre-wrap";
      text.textContent = JSON.stringify(job.result, null, 2);
      box.append(text);
    }
    if (job.status === "verified") {
      const link = document.createElement("a");
      link.href = `/api/issue-briefs/${job.id}/report`;
      link.textContent = "Download retained issue report";
      box.append(link);
    }
    clearTimeout(poll);
    if (job.status === "running") poll = setTimeout(refresh, 1000);
  }
  async function refresh() {
    if (!current) return;
    try { show(await api(`/api/issue-briefs/${current.id}`)); }
    catch (error) { status(`Could not refresh. Reload history before retrying: ${error.message}`); }
  }
  async function action(fn) {
    if (busy) return;
    busy = true;
    try { await fn(); }
    catch (error) { status(error.message); }
    finally { busy = false; }
  }
  $("briefConsent").addEventListener("change", () => {
    $("briefApprove").disabled = !$("briefConsent").checked;
  });
  $("briefPrepare").addEventListener("click", () => action(async () => {
    if (!session) throw Error("Create or select a workflow first.");
    if (dirty || recorder?.state === "recording") throw Error("Save your edits and stop recording before preparing a procedure.");
    const job = await api("/api/issue-briefs", {method: "POST", body: JSON.stringify({
      session_id: session.id, repository: $("briefRepository").value.trim(),
      keyword: $("briefKeyword").value.trim(), limit: Number($("briefLimit").value),
    })});
    $("briefConsent").checked = false;
    $("briefApprove").disabled = true;
    show(job);
  }));
  $("briefApprove").addEventListener("click", () => action(async () => {
    checkCurrentSession();
    if (!current || !$("briefConsent").checked) throw Error("Inspect the exact plan and explicitly approve it.");
    const auth = await api("/api/issue-briefs/approval-session");
    show(await api(`/api/issue-briefs/${current.id}/approve`, {method: "POST",
      headers: {"X-HMB-Approval": auth.csrf}, body: JSON.stringify({plan_hash: current.plan_hash, consent: true})}));
  }));
  $("briefStart").addEventListener("click", () => action(async () => {
    checkCurrentSession();
    if (current) show(await api(`/api/issue-briefs/${current.id}/start`, {method: "POST", body: "{}"}));
  }));
  $("briefCancel").addEventListener("click", () => action(async () => {
    if (current) show(await api(`/api/issue-briefs/${current.id}/cancel`, {method: "POST", body: "{}"}));
  }));
  $("briefHistory").addEventListener("click", () => action(async () => {
    if (!session) throw Error("Select a workflow first.");
    const data = await api(`/api/issue-briefs?session_id=${encodeURIComponent(session.id)}`);
    const box = $("briefResult");
    box.replaceChildren();
    if (!data.jobs.length) { status("No issue briefs are retained for this workflow."); return; }
    clearTimeout(poll);
    $("briefPlan").hidden = true;
    $("briefStart").disabled = true;
    $("briefCancel").disabled = true;
    status("Choose a retained issue brief to inspect its plan and result.");
    for (const job of data.jobs) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${job.status}: ${job.plan.repository} — ${job.plan.keyword || "all open"}`;
      button.addEventListener("click", () => {
        $("briefConsent").checked = false;
        $("briefApprove").disabled = true;
        show(job);
      });
      box.append(button);
    }
  }));
})();
