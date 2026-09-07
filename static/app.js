/* Video2Guide 前端逻辑：状态机 = idle → running → done/error */
"use strict";

const $ = (id) => document.getElementById(id);
const el = {
  inputCard: $("input-card"), progressCard: $("progress-card"), errorCard: $("error-card"),
  resultCard: $("result-card"), historyBlock: $("history-block"),
  url: $("url"), btnGo: $("btn-go"), btnSettings: $("btn-settings"),
  segStyle: $("seg-style"), segShots: $("seg-shots"),
  stepper: $("stepper"), logs: $("logs"), progressText: $("progress-text"), elapsed: $("elapsed"),
  errorMsg: $("error-msg"), btnRetry: $("btn-retry"), btnErrorSettings: $("btn-error-settings"),
  resultCover: $("result-cover"), resultTitle: $("result-title"),
  chipUploader: $("chip-uploader"), chipDuration: $("chip-duration"),
  chipSubtitle: $("chip-subtitle"), chipModel: $("chip-model"), linkOrigin: $("link-origin"),
  guide: $("guide"), shotsBlock: $("shots-block"), shots: $("shots"), warnStrip: $("warn-strip"),
  btnCopy: $("btn-copy"), btnDownload: $("btn-download"), btnNew: $("btn-new"),
  historyList: $("history-list"),
  modalMask: $("modal-mask"), btnModalClose: $("btn-modal-close"), btnSaveSettings: $("btn-save-settings"),
  setKey: $("set-key"), setModel: $("set-model"), setSessdata: $("set-sessdata"), hintKey: $("hint-key"),
  toast: $("toast"), exampleLink: $("example-link"),
  historySearch: $("history-search"), historyCount: $("history-count"), segSort: $("seg-sort"),
  referenceUrl: $("reference-url"),
  commentList: $("comment-list"), commentCount: $("comment-count"),
  commentName: $("comment-name"), commentText: $("comment-text"), btnComment: $("btn-comment"),
  toc: $("toc"), readProgress: $("read-progress"), btnTop: $("btn-top"),
  lightbox: $("lightbox"), lightboxImg: $("lightbox-img"),
  lightboxCaption: $("lightbox-caption"), lightboxJump: $("lightbox-jump"),
  brand: $("brand"),
  btnImport: $("btn-import"), importFile: $("import-file"), btnExport: $("btn-export"),
  accessMask: $("access-mask"), accessInput: $("access-key-input"),
  btnAccessOk: $("btn-access-ok"), btnAccessClose: $("btn-access-close"),
};

const LS_KEY = "v2g_settings";
const settings = Object.assign(
  { api_key: "", model: "", sessdata: "", style: "standard", shots: 6, history_sort: "pubdate", access_key: "", reference_url: "" },
  JSON.parse(localStorage.getItem(LS_KEY) || "{}")
);
const saveSettings = () => localStorage.setItem(LS_KEY, JSON.stringify(settings));

let pollTimer = null;
let startTime = 0;
let currentResult = null;
let serverConfig = { has_server_key: false, model: "glm-5.3-flash" };

/* ---------- 工具 ---------- */
function toast(msg) {
  el.toast.textContent = msg;
  el.toast.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.toast.classList.add("hidden"), 2400);
}

