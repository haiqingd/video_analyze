/* Video2Guide 前端逻辑：状态机 = idle → running → done/error */
"use strict";

const $ = (id) => document.getElementById(id);
const el = {
  inputCard: $("input-card"), progressCard: $("progress-card"), errorCard: $("error-card"),
  resultCard: $("result-card"),
  sidebar: $("sidebar"), sbCollections: $("sb-collections"), sbEpisodes: $("sb-episodes"),
  sbCollList: $("sb-coll-list"), sbEpList: $("sb-ep-list"), sbSearch: $("sb-search"),
  btnSbBack: $("btn-sb-back"), sbCollTitle: $("sb-coll-title"), sbCollMeta: $("sb-coll-meta"),
  btnSidebar: $("btn-sidebar"),
  segColSort: $("seg-col-sort"), btnParseNew: $("btn-parse-new"),
  epNav: $("ep-nav"), btnPrevEp: $("btn-prev-ep"), btnNextEp: $("btn-next-ep"), epPos: $("ep-pos"),
  url: $("url"), btnGo: $("btn-go"), btnSettings: $("btn-settings"),
  segStyle: $("seg-style"), segShots: $("seg-shots"),
  stepper: $("stepper"), logs: $("logs"), progressText: $("progress-text"), elapsed: $("elapsed"),
  errorMsg: $("error-msg"), btnRetry: $("btn-retry"), btnErrorSettings: $("btn-error-settings"),
  resultCover: $("result-cover"), resultTitle: $("result-title"),
  chipUploader: $("chip-uploader"), chipDuration: $("chip-duration"),
  chipSubtitle: $("chip-subtitle"), chipModel: $("chip-model"), chipSeason: $("chip-season"),
  linkOrigin: $("link-origin"),
  guide: $("guide"), shotsBlock: $("shots-block"), shots: $("shots"), warnStrip: $("warn-strip"),
  btnCopy: $("btn-copy"), btnDownload: $("btn-download"), btnNew: $("btn-new"),
  modalMask: $("modal-mask"), btnModalClose: $("btn-modal-close"), btnSaveSettings: $("btn-save-settings"),
  setKey: $("set-key"), setModel: $("set-model"), setSessdata: $("set-sessdata"), hintKey: $("hint-key"),
  toast: $("toast"), exampleLink: $("example-link"),
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
  seasonMask: $("season-mask"), seasonTitle: $("season-title"), seasonSub: $("season-sub"),
  seasonList: $("season-list"), seasonAll: $("season-all"), seasonSelected: $("season-selected"),
  btnSeasonClose: $("btn-season-close"), btnSeasonGo: $("btn-season-go"),
  btnSeasonCurrent: $("btn-season-current"),
};

const LS_KEY = "v2g_settings";
const settings = Object.assign(
  { api_key: "", model: "", sessdata: "", style: "standard", shots: 6, collection_sort: "order", access_key: "", reference_url: "" },
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
let pendingResume = null;   // 等待访问密钥后要继续的流程
let pollBatchTimer = null;

const buildPayload = (url) => ({
  url: (url || el.url.value).trim(),
  style: settings.style,
  shot_count: settings.shots,
  sessdata: settings.sessdata || "",
  api_key: settings.api_key || "",
  model: settings.model || "",
  reference_url: el.referenceUrl.value.trim(),
  access_key: settings.access_key || "",
});

function needKey() {
  if (!settings.api_key && !serverConfig.has_server_key) {
    openSettings();
    toast("请先填写 GLM API Key");
    return true;
  }
  return false;
}

async function start() {
  if (!urlValid()) {
    el.url.classList.add("invalid");
    setTimeout(() => el.url.classList.remove("invalid"), 400);
    el.url.focus();
    return;
  }
  if (needKey()) return;
  const url = el.url.value.trim();
  // 合集检测：视频属于 B 站合集时，先让用户选择要解析哪些视频
  try {
    const r = await fetch("/api/season", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, access_key: settings.access_key || "" }),
    });
    if (r.status === 403) {
      pendingResume = start;
      el.accessMask.classList.remove("hidden");
      el.accessInput.focus();
      return;
    }
    if (r.ok) {
      const info = await r.json();
      if (info.season_id && info.episodes && info.episodes.length) {
        showSeasonPicker(info, { preselect: [info.bvid], source: "parse", currentUrl: url });
        return;
      }
    }
  } catch { /* 合集查询失败不阻塞正常解析 */ }
  submitBatch([url]);
}

