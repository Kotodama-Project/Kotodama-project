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
  li{line-height:1.75;margin:6px 0}.note{font-size:13px;color:#617069}section+section{margin-top:24px}
`;
document.head.appendChild(style);
document.body.innerHTML = `<main><h1>Kotodama 要件整理</h1>
  <p class="lead">依頼を整理して、次に進める要件案を作ります。</p>
  <div class="card"><h2>今回の依頼</h2><div id="source" class="source">確認しています…</div></div>
  <div class="actions"><button id="run" disabled>Codexで要件案を作る</button><button id="reload" class="secondary">再確認</button></div>
  <p id="status" class="status" role="status">接続と閲覧権限を確認しています。</p>
  <div id="result" class="card" hidden></div>
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