function fmtDuration(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}小时${m}分` : `${m}分${s.toString().padStart(2, "0")}秒`;
}

function show(section) {
  [el.inputCard, el.progressCard, el.errorCard, el.resultCard].forEach((s) => s.classList.add("hidden"));
  if (section) section.classList.remove("hidden");
  if (section !== el.resultCard) {
    el.toc.classList.add("hidden");
    tocLinks = [];
    el.readProgress.style.width = "0";
    el.btnTop.classList.add("hidden");
  }
}

/* ---------- 设置 ---------- */
function openSettings() { el.modalMask.classList.remove("hidden"); el.setKey.focus(); }
function closeSettings() { el.modalMask.classList.add("hidden"); }

function loadSettingsUI() {
  el.setKey.value = settings.api_key || "";
  el.setModel.value = settings.model || "";
  el.setSessdata.value = settings.sessdata || "";
  syncSeg(el.segStyle, String(settings.style));
  syncSeg(el.segShots, String(settings.shots));
}

function saveSettingsUI() {
  settings.api_key = el.setKey.value.trim();
  settings.model = el.setModel.value.trim();
  settings.sessdata = el.setSessdata.value.trim();
  saveSettings();
  closeSettings();
  refreshGoState();
  toast("设置已保存（仅保存在本机浏览器）");
}

/* ---------- 分段控件 ---------- */
function syncSeg(seg, val) {
  seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.val === val));
}
[el.segStyle, el.segShots].forEach((seg) => {
  seg.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    syncSeg(seg, btn.dataset.val);
    if (seg === el.segStyle) settings.style = btn.dataset.val;
    else settings.shots = parseInt(btn.dataset.val, 10);
    saveSettings();
  });
});

/* ---------- 输入校验 ---------- */
const URL_OK = /(bilibili\.com|b23\.tv|^\s*(BV[0-9A-Za-z]{10}|av\d+)\s*$)/i;
function urlValid() { return URL_OK.test(el.url.value.trim()); }
function refreshGoState() { el.btnGo.disabled = !urlValid(); }

el.url.addEventListener("input", refreshGoState);
el.url.addEventListener("keydown", (e) => { if (e.key === "Enter" && urlValid()) start(); });
el.exampleLink.addEventListener("click", (e) => {
  e.preventDefault();
  el.url.value = "https://www.bilibili.com/video/BV1LeMU6XEJL";
  refreshGoState();
  el.url.focus();
});

/* ---------- 提交 ---------- */
let pendingSubmission = null;  // 等待密钥的提交请求

async function start() {
  if (!urlValid()) {
    el.url.classList.add("invalid");
    setTimeout(() => el.url.classList.remove("invalid"), 400);
    el.url.focus();
    return;
  }
  if (!settings.api_key && !serverConfig.has_server_key) {
    openSettings();
    toast("请先填写 GLM API Key");
    return;
  }
  const payload = () => ({
    url: el.url.value.trim(),
    style: settings.style,
    shot_count: settings.shots,
    sessdata: settings.sessdata || "",
    api_key: settings.api_key || "",
    model: settings.model || "",
    reference_url: el.referenceUrl.value.trim(),
    access_key: settings.access_key || "",
  });
  try {
    const r = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    if (r.status === 403) {
      // 需要访问密钥
      pendingSubmission = payload();
      el.accessMask.classList.remove("hidden");
      el.accessInput.focus();
      return;
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `请求失败 (${r.status})`);
    }
    const { job_id } = await r.json();
    renderRunning();
    poll(job_id);
  } catch (e) {
    showError(String(e.message || e), false);
  }
}

function closeAccessMask() {
  el.accessMask.classList.add("hidden");
  pendingSubmission = null;
}

async function submitWithAccessKey() {
  const key = el.accessInput.value.trim();
  if (!key) { toast("请输入访问密钥"); return; }
  if (!pendingSubmission) { closeAccessMask(); return; }
  pendingSubmission.access_key = key;
  try {
    const r = await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pendingSubmission),
    });
    if (r.status === 403) {
      toast("密钥不正确，请联系 462574808@qq.com");
      el.accessInput.select();
      return;
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `请求失败 (${r.status})`);
    }
    settings.access_key = key;
    saveSettings();
    closeAccessMask();
    el.accessInput.value = "";
    const { job_id } = await Promise.resolve(r.json());
    renderRunning();
    poll(job_id);
  } catch (e) {
    closeAccessMask();
    showError(String(e.message || e), false);
  }
}

/* ---------- 进行中 ---------- */
function renderRunning() {
  show(el.progressCard);
  el.stepper.innerHTML = "";
  el.logs.innerHTML = "";
  startTime = Date.now();
  el.progressText.textContent = "任务进行中…";
  updateElapsed();
}

function updateElapsed() {
  const s = Math.floor((Date.now() - startTime) / 1000);
  el.elapsed.textContent = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60}s`;
}

