const style = document.createElement("style");
style.textContent = `
  :root{font-family:system-ui,"Noto Sans JP",sans-serif;color:#18392f;background:#f4f5f0}
  *{box-sizing:border-box}body{margin:0;padding:28px}main{max-width:880px;margin:auto}
  h1{font-size:26px;margin:4px 0 8px}h2{font-size:18px;margin:0 0 12px}p{line-height:1.75}
  .lead{color:#55655e}.card{background:white;border:1px solid #d9e1da;border-radius:14px;padding:22px;margin:18px 0}
  .source{overflow-wrap:anywhere;white-space:pre-wrap;line-height:1.8;color:#394c43;font-size:14px}
  button{border:0;border-radius:9px;padding:12px 18px;background:#254e3b;color:white;font:inherit;cursor:pointer}
  button:disabled{opacity:.45;cursor:default}.secondary{background:#e5ebe3;color:#254e3b;margin-left:10px}
  .status{font-size:14px;color:#566a5d;margin:14px 0}.error{color:#9b382c}
  main{min-width:0;overflow-wrap:anywhere}.actions{display:flex;flex-wrap:wrap;gap:10px}.actions .secondary{margin-left:0}
  @media(max-width:480px){body{padding:16px}.card{padding:16px}button{max-width:100%}}
  textarea{display:block;width:100%;min-height:72px;font:inherit;line-height:1.6;padding:10px;border:1px solid #bdcbbf;border-radius:6px;resize:vertical}
  label{display:block;margin:14px 0 6px}.project-item{margin:8px 0}.project-item button{padding:5px 10px;margin-top:4px}.project-add{padding:6px 12px}
  li{line-height:1.75;margin:6px 0}.note{font-size:13px;color:#617069}section+section{margin-top:24px}
`;
document.head.appendChild(style);
document.body.innerHTML = `<main><h1>Kotodama 要件整理</h1>
  <p class="lead">依頼を整理して、次に進める要件案を作ります。</p>
  <div class="card"><h2>今回の依頼</h2><div id="source" class="source">確認しています…</div></div>
  <div class="actions"><button id="run" disabled>Codexで要件案を作る</button><button id="reload" class="secondary">再確認</button></div>
  <p id="status" class="status" role="status">接続と閲覧権限を確認しています。</p>
  <div id="result" class="card" hidden></div>
  <div class="card" id="project-card"><h2>Projectの要件</h2>
    <p id="project-status" class="status" role="status">Projectの接続を確認しています。</p>
    <p id="project-name"></p><div id="project-tasks"></div><div id="project-editor"></div>
    <label id="project-reason-label" hidden>変更の理由<textarea id="project-reason"></textarea></label>
    <div class="actions"><button id="project-inspect" disabled>変更内容を検査</button><button id="project-reload" class="secondary">Projectを再確認</button></div>
    <p class="note">記録がない項目は、確認済みという意味ではありません。検査は保存や実行を行いません。再確認すると編集内容を現在の要件で置き換えます。</p>
    <div id="project-inspection" hidden></div></div>
  <p class="note">表示するのは要件の候補です。公開、他サービスへの投稿、既存タスクの完了変更は行いません。</p></main>`;
