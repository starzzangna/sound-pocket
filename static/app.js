"use strict";
const $ = (id) => document.getElementById(id);
let csrf = "", timer = null, currentJob = null, networkFailures = 0;
const terminal = new Set(["ready", "error", "cancelled"]);

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...options.headers }, signal: AbortSignal.timeout(15000) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    error.status = response.status;
    throw error;
  }
  return data;
}
function lockForm(busy) { for (const input of $("convert-form").elements) input.disabled = busy; $("convert-button").innerHTML = busy ? '변환하고 있어요…' : 'MP3로 변환하기 <span aria-hidden="true">→</span>'; }
async function boot() {
  $("connection").hidden = false;
  try {
    const data = await api("/api/session"); csrf = data.csrf;
    $("max-minutes").textContent = data.max_minutes;
    $("retention-minutes").textContent = data.retention_minutes;
    $("connection").hidden = true;
    await showWorkspace();
  } catch {
    $("connection").hidden = false;
    $("connection").textContent = "서버를 깨우고 있어요. 무료 서버는 첫 접속에 약 1분이 걸릴 수 있습니다.";
    const retry = document.createElement("button"); retry.className = "text-button"; retry.textContent = "다시 연결"; retry.addEventListener("click", boot); $("connection").append(document.createElement("br"), retry);
  }
}
async function showWorkspace() {
  $("workspace").hidden = false;
  const { job } = await api("/api/jobs");
  if (job) { renderJob(job); if (!terminal.has(job.status)) schedulePoll(); }
  else { $("job-panel").hidden = true; currentJob = null; lockForm(false); }
}
function renderJob(job) {
  currentJob = job; $("job-panel").hidden = false; $("job-panel").dataset.status = job.status;
  const busy = !terminal.has(job.status); lockForm(busy);
  $("job-title").textContent = job.title; $("job-message").textContent = job.message || "";
  $("cancel").hidden = !busy; $("cancel").disabled = false; $("cancel").textContent = "취소";
  $("progress-region").hidden = !busy; $("download").hidden = job.status !== "ready"; $("expiry").hidden = job.status !== "ready";
  const labels = { checking: "영상 확인 중", downloading: "오디오 받는 중", converting: "MP3 변환 중", ready: "변환 완료", error: "변환하지 못했어요", cancelled: "변환 취소" };
  $("job-label").textContent = labels[job.status] || "처리 중";
  $("stage-text").textContent = job.status === "converting" ? "파일을 변환하고 있어요. 이 화면에서 기다려 주세요." : labels[job.status];
  $("progress-text").textContent = job.progress == null ? "" : `${job.progress}%`;
  if (job.progress == null) $("progress").removeAttribute("value"); else $("progress").value = job.progress;
  const step = ["checking", "downloading", "converting"].indexOf(job.status);
  document.querySelectorAll(".stages li").forEach((el, index) => { el.classList.toggle("current", index === step); el.classList.toggle("done", index < step); });
  if (job.status === "ready") {
    $("download").href = `/api/jobs/${job.id}/download`;
    const expires = new Date(job.expires_at * 1000).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
    $("expiry").textContent = `${job.bitrate}kbps · ${(job.size / 1024 / 1024).toFixed(1)}MB · ${expires}까지 다운로드할 수 있어요. 서버 재시작 시 더 일찍 삭제될 수 있습니다.`;
    clearTimeout(timer); timer = setTimeout(() => { $("download").hidden = true; $("expiry").textContent = "파일 보관 시간이 지났습니다. 주소를 입력해 다시 변환해 주세요."; }, Math.max(0, job.expires_at * 1000 - Date.now()));
  }
}
function schedulePoll(delay = 2000) { clearTimeout(timer); timer = setTimeout(poll, delay); }
async function poll() {
  if (!currentJob || terminal.has(currentJob.status)) return;
  try {
    const { job } = await api(`/api/jobs/${currentJob.id}`); networkFailures = 0; renderJob(job);
    if (!terminal.has(job.status)) schedulePoll();
  } catch (error) {
    if (error.status === 404) { renderJob({ ...currentJob, status: "error", message: error.message }); return; }
    networkFailures++; $("job-message").textContent = "연결이 잠시 끊겼습니다. 진행 상태를 다시 확인하고 있어요.";
    schedulePoll(Math.min(15000, 2000 * networkFailures));
  }
}
$("paste").addEventListener("click", async () => {
  try { $("video-url").value = (await navigator.clipboard.readText()).trim(); $("form-error").textContent = ""; }
  catch { $("form-error").textContent = "주소 입력칸에서 직접 붙여넣어 주세요. PC에서는 Ctrl+V를 사용할 수 있어요."; }
  $("video-url").focus();
});
$("convert-form").addEventListener("submit", async (event) => {
  event.preventDefault(); $("form-error").textContent = "";
  const url = $("video-url").value.trim(), bitrate = Number(new FormData(event.target).get("bitrate"));
  lockForm(true);
  try { const { job } = await api("/api/jobs", { method: "POST", body: JSON.stringify({ url, bitrate }) }); clearTimeout(timer); networkFailures = 0; renderJob(job); schedulePoll(); }
  catch (error) {
    $("form-error").textContent = error.message; lockForm(false);
    // A lost POST response may still have started a job. Restore the server's state.
    if (!error.status || error.status === 409) { try { await showWorkspace(); } catch {} }
  }
});
$("cancel").addEventListener("click", async () => {
  if (!currentJob) return; $("cancel").disabled = true; $("cancel").textContent = "취소 중…";
  try { await api(`/api/jobs/${currentJob.id}/cancel`, { method: "POST", body: "{}" }); schedulePoll(500); }
  catch (error) { $("job-message").textContent = error.message; $("cancel").disabled = false; }
});
boot();