function renderSteps(steps) {
  el.stepper.innerHTML = steps
    .map((s) => {
      const icon =
        s.state === "done"
          ? '<svg viewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" d="M4 12.5 9.5 18 20 6.5"/></svg>'
          : s.state === "error"
          ? "!"
          : "&nbsp;";
      return `<div class="step ${s.state}"><div class="step-dot">${icon}</div><div class="step-label">${s.label}</div></div>`;
    })
    .join("");
}

function renderLogs(logs) {
  el.logs.innerHTML = logs
    .map(
      (l) =>
        `<div class="log-line ${l.msg.startsWith("⚠") ? "warn" : ""}"><span class="log-time">${l.t}</span><span>${escapeHtml(l.msg)}</span></div>`
    )
    .join("");
  el.logs.scrollTop = el.logs.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function poll(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    updateElapsed();
    try {
      const r = await fetch(`/api/jobs/${jobId}`);
      if (!r.ok) throw new Error("任务查询失败");
      const job = await r.json();
      renderSteps(job.steps);
      renderLogs(job.logs);
      if (job.status === "running" || job.status === "queued") return;
      clearInterval(pollTimer);
      if (job.status === "done") renderResult(job.result, jobId);
      else showError(job.error || "未知错误", job.error && job.error.includes("SESSDATA"));
    } catch {
      clearInterval(pollTimer);
      showError("与本地服务的连接中断");
    }
  }, 1000);
}

/* ---------- 结果 ---------- */
let currentJobId = null;