const source = document.getElementById("source");
const result = document.getElementById("result");
const status = document.getElementById("status");
const run = document.getElementById("run");
let timer;
let reading = false;
let generation = 0;
let submitting = false;
const labels = {
  not_connected: "ConnectionsからKotodamaの接続を設定してください。",
  ready_to_request: "依頼を確認できました。要件案の作成を開始できます。",
  awaiting_approval: "OSの操作確認を待っています。確認欄から操作を許可してください。",
  approval_unknown: "承認要求の受信を確認できません。OSの確認欄と接続を確認してください。自動で再送はしていません。",
  rejected: "操作は拒否されました。Codexでの実行は開始していません。",
  running: "Codexで要件案を作成しています。",
  ready: "要件案ができました。内容を確認してください。",
  failed: "今回は要件案を作成できませんでした。自動で再実行はしていません。",
  interrupted: "処理が中断されました。実行記録を確認してから再開してください。",
};
function section(title, value) {
  const container = document.createElement("section"); const heading = document.createElement("h2");
  heading.textContent = title; container.appendChild(heading);
  if (Array.isArray(value)) {
    const list = document.createElement("ul");
    for (const text of value) { const item = document.createElement("li"); item.textContent = text; list.appendChild(item); }
    if (!value.length) { const note = document.createElement("p"); note.textContent = `${title}はこの候補に記載されていません。確認済みという意味ではありません。`; container.appendChild(note); }
    else container.appendChild(list);
  } else { const text = document.createElement("p"); text.textContent = value; container.appendChild(text); }
  result.appendChild(container);
}
function render(state) {
  source.textContent = state.source?.overview ?? "まだ依頼を取得できません。";
  status.textContent = labels[state.state] ?? "状態を確認してください。"; status.classList.remove("error");
  run.disabled = submitting || state.state !== "ready_to_request";
  result.replaceChildren(); result.hidden = state.state !== "ready" || !state.result;
  if (!result.hidden) {
    section("目的", state.result.objective); section("成果物", state.result.deliverable);
    section("守る条件", state.result.constraints); section("確認すること", state.result.acceptance_criteria);
    section("未確定のこと", state.result.open_questions);
  }
  clearTimeout(timer);
  if (["running", "awaiting_approval", "approval_unknown"].includes(state.state)) timer = setTimeout(() => refresh(), 2500);
}
function showError() {
  clearTimeout(timer); source.textContent = "現在、この依頼を表示できません。";
  result.replaceChildren(); result.hidden = true; run.disabled = true;
  status.textContent = "権限・期限・接続を確認してください。過去の結果は再表示していません。"; status.classList.add("error");
}
// A newer read or a mutation invalidates older responses, including errors.
// A manual refresh may replace a hung read; polling never creates overlapping reads.
async function refresh(force = false) {
  if (submitting || (reading && !force)) return;
  const current = ++generation;
  clearTimeout(timer); reading = true;
  // Old data is not actionable while identity/freshness is being rechecked.
  run.disabled = true;
  status.textContent = "接続と閲覧権限を再確認しています。";
  try {
    const state = await gadget.getState();
    if (current === generation) render(state);
  } catch {
    if (current === generation) showError();
  } finally {
    if (current === generation) reading = false;
  }
}
run.addEventListener("click", async () => {
  if (submitting || run.disabled) return;
  const current = ++generation;
  clearTimeout(timer); reading = false; submitting = true;
  run.disabled = true; status.textContent = "依頼を送っています…";
  let succeeded = false;
  try {
    const state = await gadget.requestBrief();
    if (current === generation) { render(state); succeeded = true; }
  } catch {
    if (current === generation) showError();
  } finally {
    submitting = false;
    // A failed dispatch is not silently retried or replaced with old state.
    // An explicit read can recover without creating another request.
    if (succeeded) await refresh(true);
  }
});
document.getElementById("reload").addEventListener("click", () => refresh(true));
refresh();