function closeAccessMask() {
  el.accessMask.classList.add("hidden");
  pendingResume = null;
}

async function submitWithAccessKey() {
  const key = el.accessInput.value.trim();
  if (!key) { toast("请输入访问密钥"); return; }
  settings.access_key = key;
  saveSettings();
  const resume = pendingResume;
  closeAccessMask();
  el.accessInput.value = "";
  if (resume) await resume();
}

async function submitBatch(urls) {
  const jobIds = [];
  let firstErr = "";
  for (const u of urls) {
    try {
      const r = await fetch("/api/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload(u)),
      });
      if (r.status === 403) {
        pendingResume = () => submitBatch(urls);
        el.accessMask.classList.remove("hidden");
        el.accessInput.focus();
        return;
      }
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `请求失败 (${r.status})`);
      }
      jobIds.push((await r.json()).job_id);
    } catch (e) {
      firstErr = String(e.message || e);
    }
  }
  if (!jobIds.length) {
    showError(firstErr || "提交失败", false);
    return;
  }
  if (jobIds.length > 1) {
    toast(`已提交 ${jobIds.length} 个解析任务，其余任务在后台排队处理`);
    watchBatch(jobIds.slice());
  }
  renderRunning();
  poll(jobIds[0]);
}

function watchBatch(ids) {
  // 批量任务：后台轮询剩余任务，全部结束后刷新历史/合集列表
  clearInterval(pollBatchTimer);
  pollBatchTimer = setInterval(async () => {
    let running = 0;
    for (const id of ids) {
      try {
        const j = await (await fetch(`/api/jobs/${id}`)).json();
        if (j.status === "running" || j.status === "queued") running++;
      } catch { running++; }
    }
    if (!running) {
      clearInterval(pollBatchTimer);
      loadHistory();
      toast("合集批量解析完成");
    }
  }, 15000);
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
  if (v.season_id && v.season_title) {
    el.chipSeason.dataset.sid = String(v.season_id);
    el.chipSeason.textContent = `合集 · ${v.season_title} ›`;
    el.chipSeason.classList.remove("hidden");
  } else {
    el.chipSeason.dataset.sid = "";
    el.chipSeason.classList.add("hidden");
  }
  syncSidebarToSeason(v.season_id);   // 打开攻略自动在左侧栏选中其所属合集
  renderEpisodeNav(v);
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

/* ---------- 路由：#/ 首页+合集列表 | #/c/{seasonId} 合集内视频列表 | #/g/{jobId} 攻略 ---------- */
let suppressHashChange = false;
let currentSeasonId = null;   // 左侧栏选中的合集（null = 显示合集列表；"0" = 单集汇总）

function goHome() {
  currentJobId = null;
  currentResult = null;
  currentSeasonId = null;
  show(el.inputCard);
  renderSidebar();
  if (location.hash && location.hash !== "#/") {
    suppressHashChange = true;
    location.hash = "#/";
  }
  el.url.select();
}

window.addEventListener("hashchange", () => {
  if (suppressHashChange) { suppressHashChange = false; return; }
  const g = location.hash.match(/^#\/g\/(.+)$/);
  const c = location.hash.match(/^#\/c\/(\d+)$/);
  if (g && g[1] !== currentJobId) {
    reopen(g[1]);
  } else if (c && (c[1] !== String(currentSeasonId) || currentJobId)) {
    openCollectionList(c[1]);
  } else if (!location.hash || location.hash === "#/") {
    if (currentJobId || currentSeasonId !== null) goHomeInternal();
  }
});

function goHomeInternal() {
  currentJobId = null;
  currentResult = null;
  currentSeasonId = null;
  show(el.inputCard);
  renderSidebar();
}

/* ---------- 左侧栏：合集列表 ⇄ 合集内视频 ---------- */
function collectionJobs(id) {
  // 某合集（id=0 表示无合集单集）下的全部视频，同一 BV 只保留一份（优先成功任务）
  const byBv = new Map();
  for (const j of historyJobs) {
    if (String(j.season_id || 0) !== String(id)) continue;
    const bv = j.bvid || (j.url || "").match(/BV[0-9A-Za-z]{10}/)?.[0] || j.id;
    const prev = byBv.get(bv);
    if (!prev || (j.status === "done" && prev.status !== "done")) byBv.set(bv, j);
  }
  return [...byBv.values()];
}

function closeMobileSidebar() {
  el.sidebar.classList.remove("open");
}

function openCollectionList(id) {
  // 选中合集（#/c/）：左侧栏切到该合集的视频列表，主区域回首页
  currentJobId = null;
  currentResult = null;
  currentSeasonId = id;
  show(el.inputCard);
  renderSidebar();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function syncSidebarToSeason(seasonId) {
  // 打开攻略时自动选中其所属合集（不切换主区域视图）
  currentSeasonId = seasonId ? String(seasonId) : null;
  renderSidebar();
}

function renderSidebar() {
  if (currentSeasonId === null) {
    el.sbCollections.classList.remove("hidden");
    el.sbEpisodes.classList.add("hidden");
    renderSidebarCollections();
  } else {
    el.sbCollections.classList.add("hidden");
    el.sbEpisodes.classList.remove("hidden");
    renderSidebarEpisodes();
  }
}

function renderSidebarCollections() {
  const search = (el.sbSearch.value || "").trim().toLowerCase();
  const items = dedupByBv(historyJobs);
  // 搜索：跨合集匹配视频标题，平铺展示
  if (search) {
    const hit = items
      .filter((j) => (j.title || "").toLowerCase().includes(search))
      .sort((a, b) => (b.pubdate || 0) - (a.pubdate || 0));
    el.sbCollList.innerHTML = hit
      .map((j) => itemRowHtml(j, j.pubdate ? fmtPubdate(j.pubdate) : j.created_at.slice(5, 16)))
      .join("");
    el.sbCollList.querySelectorAll(".history-item").forEach((row) => {
      row.addEventListener("click", () => { closeMobileSidebar(); reopen(row.dataset.id); });
    });
    return;
  }
  // 默认：合集卡片（按最近更新倒序，单集最后）
  const byKey = new Map();
  for (const j of items) {
    const key = j.season_id ? String(j.season_id) : "0";
    if (!byKey.has(key)) byKey.set(key, { id: key, title: j.season_title || "单集视频", jobs: [] });
    byKey.get(key).jobs.push(j);
  }
  const cards = [...byKey.values()].map((c) => {
    c.ts = Math.max(...c.jobs.map((j) => j.pubdate || 0));
    c.uploader = (c.jobs.find((j) => j.uploader) || {}).uploader || "";
    return c;
  });
  const singles = cards.filter((c) => c.id === "0").sort((a, b) => b.ts - a.ts);
  const named = cards.filter((c) => c.id !== "0").sort((a, b) => b.ts - a.ts);
  el.sbCollList.innerHTML = [...named, ...singles]
    .map((c) => {
      const cover = (c.jobs.find((j) => j.cover) || {}).cover || "";
      const img = cover ? `<img src="${cover}" loading="lazy" alt="">` : "";
      return `<div class="sb-coll-item" data-id="${c.id}" title="${escapeHtml(c.title)}">
        <div class="sb-coll-cover">${img}</div>
        <div class="sb-coll-main">
          <span class="sb-coll-name">${escapeHtml(c.title)}</span>
          <span class="sb-coll-sub">${c.jobs.length} 个视频${c.uploader ? " · " + escapeHtml(c.uploader) : ""}</span>
        </div>
        <span class="sb-coll-count">${c.ts ? fmtPubdate(c.ts).slice(2) : ""}</span>
      </div>`;
    })
    .join("");
  el.sbCollList.querySelectorAll(".sb-coll-item").forEach((card) => {
    card.addEventListener("click", () => {
      closeMobileSidebar();
      location.hash = `#/c/${card.dataset.id}`;
    });
  });
}

function renderSidebarEpisodes() {
  const id = currentSeasonId;
  const jobs = collectionJobs(id);
  const named = jobs.find((j) => j.season_title);
  el.sbCollTitle.textContent = id === "0" ? "单集视频" : (named ? named.season_title : "合集");
  const uploader = (jobs.find((j) => j.uploader) || {}).uploader || "";
  el.sbCollMeta.textContent = `${jobs.length} 个视频${uploader ? " · " + uploader : ""}`;
  el.btnParseNew.classList.toggle("hidden", id === "0" || !jobs.some((j) => j.bvid));
  renderCollectionList(jobs);
}

function renderCollectionList(jobs) {
  const sortBy = settings.collection_sort || "order";
  const items = [...jobs];
  if (sortBy === "order") items.sort((a, b) => (a.pubdate || Infinity) - (b.pubdate || Infinity));
  else if (sortBy === "pubdesc") items.sort((a, b) => (b.pubdate || 0) - (a.pubdate || 0));
  else items.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  el.sbEpList.innerHTML = items
    .map((j) => {
      const date = sortBy === "created" || !j.pubdate
        ? j.created_at.slice(5, 16)
        : fmtPubdate(j.pubdate);
      const thumb = j.cover
        ? `<img class="history-thumb" src="${j.cover}" loading="lazy" alt="">`
        : `<div class="history-thumb"></div>`;
      return `<div class="history-item collection-row${j.id === currentJobId ? " active" : ""}" data-id="${j.id}" title="${escapeHtml(j.title || "")}">
        ${thumb}
        <div class="h-main">
          <span class="h-title">${escapeHtml(j.title || j.id)}</span>
          <span class="h-meta"><span class="h-dot ${j.status}"></span><span class="h-time">${date}</span></span>
        </div>
      </div>`;
    })
    .join("");
  el.sbEpList.querySelectorAll(".history-item").forEach((item) => {
    item.addEventListener("click", () => { closeMobileSidebar(); reopen(item.dataset.id); });
  });
  // 当前正在看的集数滚进侧栏可视区
  const activeRow = el.sbEpList.querySelector(".history-item.active");
  if (activeRow) activeRow.scrollIntoView({ block: "nearest" });
}

/* ---------- 攻略页：合集内上一集 / 下一集 ---------- */
function renderEpisodeNav(v) {
  if (!v || !v.season_id || !v.bvid || !historyJobs.length) {
    el.epNav.classList.add("hidden");
    return;
  }
  const jobs = collectionJobs(String(v.season_id))
    .sort((a, b) => (a.pubdate || Infinity) - (b.pubdate || Infinity));
  const idx = jobs.findIndex((j) => j.bvid === v.bvid);
  if (idx < 0 || jobs.length < 2) {
    el.epNav.classList.add("hidden");
    return;
  }
  const prev = idx > 0 ? jobs[idx - 1] : null;
  const next = idx < jobs.length - 1 ? jobs[idx + 1] : null;
  el.btnPrevEp.disabled = !prev;
  el.btnNextEp.disabled = !next;
  el.btnPrevEp.title = prev ? `上一集：${prev.title.slice(0, 30)}` : "已经是第一集";
  el.btnNextEp.title = next ? `下一集：${next.title.slice(0, 30)}` : "已经是最后一集";
  el.epPos.textContent = `第 ${idx + 1} / ${jobs.length} 集`;
  el.btnPrevEp.onclick = () => prev && reopen(prev.id);
  el.btnNextEp.onclick = () => next && reopen(next.id);
  el.epNav.classList.remove("hidden");
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

/* ---------- 任务列表数据（左侧栏与合集导航的数据源） ---------- */
let historyJobs = [];   // 原始列表

function fmtPubdate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dedupByBv(jobs) {
  // 同一视频只保留一份（优先成功任务；同状态保留更新近创建的）
  const byBv = new Map();
  for (const j of jobs) {
    const bv = j.bvid || (j.url || "").match(/BV[0-9A-Za-z]{10}/)?.[0] || j.id;
    const prev = byBv.get(bv);
    if (!prev || (j.status === "done" && prev.status !== "done")) byBv.set(bv, j);
  }
  return [...byBv.values()];
}

function itemRowHtml(j, date) {
  const thumb = j.cover
    ? `<img class="history-thumb" src="${j.cover}" loading="lazy" alt="">`
    : `<div class="history-thumb"></div>`;
  return `<div class="history-item${j.id === currentJobId ? " active" : ""}" data-id="${j.id}" title="${escapeHtml(j.title || "")}">
    ${thumb}
    <div class="h-main">
      <span class="h-title">${escapeHtml(j.title || j.id)}</span>
      <span class="h-meta"><span class="h-dot ${j.status}"></span><span class="h-time">${date}</span></span>
    </div>
  </div>`;
}

async function loadHistory() {
  try {
    const r = await fetch("/api/jobs");
    historyJobs = (await r.json()).jobs || [];
  } catch { historyJobs = []; }
  renderSidebar();
  // 正在看攻略时同步集数导航（新任务完成、列表变化）
  if (currentJobId && currentResult) renderEpisodeNav(currentResult.video);
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

/* ---------- 合集选集弹窗 ---------- */
let seasonInfo = null;
let seasonState = { preselect: [], source: "parse", currentUrl: "" };

async function fetchSeason(body) {
  // 返回 {status, info}：status = ok | forbidden | fail
  try {
    const r = await fetch("/api/season", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, access_key: settings.access_key || "" }),
    });
    if (r.status === 403) return { status: "forbidden" };
    if (!r.ok) return { status: "fail" };
    return { status: "ok", info: await r.json() };
  } catch {
    return { status: "fail" };
  }
}

function showSeasonPicker(info, opts) {
  seasonInfo = info;
  seasonState = opts;
  const parsed = info.episodes.filter((e) => e.parsed).length;
  el.seasonTitle.textContent = `选择合集视频 · ${info.season_title}`;
  el.seasonSub.textContent = `UP主 ${info.uploader} · 共 ${info.episodes.length} 集 · 已解析 ${parsed} 集`;
  el.btnSeasonCurrent.classList.toggle("hidden", opts.source !== "parse");
  renderSeasonList();
  el.seasonMask.classList.remove("hidden");
}

function closeSeasonPicker() {
  el.seasonMask.classList.add("hidden");
  seasonInfo = null;
}

function renderSeasonList() {
  const eps = [...(seasonInfo ? seasonInfo.episodes : [])].sort((a, b) => (a.pubdate || 0) - (b.pubdate || 0));
  el.seasonList.innerHTML = eps
    .map((e) => {
      const date = e.pubdate ? fmtPubdate(e.pubdate) : "";
      if (e.parsed) {
        return `<div class="season-row parsed" data-job="${e.job_id}" title="已生成攻略，点击查看">
          <span class="season-done-badge">✓</span>
          <span class="season-title">${escapeHtml(e.title)}</span>
          <span class="season-badge">已生成</span>
          <span class="season-date">${date}</span>
        </div>`;
      }
      const checked = seasonState.preselect.includes(e.bvid) ? " checked" : "";
      return `<label class="season-row">
        <input type="checkbox" class="season-check" data-bv="${e.bvid}"${checked}>
        <span class="season-title">${escapeHtml(e.title)}</span>
        <span class="season-date">${date}</span>
      </label>`;
    })
    .join("");
  el.seasonList.querySelectorAll("input.season-check").forEach((cb) => {
    cb.addEventListener("change", updateSeasonCount);
  });
  el.seasonList.querySelectorAll(".season-row.parsed").forEach((row) => {
    row.addEventListener("click", () => {
      const id = row.dataset.job;
      closeSeasonPicker();
      if (id) reopen(id);
    });
  });
  updateSeasonCount();
}

function updateSeasonCount() {
  const boxes = [...el.seasonList.querySelectorAll("input.season-check")];
  const n = boxes.filter((cb) => cb.checked).length;
  el.seasonSelected.textContent = `已选 ${n} 个视频`;
  el.seasonAll.checked = n > 0 && n === boxes.length;
  el.btnSeasonGo.disabled = n === 0;
}

function submitSeasonSelection() {
  const bvs = [...el.seasonList.querySelectorAll("input.season-check:checked")].map((cb) => cb.dataset.bv);
  closeSeasonPicker();
  submitBatch(bvs.map((bv) => `https://www.bilibili.com/video/${bv}`));
}

async function parseCollectionNew() {
  if (needKey()) return;
  const jobs = collectionJobs(currentSeasonId);
  const bv = (jobs.find((j) => j.bvid) || {}).bvid;
  if (!bv) { toast("没有可用的视频信息"); return; }
  const { status, info } = await fetchSeason({ bvid: bv });
  if (status === "forbidden") {
    pendingResume = parseCollectionNew;
    el.accessMask.classList.remove("hidden");
    el.accessInput.focus();
    return;
  }
  if (status !== "ok" || !info.season_id) { toast("合集信息获取失败，请稍后再试"); return; }
  const unparsed = info.episodes.filter((e) => !e.parsed).map((e) => e.bvid);
  showSeasonPicker(info, { preselect: unparsed, source: "collection", currentUrl: "" });
}

/* ---------- 事件绑定 ---------- */
el.btnGo.addEventListener("click", start);
el.btnSettings.addEventListener("click", openSettings);
el.btnModalClose.addEventListener("click", closeSettings);
el.btnSaveSettings.addEventListener("click", saveSettingsUI);
el.modalMask.addEventListener("click", (e) => { if (e.target === el.modalMask) closeSettings(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeLightbox(); closeSettings(); closeAccessMask(); closeSeasonPicker(); }
});
el.btnRetry.addEventListener("click", () => { show(el.inputCard); el.url.focus(); });
el.btnErrorSettings.addEventListener("click", openSettings);
el.btnNew.addEventListener("click", () => { show(el.inputCard); el.url.select(); });

/* 合集选集弹窗 */
el.seasonMask.addEventListener("click", (e) => { if (e.target === el.seasonMask) closeSeasonPicker(); });
el.btnSeasonClose.addEventListener("click", closeSeasonPicker);
el.seasonAll.addEventListener("change", () => {
  el.seasonList.querySelectorAll("input.season-check").forEach((cb) => { cb.checked = el.seasonAll.checked; });
  updateSeasonCount();
});
el.btnSeasonGo.addEventListener("click", submitSeasonSelection);
el.btnSeasonCurrent.addEventListener("click", () => {
  const url = seasonState.currentUrl;
  closeSeasonPicker();
  if (url) submitBatch([url]);
});

/* 合集内容页 */
el.btnParseNew.addEventListener("click", parseCollectionNew);

/* 左侧栏：返回合集列表 / 移动端开关 / 攻略页合集 chip 定位 */
el.btnSbBack.addEventListener("click", () => {
  closeMobileSidebar();
  location.hash = "#/";
});
el.btnSidebar.addEventListener("click", () => el.sidebar.classList.toggle("open"));
el.chipSeason.addEventListener("click", (e) => {
  e.preventDefault();
  const sid = el.chipSeason.dataset.sid;
  if (!sid) return;
  syncSidebarToSeason(sid);
  const row = el.sbEpList.querySelector(".history-item.active");
  if (row) row.scrollIntoView({ block: "center", behavior: "smooth" });
  if (window.innerWidth < 900) el.sidebar.classList.add("open");
});
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
  if (e.key === "Escape") { closeLightbox(); closeSettings(); closeAccessMask(); closeSeasonPicker(); return; }
  if (e.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "")) {
    e.preventDefault();
    if (currentSeasonId !== null) {
      // 已在合集内：先回到合集列表态再聚焦搜索
      currentSeasonId = null;
      renderSidebar();
    }
    el.sbSearch.focus();
    el.sbSearch.select();
  }
  // 攻略页 ←/→ 切换合集内上一集/下一集
  if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !el.resultCard.classList.contains("hidden")
      && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || "")) {
    const btn = e.key === "ArrowLeft" ? el.btnPrevEp : el.btnNextEp;
    if (btn && !btn.disabled) btn.click();
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
  syncSeg(el.segColSort, settings.collection_sort || "order");
  el.segColSort.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    syncSeg(el.segColSort, btn.dataset.val);
    settings.collection_sort = btn.dataset.val;
    saveSettings();
    renderCollectionList(collectionJobs(currentSeasonId));
  });
  let searchTimer = null;
  el.sbSearch.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderSidebar, 150);
  });
  try {
    serverConfig = await (await fetch("/api/config")).json();
    if (serverConfig.has_server_key) {
      el.hintKey.textContent = "服务端 .env 已配置 Key，此处可留空。";
    }
    if (!settings.model) el.setModel.placeholder = serverConfig.model;
  } catch { /* 忽略 */ }
  await loadHistory();
  // 初始路由：#/g/{jobId} 打开文章（侧栏自动选中其合集）；#/c/{seasonId} 选中合集
  const g = location.hash.match(/^#\/g\/(.+)$/);
  const c = location.hash.match(/^#\/c\/(\d+)$/);
  if (g) reopen(g[1]);
  else if (c) openCollectionList(c[1]);
})();