function renderResult(res, jobId) {
  currentResult = res;
  currentJobId = jobId;
  const v = res.video;
  el.resultTitle.textContent = v.title;
  el.chipUploader.textContent = "UP主 · " + v.uploader;
  el.chipDuration.textContent = fmtDuration(v.duration);
  el.chipSubtitle.textContent = res.subtitle_desc;
  el.chipModel.textContent = res.model;
  el.linkOrigin.href = v.url;
  if (v.cover) { el.resultCover.src = v.cover; el.resultCover.classList.remove("hidden"); }
  else el.resultCover.classList.add("hidden");

  el.guide.innerHTML = res.guide_html;
  // 字幕覆盖率警告（B站字幕缺失/错配时提示）
  if (res.coverage_warn) {
    el.warnStrip.textContent = res.coverage_warn;
    el.warnStrip.classList.remove("hidden");
  } else {
    el.warnStrip.classList.add("hidden");
  }
  // ▶ 时间戳链接特殊样式
  el.guide.querySelectorAll("a").forEach((a) => {
    if (a.textContent.trim().startsWith("▶")) a.classList.add("ts-chip");
  });

  if (res.shots && res.shots.length) {
    el.shotsBlock.classList.remove("hidden");
    el.shots.innerHTML = res.shots
      .map(
        (s) => `<a class="shot-card" href="${s.jump}" target="_blank" rel="noopener" title="在 B 站打开此时间点">
          <img src="${s.image}" alt="${escapeHtml(s.caption)}" loading="lazy">
          <span class="shot-ts">▶ ${s.ts}</span>
          <div class="shot-caption">${escapeHtml(s.caption)}</div>
        </a>`
      )
      .join("");
  } else {
    el.shotsBlock.classList.add("hidden");
  }

  el.btnDownload.href = res.files.markdown;
  el.btnDownload.setAttribute("download", `${v.title.slice(0, 40)}·攻略.md`);
  el.btnExport.href = `/api/jobs/${jobId}/export`;
  el.btnExport.setAttribute("download", `${v.title.slice(0, 30)}-${jobId}.v2g`);
  show(el.resultCard);
  buildToc();
  loadComments(jobId);
  loadHistory();
  if (location.hash !== `#/g/${jobId}`) {
    suppressHashChange = true;
    location.hash = `#/g/${jobId}`;
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------- 路由 ---------- */
let suppressHashChange = false;

function goHome() {
  currentJobId = null;
  currentResult = null;
  show(el.inputCard);
  renderHistory();
  if (location.hash && location.hash !== "#/") {
    suppressHashChange = true;
    location.hash = "#/";
  }
  el.url.select();
}

window.addEventListener("hashchange", () => {
  if (suppressHashChange) { suppressHashChange = false; return; }
  const m = location.hash.match(/^#\/g\/(.+)$/);
  if (m && m[1] !== currentJobId) {
    reopen(m[1]);
  } else if (!location.hash || location.hash === "#/") {
    if (currentJobId) goHomeInternal();
  }
});

function goHomeInternal() {
  currentJobId = null;
  currentResult = null;
  show(el.inputCard);
  renderHistory();
}

/* ---------- 评论 ---------- */
async function loadComments(jobId) {
  try {
    const { comments } = await (await fetch(`/api/jobs/${jobId}/comments`)).json();
    renderComments(comments);
  } catch {
    renderComments([]);
  }
}

function renderComments(comments) {
  el.commentCount.textContent = comments.length ? `(${comments.length})` : "";
  if (!comments.length) {
    el.commentList.innerHTML = '<div class="comment-empty">还没有评论，来抢沙发～</div>';
    return;
  }
  el.commentList.innerHTML = comments
    .map(
      (c) => `<div class="comment-item">
        <div class="comment-head"><span class="comment-name">${escapeHtml(c.name)}</span><span class="comment-time">${c.time}</span></div>
        <div class="comment-text">${escapeHtml(c.text)}</div>
      </div>`
    )
    .join("");
}

async function submitComment() {
  if (!currentJobId) return;
  const text = el.commentText.value.trim();
  if (!text) { toast("评论内容不能为空"); return; }
  el.btnComment.disabled = true;
  try {
    const r = await fetch(`/api/jobs/${currentJobId}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: el.commentName.value, text }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "提交失败");
    const { comments } = await r.json();
    renderComments(comments);
    el.commentText.value = "";
    toast("评论已发表");
  } catch (e) {
    toast(String(e.message || e));
  } finally {
    el.btnComment.disabled = false;
  }
}
el.btnComment.addEventListener("click", submitComment);
el.commentText.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submitComment();
});


let tocLinks = [];

function buildToc() {
  el.toc.innerHTML = "";
  tocLinks = [];
  const heads = [...el.guide.querySelectorAll("h2")];
  if (!el.shotsBlock.classList.contains("hidden")) {
    const st = el.shotsBlock.querySelector(".shots-title");
    if (st) heads.push(st);
  }
  if (heads.length < 3) { el.toc.classList.add("hidden"); return; }
  heads.forEach((h, i) => {
    h.id = h.id || `sec-${i}`;
    const a = document.createElement("a");
    a.href = `#${h.id}`;
    a.textContent = h.textContent.trim();
    a.addEventListener("click", (e) => {
      e.preventDefault();
      window.scrollTo({ top: h.offsetTop - 76, behavior: "smooth" });
    });
    el.toc.appendChild(a);
    tocLinks.push({ a, h });
  });
  el.toc.classList.remove("hidden");
}

function onScrollUI() {
  // 阅读进度
  const docH = document.documentElement.scrollHeight - window.innerHeight;
  const pct = docH > 0 ? Math.min(100, (window.scrollY / docH) * 100) : 0;
  el.readProgress.style.width = `${pct}%`;
  // 回到顶部
  el.btnTop.classList.toggle("hidden", window.scrollY < 500);
  // 目录高亮：当前阅读章节
  let active = null;
  for (const { a, h } of tocLinks) {
    if (h.offsetTop - 90 <= window.scrollY) active = a;
  }
  tocLinks.forEach(({ a }) => a.classList.toggle("active", a === active));
}

/* ---------- 灯箱 ---------- */
function openLightbox(src, caption, jumpUrl) {
  el.lightboxImg.src = src;
  el.lightboxCaption.textContent = caption || "";
  if (jumpUrl) {
    el.lightboxJump.href = jumpUrl;
    el.lightboxJump.classList.remove("hidden");
  } else {
    el.lightboxJump.classList.add("hidden");
  }
  el.lightbox.classList.remove("hidden");
}

function closeLightbox() {
  el.lightbox.classList.add("hidden");
  el.lightboxImg.src = "";
}

/* ---------- 错误 ---------- */
function showError(msg, needSettings) {
  el.errorMsg.textContent = msg;
  el.btnErrorSettings.classList.toggle("hidden", !needSettings);
  show(el.errorCard);
}

/* ---------- 历史 ---------- */
let historyJobs = [];   // 原始列表
let historyRendered = false;

function fmtPubdate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function seasonOf(title) {
  const m = title.match(/^([春夏秋冬])/);
  return m ? m[1] : "";
}

async function loadHistory() {
  try {
    const r = await fetch("/api/jobs");
    historyJobs = (await r.json()).jobs || [];
  } catch { historyJobs = []; }
  renderHistory();
}

function renderHistory() {
  const list = el.historyList;
  const search = el.historySearch.value.trim().toLowerCase();
  const sortBy = settings.history_sort || "pubdate";

  // 去重：同一视频只保留最新一份（优先成功任务）
  const byBv = new Map();
  for (const j of historyJobs) {
    const bv = j.bvid || (j.url || "").match(/BV[0-9A-Za-z]{10}/)?.[0] || j.id;
    const prev = byBv.get(bv);
    if (!prev || (j.status === "done" && prev.status !== "done")) byBv.set(bv, j);
  }
  let items = [...byBv.values()];

  if (search) items = items.filter((j) => (j.title || "").toLowerCase().includes(search));

  if (sortBy === "pubdate" && items.some((j) => j.pubdate)) {
    items.sort((a, b) => (a.pubdate || 0) - (b.pubdate || 0));
  } else {
    items.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  }

  el.historyCount.textContent = search
    ? `${items.length} / ${byBv.size} 个视频`
    : `共 ${byBv.size} 个视频`;

  if (!items.length) {
    el.historyBlock.classList.add("hidden");
    return;
  }
  el.historyBlock.classList.remove("hidden");

  const useGroups = sortBy === "pubdate";
  let html = "";
  let lastSeason = null;
  for (const j of items) {
    if (useGroups) {
      const s = seasonOf(j.title || "");
      const group = s ? `${s} 季` : "其他";
      if (group !== lastSeason) {
        html += `<div class="history-group">${group}</div>`;
        lastSeason = group;
      }
    }
    const date = useGroups && j.pubdate ? fmtPubdate(j.pubdate) : j.created_at.slice(5, 16);
    const thumb = j.cover
      ? `<img class="history-thumb" src="${j.cover}" loading="lazy" alt="">`
      : `<div class="history-thumb"></div>`;
    html += `<div class="history-item${j.id === currentJobId ? " active" : ""}" data-id="${j.id}" title="${escapeHtml(j.title || "")}">
      ${thumb}
      <div class="h-main">
        <span class="h-title">${escapeHtml(j.title || j.id)}</span>
        <span class="h-meta"><span class="h-dot ${j.status}"></span><span class="h-time">${date}</span></span>
      </div>
    </div>`;
  }
  list.innerHTML = html;
  list.querySelectorAll(".history-item").forEach((item) => {
    item.addEventListener("click", () => reopen(item.dataset.id));
  });
}

async function reopen(jobId) {
  const r = await fetch(`/api/jobs/${jobId}`);
  if (!r.ok) { toast("任务不存在（服务可能已重启）"); return; }
  const job = await r.json();
  if (job.status === "done") { renderResult(job.result, jobId); return; }
  if (job.status === "error") { showError(job.error || "未知错误"); return; }
  renderRunning();
  renderSteps(job.steps);
  renderLogs(job.logs);
  poll(jobId);
}

/* ---------- 事件绑定 ---------- */
el.btnGo.addEventListener("click", start);
el.btnSettings.addEventListener("click", openSettings);
el.btnModalClose.addEventListener("click", closeSettings);
el.btnSaveSettings.addEventListener("click", saveSettingsUI);
el.modalMask.addEventListener("click", (e) => { if (e.target === el.modalMask) closeSettings(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSettings(); });
el.btnRetry.addEventListener("click", () => { show(el.inputCard); el.url.focus(); });
el.btnErrorSettings.addEventListener("click", openSettings);
el.btnNew.addEventListener("click", () => { show(el.inputCard); el.url.select(); });
el.btnCopy.addEventListener("click", async () => {
  if (!currentResult) return;
  try {
    await navigator.clipboard.writeText(currentResult.guide_md);
    toast("Markdown 已复制到剪贴板");
  } catch {
    // 剪贴板 API 不可用时降级
    const ta = document.createElement("textarea");
    ta.value = currentResult.guide_md;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      toast("Markdown 已复制到剪贴板");
    } catch {
      toast("复制失败，请使用「下载 .md」");
    }
    ta.remove();
  }
});
document.querySelectorAll(".reveal").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = $(btn.dataset.target);
    const show_ = input.type === "password";
    input.type = show_ ? "text" : "password";
    btn.textContent = show_ ? "隐藏" : "显示";
  });
});