// Project operations use the same native connection and its existing owner.
const projectStatus = document.getElementById("project-status");
const projectEditor = document.getElementById("project-editor");
const projectName = document.getElementById("project-name");
const projectTasks = document.getElementById("project-tasks");
const projectInspect = document.getElementById("project-inspect");
const projectReason = document.getElementById("project-reason");
const projectResult = document.getElementById("project-inspection");
const projectLabels = { outcome: "欲しい成果", in_scope: "含めること", out_of_scope: "含めないこと", constraints: "守る条件", acceptance: "受入条件", unknowns: "未確定のこと" };
let projectSnapshot, projectGeneration = 0, inspectingProject = false;
function renderTaskRefs(container, refs, title) {
  container.replaceChildren();
  const heading = document.createElement("h2"); heading.textContent = title; container.append(heading);
  const note = document.createElement("p"); note.className = "note";
  note.textContent = refs.length ? "記録された参照です。Taskの現在の状態や完了を確認した表示ではありません。" : "関連付けた参照は記録されていません。";
  container.append(note);
  for (const ref of refs) {
    const row = document.createElement("details"); const summary = document.createElement("summary");
    const kind = ref.adapter === "discord_local_task_v1" ? "Task" : ref.adapter === "swarm_execution_v1" ? "swarmへの実行入力" : "実行入力（旧形式）";
    summary.textContent = `${kind} · ${ref.task_id} · 第${ref.revision}版`; row.append(summary);
    if (ref.adapter !== "discord_local_task_v1") {
      const owner = document.createElement("p"); owner.textContent = `実行元の参照: ${ref.owner_ref}`;
      const digest = document.createElement("p"); digest.textContent = `入力の照合値: ${ref.context_digest}`; row.append(owner, digest);
    }
    container.append(row);
  }
}
function clearInspection() {
  projectResult.replaceChildren(); projectResult.hidden = true;
  if (projectSnapshot) projectStatus.textContent = "編集内容はまだ検査していません。";
}
function projectEditable(enabled) {
  for (const input of projectEditor.querySelectorAll("textarea,button")) input.disabled = !enabled;
  projectReason.disabled = !enabled; projectInspect.disabled = !enabled;
}
function clearProject(message) {
  projectSnapshot = null; projectName.textContent = ""; projectTasks.replaceChildren(); projectEditor.replaceChildren();
  projectReason.value = ""; document.getElementById("project-reason-label").hidden = true;
  clearInspection(); projectEditable(false); projectStatus.textContent = message;
}
function addProjectItem(container, value = "") {
  const row = document.createElement("div"); row.className = "project-item";
  const input = document.createElement("textarea"); input.value = value; input.setAttribute("aria-label", projectLabels[container.dataset.field] + "の項目");
  const remove = document.createElement("button"); remove.textContent = "この項目を削除"; remove.className = "secondary";
  remove.addEventListener("click", () => { row.remove(); clearInspection(); });
  row.append(input, remove); container.append(row);
}
function renderProject(value) {
  if (value.state !== "connected") { clearProject("この接続にはProjectが設定されていません。"); return; }
  projectSnapshot = value; projectEditor.replaceChildren(); clearInspection();
  const project = value.view.project;
  projectName.textContent = `${project.name} · 第${project.revision}版`;
  renderTaskRefs(projectTasks, project.task_refs, "関連するTaskの参照");
  for (const [key, title] of Object.entries(projectLabels)) {
    const group = document.createElement("section"); const label = document.createElement("label"); label.textContent = title;
    const values = document.createElement("div"); values.dataset.field = key; group.append(label, values);
    if (key === "outcome") { const input = document.createElement("textarea"); input.value = project.brief[key]; input.setAttribute("aria-label", title); values.append(input); }
    else {
      for (const item of project.brief[key]) addProjectItem(values, item);
      const add = document.createElement("button"); add.textContent = "項目を追加"; add.className = "secondary project-add";
      add.addEventListener("click", () => { if (values.children.length < 20) { addProjectItem(values); clearInspection(); } });
      group.append(add);
    }
    projectEditor.append(group);
  }
  projectReason.value = ""; document.getElementById("project-reason-label").hidden = !value.can_inspect;
  projectStatus.textContent = value.can_inspect ? "現在の要件です。編集して、条件の削除と影響を確認できます。" : "現在の要件です。この接続では閲覧できます。";
  projectEditable(value.can_inspect);
}
async function refreshProject() {
  if (inspectingProject) return;
  const generation = ++projectGeneration;
  clearProject("Projectの権限と現在の要件を確認しています。");
  if (typeof gadget.getProject !== "function") { clearProject("この接続にはProjectが設定されていません。"); return; }
  try { const value = await gadget.getProject(); if (generation === projectGeneration) renderProject(value); }
  catch { if (generation === projectGeneration) clearProject("Projectを表示できません。権限・期限・接続を確認してください。"); }
}
projectEditor.addEventListener("input", clearInspection);
projectReason.addEventListener("input", clearInspection);
projectInspect.addEventListener("click", async () => {
  if (!projectSnapshot || inspectingProject || projectInspect.disabled) return;
  const current = projectSnapshot;
  const brief = {};
  for (const key of Object.keys(projectLabels)) {
    const values = [...projectEditor.querySelector(`[data-field="${key}"]`).querySelectorAll("textarea")].map(input => input.value);
    brief[key] = key === "outcome" ? values[0] : values;
  }
  const whitespace = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u;
  const validText = (value, max) => value.isWellFormed() && !value.includes("\0") && !whitespace.test(value) && [...value].length <= max;
  if (!validText(projectReason.value, 1000) || !validText(brief.outcome, 4000)
    || Object.keys(projectLabels).slice(1).some(key => new Set(brief[key]).size !== brief[key].length || brief[key].some(value => !validText(value, 1000)))) {
    clearInspection(); projectStatus.textContent = "理由・成果と各項目を入力してください。成果は4,000文字、理由と各項目は1,000文字までです。同じ項目は重複させず、空の項目は削除してください。"; return;
  }
  if (Object.keys(projectLabels).every(key => JSON.stringify(brief[key]) === JSON.stringify(current.view.project.brief[key]))) {
    clearInspection(); projectStatus.textContent = "要件の変更がありません。編集内容を変えてから検査してください。"; return;
  }
  const input = { binding_sha256: current.binding_sha256, expected_revision: current.view.project.revision,
    base_digest: current.view.project_digest, reason: projectReason.value, brief };
  if (new TextEncoder().encode(JSON.stringify(input)).length > 190000) {
    clearInspection(); projectStatus.textContent = "この入力は接続の上限を超えています。編集内容は残しています。"; return;
  }
  const generation = ++projectGeneration; inspectingProject = true;
  projectEditable(false); clearInspection(); projectStatus.textContent = "変更候補を検査しています。";
  try {
    const result = await gadget.inspectProjectChange(input);
    if (generation !== projectGeneration) return;
    const candidate = result.inspection;
    const heading = document.createElement("h2"); heading.textContent = "変更候補の検査結果"; projectResult.append(heading);
    const changed = document.createElement("p"); changed.textContent = "変更する項目: " + candidate.changed_fields.map(key => projectLabels[key]).join("、"); projectResult.append(changed);
    for (const key of ["constraints", "acceptance"]) {
      const title = document.createElement("p"); title.textContent = `削除される${projectLabels[key]}: ${candidate.removed_requirements[key].length}件`; projectResult.append(title);
      const list = document.createElement("ul"); for (const value of candidate.removed_requirements[key]) { const item = document.createElement("li"); item.textContent = value; list.append(item); } projectResult.append(list);
    }
    const note = document.createElement("p"); note.textContent = `第${candidate.expected_revision}版に対する検査です。影響するTask参照: ${candidate.impact_task_refs.length}件。変更は保存されていません。意味や条件の妥当性は別途確認が必要です。`; projectResult.append(note);
    const affected = document.createElement("div"); renderTaskRefs(affected, candidate.impact_task_refs, "影響するTaskの参照"); projectResult.append(affected);
    projectResult.hidden = false; projectStatus.textContent = "検査できました。現在の要件は変更していません。"; projectEditable(true);
  } catch { if (generation === projectGeneration) clearProject("変更候補を検査できませんでした。Projectを再確認してください。変更は保存していません。"); }
  finally { inspectingProject = false; }
});
document.getElementById("project-reload").addEventListener("click", refreshProject);
refreshProject();