/* ---------- 全局 UI：滚动 / 灯箱 / 快捷键 ---------- */
let scrollRaf = null;
window.addEventListener("scroll", () => {
  if (scrollRaf) return;
  scrollRaf = requestAnimationFrame(() => { scrollRaf = null; onScrollUI(); });
});

el.btnTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

// 灯箱：截图卡片点击先看大图；正文图片也可放大
document.addEventListener("click", (e) => {
  const card = e.target.closest(".shot-card");
  if (card) {
    e.preventDefault();
    const img = card.querySelector("img");
    if (img) openLightbox(img.src, img.alt, card.href);
    return;
  }
  const gimg = e.target.closest(".guide-content img");
  if (gimg) {
    e.preventDefault();
    openLightbox(gimg.src, gimg.alt || "", "");
    return;
  }
  if (e.target === el.lightbox) closeLightbox();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeLightbox(); closeSettings(); closeAccessMask(); return; }
  if (e.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "")) {
    e.preventDefault();
    el.historySearch.focus();
    el.historySearch.select();
  }
});

/* 品牌点击回主页 / 密钥弹窗 / 参考链接持久化 */
el.brand.addEventListener("click", (e) => { e.preventDefault(); goHome(); });
el.btnAccessOk.addEventListener("click", submitWithAccessKey);
el.btnAccessClose.addEventListener("click", closeAccessMask);
el.accessMask.addEventListener("click", (e) => { if (e.target === el.accessMask) closeAccessMask(); });
el.accessInput.addEventListener("keydown", (e) => { if (e.key === "Enter") submitWithAccessKey(); });
el.referenceUrl.value = settings.reference_url || "";
el.referenceUrl.addEventListener("input", () => {
  settings.reference_url = el.referenceUrl.value.trim();
  saveSettings();
});

/* ---------- 导入 .v2g ---------- */
el.btnImport.addEventListener("click", () => el.importFile.click());
el.importFile.addEventListener("change", async () => {
  const f = el.importFile.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  el.btnImport.disabled = true;
  try {
    const r = await fetch("/api/jobs/import", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `导入失败 (${r.status})`);
    toast(`已导入《${(data.title || "").slice(0, 20)}》`);
    loadHistory();
    reopen(data.job_id);
  } catch (e) {
    toast(String(e.message || e));
  } finally {
    el.btnImport.disabled = false;
    el.importFile.value = "";
  }
});

/* ---------- 主题切换 ---------- */
$("btn-theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("v2g_theme", next);
});

/* ---------- 初始化 ---------- */
(async function init() {
  loadSettingsUI();
  refreshGoState();
  syncSeg(el.segSort, settings.history_sort || "pubdate");
  el.segSort.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    syncSeg(el.segSort, btn.dataset.val);
    settings.history_sort = btn.dataset.val;
    saveSettings();
    renderHistory();
  });
  let searchTimer = null;
  el.historySearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderHistory, 150);
  });
  try {
    serverConfig = await (await fetch("/api/config")).json();
    if (serverConfig.has_server_key) {
      el.hintKey.textContent = "服务端 .env 已配置 Key，此处可留空。";
    }
    if (!settings.model) el.setModel.placeholder = serverConfig.model;
  } catch { /* 忽略 */ }
  loadHistory();
  // 初始路由：#/g/{jobId} 直接打开对应文章
  const m = location.hash.match(/^#\/g\/(.+)$/);
  if (m) reopen(m[1]);
})();
