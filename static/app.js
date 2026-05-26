const stateUrl = String(window.PADRES_BOARD_STATE_URL || "/api/state");
const lowPowerMode =
  Boolean(window.PADRES_BOARD_LOW_POWER) ||
  (document.body instanceof HTMLElement && document.body.classList.contains("low-power-mode"));
const keepLowPowerTransitions =
  Boolean(window.PADRES_BOARD_KEEP_TRANSITIONS) ||
  (document.body instanceof HTMLElement && document.body.classList.contains("keep-transitions"));
const pollIntervalMs = Math.max(
  15000,
  Number(window.PADRES_BOARD_POLL_INTERVAL_MS || (lowPowerMode ? 60000 : 30000))
);
const visualTemplateUrl = "/static/visual-scene-templates.json";
const visualTemplatePollIntervalMs = Math.max(
  4000,
  Number(window.PADRES_BOARD_TEMPLATE_POLL_INTERVAL_MS || (lowPowerMode ? 15000 : 4000))
);
const slideFontScale = Math.max(0.85, Math.min(2, Number(window.PADRES_BOARD_FONT_SCALE || (lowPowerMode ? 1.18 : 1))));
const lowPowerTemplateSlideTtlMs = Math.max(
  10000,
  Number(window.PADRES_BOARD_TEMPLATE_SLIDE_TTL_MS || 180000)
);
const templateApiErrorRetryMs = Math.max(
  5000,
  Number(window.PADRES_BOARD_TEMPLATE_API_ERROR_RETRY_MS || (lowPowerMode ? 20000 : 8000))
);

const priorStatePollHandle = Number(window.__PADRES_BOARD_STATE_POLL_HANDLE);
if (Number.isFinite(priorStatePollHandle) && priorStatePollHandle > 0) {
  window.clearInterval(priorStatePollHandle);
}

const priorTemplatePollHandle = Number(window.__PADRES_BOARD_TEMPLATE_POLL_HANDLE);
if (Number.isFinite(priorTemplatePollHandle) && priorTemplatePollHandle > 0) {
  window.clearInterval(priorTemplatePollHandle);
}

const video = document.getElementById("mainVideo");
const noVideoMessage = document.getElementById("noVideoMessage");
const modeBadge = document.getElementById("modeBadge");

const awayName = document.getElementById("awayName");
const awayAbbrev = document.getElementById("awayAbbrev");
const homeName = document.getElementById("homeName");
const homeAbbrev = document.getElementById("homeAbbrev");

const awayRuns = document.getElementById("awayRuns");
const homeRuns = document.getElementById("homeRuns");
const awayStats = document.getElementById("awayStats");
const homeStats = document.getElementById("homeStats");

const statusLine = document.getElementById("statusLine");
const detailLine = document.getElementById("detailLine");
const clipTitle = document.getElementById("clipTitle");
const clipMeta = document.getElementById("clipMeta");
const updateStamp = document.getElementById("updateStamp");
const slideName = document.getElementById("slideName");
const slideContainer = document.getElementById("slideContainer");
const slidesRenderViewport = document.getElementById("slidesRenderViewport");
const liveGameHighlightPanel = document.getElementById("liveGameHighlightPanel");
const liveGameHighlightTitle = document.getElementById("liveGameHighlightTitle");
const liveGameHighlightMeta = document.getElementById("liveGameHighlightMeta");

if (document.body instanceof HTMLElement) {
  document.body.style.setProperty("--slides-font-scale", String(slideFontScale));
}

function updateSlidesRenderViewportScale() {
  if (!(document.body instanceof HTMLElement)) {
    return;
  }
  if (!(slidesRenderViewport instanceof HTMLElement)) {
    return;
  }
  if (!document.body.classList.contains("slides-only-page")) {
    return;
  }

  const computed = window.getComputedStyle(document.body);
  const configuredWidth = Number(window.PADRES_BOARD_TARGET_WIDTH);
  const configuredHeight = Number(window.PADRES_BOARD_TARGET_HEIGHT);
  const renderWidth = Math.max(
    1,
    Number.isFinite(configuredWidth)
      ? configuredWidth
      : Number.parseFloat(computed.getPropertyValue("--slides-render-width")) || 1280
  );
  const renderHeight = Math.max(
    1,
    Number.isFinite(configuredHeight)
      ? configuredHeight
      : Number.parseFloat(computed.getPropertyValue("--slides-render-height")) || 720
  );
  const viewportWidth = Math.max(1, window.innerWidth || document.documentElement.clientWidth || renderWidth);
  const viewportHeight = Math.max(1, window.innerHeight || document.documentElement.clientHeight || renderHeight);

  document.body.style.setProperty("--slides-render-width", String(renderWidth));
  document.body.style.setProperty("--slides-render-height", String(renderHeight));

  const allowUpscale = Boolean(window.PADRES_BOARD_ALLOW_UPSCALE);
  const baseScale = Math.min(viewportWidth / renderWidth, viewportHeight / renderHeight);
  const scale = Math.max(0.1, allowUpscale ? baseScale : Math.min(baseScale, 1));

  document.body.style.setProperty("--slides-render-scale", String(scale));
}

if (document.body instanceof HTMLElement && slidesRenderViewport instanceof HTMLElement) {
  updateSlidesRenderViewportScale();
  window.addEventListener("resize", updateSlidesRenderViewportScale, { passive: true });
  window.addEventListener("orientationchange", updateSlidesRenderViewportScale, { passive: true });
}

let hlsInstance = null;
let activeMode = "";
let currentVideoKey = "";
let activeHighlights = [];
let activeHighlightsSignature = "";
let baseHighlights = [];
let baseHighlightsSignature = "";
let highlightIndex = 0;
let kioskPayload = null;
let currentTeamName = "Padres";
let lastScoreboard = null;
let previousLiveStatusSnapshot = null;

let slideDefinitions = [];
let slideIndex = 0;
let slideTimer = null;
let slideSwapTimer = null;
let activeSlideType = "";
let activeSlidePayload = null;
let kioskLayoutSignature = "";
let currentSlideOutMs = 650;
let latestStatePayload = null;
let templateRuntimeDataBySlide = {};
let templateRuntimeFetchBySlide = {};

let sceneTimers = [];
let visualTemplatePollHandle = null;
let statePollHandle = null;
let visualSceneSignature = "";
let refreshStatePromise = null;
let visualSceneConfig = {
  enabled: false,
  slideTransitionMs: 650,
  elementDefaults: {
    enter: { effect: "slide-up", durationMs: 700, delayMs: 0, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
    exit: { effect: "fade", durationMs: 460, delayMs: 0, easing: "ease" },
  },
  templates: {},
};

const fallbackSlides = [{ id: "status", type: "status", title: "Game Pulse", durationSeconds: 10, payload: {} }];

function destroyHls() {
  if (hlsInstance) {
    hlsInstance.destroy();
    hlsInstance = null;
  }
}

function isM3u8(url) {
  return typeof url === "string" && url.toLowerCase().includes(".m3u8");
}

function playSource(url) {
  if (!url) {
    return;
  }

  destroyHls();

  if (window.Hls && window.Hls.isSupported() && isM3u8(url)) {
    hlsInstance = new window.Hls({
      enableWorker: true,
      lowLatencyMode: false,
    });
    hlsInstance.loadSource(url);
    hlsInstance.attachMedia(video);
  } else {
    video.src = url;
  }

  video
    .play()
    .catch(() => {
      video.muted = true;
      return video.play();
    })
    .catch(() => {
      // Browser autoplay policy can still block playback until user interaction.
    });
}

function formatTimestamp(isoString) {
  if (!isoString) {
    return "";
  }
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) {
    return isoString;
  }
  return date.toLocaleString();
}

function escapeHtml(rawValue) {
  const value = String(rawValue ?? "");
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function modeText(mode) {
  if (mode === "live_stream") {
    return "Live Game Stream";
  }
  if (mode === "highlights_with_scoreboard") {
    return "Live Scoreboard + Highlights";
  }
  return "Highlights Loop";
}

function syncLiveGameHighlightPanel() {
  if (!(document.body instanceof HTMLElement)) {
    return;
  }

  const isSlidesOnly = document.body.classList.contains("slides-only-page");
  const shouldShow = isSlidesOnly && activeSlideType === "live_game_status";
  document.body.classList.toggle("live-game-status-active", shouldShow);

  if (liveGameHighlightPanel instanceof HTMLElement) {
    liveGameHighlightPanel.classList.toggle("hidden", !shouldShow);
  }

  if (!shouldShow) {
    return;
  }

  if (liveGameHighlightTitle instanceof HTMLElement) {
    const text = String(clipTitle?.textContent || "").trim();
    liveGameHighlightTitle.textContent = text || "Live game highlights";
  }

  if (liveGameHighlightMeta instanceof HTMLElement) {
    const text = String(clipMeta?.textContent || "").trim();
    liveGameHighlightMeta.textContent = text || "Waiting for clips...";
  }
}

function renderScoreboard(scoreboard) {
  lastScoreboard = scoreboard;

  if (!scoreboard) {
    awayName.textContent = "No game";
    awayAbbrev.textContent = "---";
    homeName.textContent = "Padres";
    homeAbbrev.textContent = "SD";
    awayRuns.textContent = "0";
    homeRuns.textContent = "0";
    awayStats.textContent = "H 0 | E 0";
    homeStats.textContent = "H 0 | E 0";
    statusLine.textContent = "No Padres game currently active";
    detailLine.textContent = "Highlights are playing from recent games.";
    return;
  }

  awayName.textContent = scoreboard.away.name || "Away";
  awayAbbrev.textContent = scoreboard.away.abbrev || "AWY";
  homeName.textContent = scoreboard.home.name || "Home";
  homeAbbrev.textContent = scoreboard.home.abbrev || "HME";

  awayRuns.textContent = String(scoreboard.away.runs || 0);
  homeRuns.textContent = String(scoreboard.home.runs || 0);
  awayStats.textContent = `H ${scoreboard.away.hits || 0} | E ${scoreboard.away.errors || 0}`;
  homeStats.textContent = `H ${scoreboard.home.hits || 0} | E ${scoreboard.home.errors || 0}`;

  const statusText = scoreboard.status?.detailed || scoreboard.status?.abstract || "Game status unavailable";
  const inningState = scoreboard.inning?.state || "";
  const inningNumber = scoreboard.inning?.number || 0;
  const count = scoreboard.count || { balls: 0, strikes: 0, outs: 0 };

  statusLine.textContent = statusText;
  detailLine.textContent = `${inningState} ${inningNumber > 0 ? inningNumber : ""}  |  B ${count.balls} S ${count.strikes} O ${count.outs}`.trim();
}

function parseHighlightTimestamp(rawValue) {
  if (!rawValue) {
    return 0;
  }

  const parsed = new Date(rawValue);
  if (Number.isNaN(parsed.getTime())) {
    return 0;
  }
  return parsed.getTime();
}

function normalizeHighlightQueue(items) {
  const source = Array.isArray(items) ? items : [];
  const seen = new Set();
  const normalized = [];

  source.forEach((clip, index) => {
    if (!clip || !clip.url) {
      return;
    }

    const dedupeKey = `${clip.id || ""}|${clip.url || ""}`;
    if (seen.has(dedupeKey)) {
      return;
    }
    seen.add(dedupeKey);

    normalized.push({
      clip,
      sourceIndex: index,
      publishedAtMs: parseHighlightTimestamp(clip.publishedAt),
    });
  });

  normalized.sort((left, right) => {
    if (left.publishedAtMs !== right.publishedAtMs) {
      return right.publishedAtMs - left.publishedAtMs;
    }
    return left.sourceIndex - right.sourceIndex;
  });

  return normalized.map((entry) => entry.clip);
}

function filterHighlightsByAgeHours(items, maxAgeHours) {
  const source = Array.isArray(items) ? items : [];
  const safeHours = Number(maxAgeHours || 0);
  if (!Number.isFinite(safeHours) || safeHours <= 0) {
    return source.slice();
  }

  const cutoffMs = Date.now() - safeHours * 60 * 60 * 1000;
  return source.filter((clip) => {
    const publishedAtMs = parseHighlightTimestamp(clip?.publishedAt);
    return publishedAtMs > 0 && publishedAtMs >= cutoffMs;
  });
}

function buildHighlightsSignature(items) {
  return items.map((item) => item.id || item.url).join("|");
}

function setBaseHighlights(items) {
  const normalized = normalizeHighlightQueue(items);
  const signature = buildHighlightsSignature(normalized);
  if (signature === baseHighlightsSignature) {
    return false;
  }

  baseHighlights = normalized.slice();
  baseHighlightsSignature = signature;
  return true;
}

function setActiveHighlights(items) {
  const normalized = normalizeHighlightQueue(items);
  const signature = buildHighlightsSignature(normalized);
  if (signature === activeHighlightsSignature) {
    return false;
  }

  activeHighlights = normalized.slice();
  activeHighlightsSignature = signature;
  highlightIndex = 0;
  return true;
}

function playNextHighlight() {
  if (!activeHighlights.length) {
    noVideoMessage.classList.remove("hidden");
    currentVideoKey = "";
    clipTitle.textContent = "No highlight clips available right now";
    clipMeta.textContent = "Waiting for MLB highlight content...";
    syncLiveGameHighlightPanel();
    return;
  }

  noVideoMessage.classList.add("hidden");

  const clip = activeHighlights[highlightIndex % activeHighlights.length];
  highlightIndex = (highlightIndex + 1) % activeHighlights.length;

  currentVideoKey = clip.url;
  clipTitle.textContent = clip.title || "Padres highlight";

  const metaParts = [];
  if (clip.duration) {
    metaParts.push(`Duration ${clip.duration}`);
  }
  if (clip.publishedAt) {
    metaParts.push(formatTimestamp(clip.publishedAt));
  }
  clipMeta.textContent = metaParts.join(" | ");

  playSource(clip.url);
  syncLiveGameHighlightPanel();
}

function updateModeBadge(mode) {
  modeBadge.textContent = modeText(mode);
}

function slideTitleForType(type) {
  if (type === "live_game_status") {
    return "Live Game Center";
  }
  if (type === "game_today") {
    return "Game Today";
  }
  if (type === "schedule_overview") {
    return "Upcoming Schedule";
  }
  if (type === "upcoming_weather") {
    return "Next Game Weather";
  }
  if (type === "team_hitting_leaders") {
    return "Hitting Leaders";
  }
  if (type === "team_pitching_leaders") {
    return "Pitching Leaders";
  }
  if (type === "player_breakdown") {
    return "Player Breakdown";
  }
  if (type === "previous_game_pbp") {
    return "Previous Game Story";
  }
  if (type === "featured_player") {
    return "Featured Player Breakdown";
  }
  return "Game Pulse";
}

function normalizeSlides(kiosk) {
  const generatedSlides = Array.isArray(kiosk?.slides) ? kiosk.slides : [];
  const layout = kiosk?.layout || {};

  if (layout && layout.enabled === false && !generatedSlides.length) {
    return [];
  }

  let source = fallbackSlides;
  if (generatedSlides.length) {
    source = generatedSlides;
  } else if (Array.isArray(layout?.slides) && layout.slides.length) {
    source = layout.slides;
  }

  const defaultDuration = Math.max(5, Number(layout?.rotationSeconds || 14));

  return source
    .map((slide, index) => {
      const type = String(slide?.type || "").trim();
      if (!type) {
        return null;
      }

      const durationSeconds = Math.max(5, Number(slide.durationSeconds || defaultDuration));
      const payload = typeof slide?.payload === "object" && slide.payload ? slide.payload : {};

      return {
        id: String(slide.id || `slide-${index + 1}`),
        type,
        title: String(slide.title || slideTitleForType(type)),
        durationSeconds,
        payload,
      };
    })
    .filter((slide) => slide !== null);
}

function buildSlideLayoutSignature(slides) {
  const normalized = Array.isArray(slides)
    ? slides.map((slide) => ({
        id: String(slide?.id || ""),
        type: String(slide?.type || ""),
        title: String(slide?.title || ""),
        durationSeconds: Number(slide?.durationSeconds || 0),
      }))
    : [];
  return JSON.stringify(normalized);
}

function clearSceneTimers() {
  for (const timer of sceneTimers) {
    window.clearTimeout(timer);
  }
  sceneTimers = [];
}

function queueSceneTimer(callback, delayMs) {
  const timer = window.setTimeout(callback, Math.max(0, Number(delayMs || 0)));
  sceneTimers.push(timer);
}

function parseJsonSafe(rawValue, fallbackValue) {
  try {
    return JSON.parse(rawValue);
  } catch {
    return fallbackValue;
  }
}

function normalizeEffectName(rawEffect, fallbackEffect) {
  const value = String(rawEffect || "").trim().toLowerCase();
  if (["fade", "slide-up", "slide-down", "slide-left", "slide-right", "zoom"].includes(value)) {
    return value;
  }
  if (value === "fade-up") {
    return "slide-up";
  }
  if (value === "slide") {
    return "slide-left";
  }
  return fallbackEffect;
}

function normalizeMotion(rawMotion, fallbackMotion) {
  const source = typeof rawMotion === "object" && rawMotion ? rawMotion : {};
  const fallback = typeof fallbackMotion === "object" && fallbackMotion ? fallbackMotion : {};

  return {
    effect: normalizeEffectName(source.effect, normalizeEffectName(fallback.effect, "fade")),
    durationMs: Math.max(120, Number(source.durationMs ?? fallback.durationMs ?? 600)),
    delayMs: Math.max(0, Number(source.delayMs ?? fallback.delayMs ?? 0)),
    easing: String(source.easing || fallback.easing || "ease"),
  };
}

function normalizeVisualSceneConfig(rawConfig) {
  const source = typeof rawConfig === "object" && rawConfig ? rawConfig : {};

  const defaults = {
    enter: normalizeMotion(source.elementDefaults?.enter, {
      effect: "slide-up",
      durationMs: 700,
      delayMs: 0,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
    }),
    exit: normalizeMotion(source.elementDefaults?.exit, {
      effect: "fade",
      durationMs: 460,
      delayMs: 0,
      easing: "ease",
    }),
  };

  const templates = {};
  if (Array.isArray(source.templates)) {
    for (const row of source.templates) {
      if (!row || typeof row !== "object") {
        continue;
      }
      const key = String(row.match || row.type || row.id || "").trim();
      if (!key) {
        continue;
      }
      templates[key] = row;
    }
  } else if (source.templates && typeof source.templates === "object") {
    for (const [key, value] of Object.entries(source.templates)) {
      if (!value || typeof value !== "object") {
        continue;
      }
      templates[key] = value;
    }
  }

  return {
    enabled: Boolean(source.enabled),
    slideTransitionMs: Math.max(200, Number(source.slideTransitionMs || 650)),
    elementDefaults: defaults,
    templates,
  };
}

async function refreshVisualSceneConfig(force = false) {
  try {
    const token = force ? Date.now() : Math.floor(Date.now() / visualTemplatePollIntervalMs);
    const response = await fetch(`${visualTemplateUrl}?t=${token}`, { cache: "no-store" });
    if (!response.ok) {
      return false;
    }

    const rawText = await response.text();
    const signature = rawText.trim();
    if (!signature) {
      return false;
    }

    if (!force && signature === visualSceneSignature) {
      return false;
    }

    visualSceneSignature = signature;
    visualSceneConfig = normalizeVisualSceneConfig(parseJsonSafe(rawText, {}));
    templateRuntimeDataBySlide = {};
    return true;
  } catch {
    return false;
  }
}

function startVisualTemplatePolling() {
  if (visualTemplatePollHandle) {
    window.clearInterval(visualTemplatePollHandle);
  }

  visualTemplatePollHandle = window.setInterval(async () => {
    const changed = await refreshVisualSceneConfig(false);
    if (changed && slideDefinitions.length) {
      renderActiveSlide(false);
    }
  }, visualTemplatePollIntervalMs);

  window.__PADRES_BOARD_TEMPLATE_POLL_HANDLE = visualTemplatePollHandle;
}

function startStatePolling() {
  if (statePollHandle) {
    window.clearInterval(statePollHandle);
  }

  statePollHandle = window.setInterval(() => {
    refreshState();
  }, pollIntervalMs);

  window.__PADRES_BOARD_STATE_POLL_HANDLE = statePollHandle;
}

function getPathValue(source, path) {
  if (!path || typeof path !== "string") {
    return undefined;
  }

  const keys = path
    .split(".")
    .map((segment) => segment.trim())
    .filter(Boolean);

  let current = source;
  for (const key of keys) {
    if (current == null || typeof current !== "object") {
      return undefined;
    }
    current = current[key];
  }

  return current;
}

function resolveExpression(expression, context) {
  const token = String(expression || "").trim();
  if (!token) {
    return "";
  }

  if (token.startsWith("payload.")) {
    return getPathValue(context.payload, token.slice("payload.".length));
  }
  if (token === "payload") {
    return context.payload;
  }

  if (token.startsWith("slide.")) {
    return getPathValue(context.slide, token.slice("slide.".length));
  }
  if (token === "slide") {
    return context.slide;
  }

  if (token.startsWith("kiosk.")) {
    return getPathValue(context.kiosk, token.slice("kiosk.".length));
  }
  if (token === "kiosk") {
    return context.kiosk;
  }

  if (token.startsWith("state.")) {
    return getPathValue(context.state, token.slice("state.".length));
  }
  if (token === "state") {
    return context.state;
  }

  if (token.startsWith("item.")) {
    return getPathValue(context.item, token.slice("item.".length));
  }
  if (token === "item") {
    return context.item;
  }

  if (token === "index") {
    return context.index;
  }

  return getPathValue(context, token);
}

function parseTemplateToken(rawExpression) {
  const segments = String(rawExpression ?? "")
    .split("|")
    .map((segment) => segment.trim())
    .filter(Boolean);

  const expression = segments.shift() || "";
  const filters = segments.map((segment) => {
    const separatorIndex = segment.indexOf(":");
    if (separatorIndex <= 0) {
      return { name: segment.toLowerCase(), arg: "" };
    }

    return {
      name: segment.slice(0, separatorIndex).trim().toLowerCase(),
      arg: segment.slice(separatorIndex + 1).trim(),
    };
  });

  return {
    expression,
    filters,
  };
}

function parseDateLikeValue(rawValue) {
  if (rawValue instanceof Date && !Number.isNaN(rawValue.getTime())) {
    return rawValue;
  }

  if (typeof rawValue === "number" && Number.isFinite(rawValue)) {
    const numeric = Math.abs(rawValue) < 1e12 ? rawValue * 1000 : rawValue;
    const fromNumber = new Date(numeric);
    return Number.isNaN(fromNumber.getTime()) ? null : fromNumber;
  }

  const text = String(rawValue ?? "").trim();
  if (!text) {
    return null;
  }

  const dateOnlyMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnlyMatch) {
    const year = Number(dateOnlyMatch[1]);
    const month = Number(dateOnlyMatch[2]);
    const day = Number(dateOnlyMatch[3]);
    const dateOnly = new Date(year, month - 1, day, 12, 0, 0, 0);
    return Number.isNaN(dateOnly.getTime()) ? null : dateOnly;
  }

  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateTemplateValue(rawValue, formatOption = "") {
  const parsedDate = parseDateLikeValue(rawValue);
  if (!parsedDate) {
    return rawValue === undefined || rawValue === null ? "" : String(rawValue);
  }

  const option = String(formatOption || "medium").trim().toLowerCase();
  if (option === "iso" || option === "yyyy-mm-dd") {
    const year = parsedDate.getFullYear();
    const month = String(parsedDate.getMonth() + 1).padStart(2, "0");
    const day = String(parsedDate.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  const formatters = {
    short: { month: "short", day: "numeric" },
    medium: { month: "short", day: "numeric", year: "numeric" },
    long: { month: "long", day: "numeric", year: "numeric" },
    weekday: { weekday: "short", month: "short", day: "numeric" },
    full: { weekday: "long", month: "long", day: "numeric", year: "numeric" },
    time: { hour: "numeric", minute: "2-digit" },
    datetime: { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" },
  };

  const formatter = formatters[option] || formatters.medium;
  return new Intl.DateTimeFormat(undefined, formatter).format(parsedDate);
}

function formatPercentTemplateValue(rawValue, formatOption = "") {
  const text = String(rawValue ?? "").trim();
  if (!text) {
    return "";
  }

  const numericText = text.endsWith("%") ? text.slice(0, -1).trim() : text;
  const numericValue = Number(numericText);
  if (!Number.isFinite(numericValue)) {
    return rawValue === undefined || rawValue === null ? "" : String(rawValue);
  }

  let decimals = Number.parseInt(String(formatOption || "").trim(), 10);
  if (!Number.isFinite(decimals)) {
    decimals = 1;
  }
  decimals = Math.max(0, Math.min(4, decimals));

  const percentValue = Math.abs(numericValue) <= 1 ? numericValue * 100 : numericValue;
  return `${percentValue.toFixed(decimals)}%`;
}

function applyTemplateFilter(value, filterName, filterArg) {
  if (filterName === "date") {
    return formatDateTemplateValue(value, filterArg);
  }

  if (filterName === "percent" || filterName === "pct") {
    return formatPercentTemplateValue(value, filterArg);
  }

  if (filterName === "default" || filterName === "fallback") {
    const hasValue = !(value === undefined || value === null || String(value).trim() === "");
    return hasValue ? value : filterArg;
  }

  return value;
}

function interpolateTemplate(template, context) {
  const raw = String(template ?? "");
  return raw.replace(/\{\{\s*([^}]+)\s*\}\}/g, (_match, expression) => {
    const token = parseTemplateToken(expression);
    let value = resolveExpression(token.expression, context);
    for (const filter of token.filters) {
      value = applyTemplateFilter(value, filter.name, filter.arg);
    }
    if (value === undefined || value === null) {
      return "";
    }
    return String(value);
  });
}

function resolveInterpolatedValue(value, context) {
  if (typeof value !== "string") {
    return value;
  }
  if (!value.includes("{{")) {
    return value;
  }
  return interpolateTemplate(value, context);
}

const inlineImageTokenPattern = /\{\{\s*img\s*:\s*([^}]+?)\s*\}\}/gi;

function parseInlineImageTokenSpec(rawSpec) {
  const text = String(rawSpec ?? "").trim();
  if (!text) {
    return {
      expression: "",
      width: "",
      height: "",
      zoom: "",
      offsetX: "",
      offsetY: "",
      mode: "",
    };
  }

  const parts = text
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean);

  const expression = parts.shift() || "";
  let squareSize = "";
  let width = "";
  let height = "";
  let zoom = "";
  let offsetX = "";
  let offsetY = "";
  let mode = "";

  for (const part of parts) {
    const loweredPart = part.toLowerCase();
    if (loweredPart === "cap") {
      mode = "cap";
      continue;
    }

    const separatorIndex = part.indexOf("=");
    if (separatorIndex <= 0) {
      if (!squareSize) {
        squareSize = part;
      }
      continue;
    }

    const key = part.slice(0, separatorIndex).trim().toLowerCase();
    const value = part.slice(separatorIndex + 1).trim();
    if (!value) {
      continue;
    }

    if (key === "size" || key === "s") {
      squareSize = value;
      continue;
    }
    if (key === "width" || key === "w") {
      width = value;
      continue;
    }
    if (key === "height" || key === "h") {
      height = value;
      continue;
    }
    if (key === "zoom" || key === "z") {
      zoom = value;
      continue;
    }
    if (key === "x" || key === "dx" || key === "offsetx") {
      offsetX = value;
      continue;
    }
    if (key === "y" || key === "dy" || key === "offsety") {
      offsetY = value;
      continue;
    }
    if (key === "mode" || key === "m") {
      mode = value.toLowerCase();
    }
  }

  if (squareSize) {
    if (!width) {
      width = squareSize;
    }
    if (!height) {
      height = squareSize;
    }
  }

  return {
    expression,
    width,
    height,
    zoom,
    offsetX,
    offsetY,
    mode,
  };
}

function appendInlineTemplateContent(node, templateValue, context) {
  const rawTemplate = String(templateValue ?? "");
  inlineImageTokenPattern.lastIndex = 0;

  let cursor = 0;
  let hasImageToken = false;
  let match = inlineImageTokenPattern.exec(rawTemplate);

  while (match) {
    hasImageToken = true;

    const textChunk = rawTemplate.slice(cursor, match.index);
    if (textChunk) {
      const resolvedText = interpolateTemplate(textChunk, context);
      if (resolvedText) {
        node.appendChild(document.createTextNode(resolvedText));
      }
    }

    const imageToken = parseInlineImageTokenSpec(match[1]);
    const imageSource = resolveExpression(imageToken.expression, context);
    const sourceText = String(imageSource || "").trim();
    if (sourceText) {
      const image = document.createElement("img");
      image.classList.add("scene-inline-image");
      const looksLikeCapLogo = sourceText.includes("/team-cap-") || sourceText.includes("team-cap-on-");
      if (looksLikeCapLogo || imageToken.mode === "cap") {
        image.classList.add("scene-inline-image-cap");
      }
      image.src = sourceText;
      image.alt = "Inline image";
      image.loading = "eager";
      if (imageToken.width) {
        image.style.width = imageToken.width;
      }
      if (imageToken.height) {
        image.style.height = imageToken.height;
      }
      if (imageToken.zoom) {
        image.style.setProperty("--inline-image-zoom", imageToken.zoom);
      }
      if (imageToken.offsetX) {
        image.style.setProperty("--inline-image-offset-x", imageToken.offsetX);
      }
      if (imageToken.offsetY) {
        image.style.setProperty("--inline-image-offset-y", imageToken.offsetY);
      }
      node.appendChild(image);
    }

    cursor = match.index + match[0].length;
    match = inlineImageTokenPattern.exec(rawTemplate);
  }

  if (!hasImageToken) {
    node.textContent = interpolateTemplate(rawTemplate, context);
    return;
  }

  const tail = rawTemplate.slice(cursor);
  if (tail) {
    const resolvedTail = interpolateTemplate(tail, context);
    if (resolvedTail) {
      node.appendChild(document.createTextNode(resolvedTail));
    }
  }
}

function pruneTemplateRuntimeDataBySlide() {
  if (!slideDefinitions.length) {
    templateRuntimeDataBySlide = {};
    templateRuntimeFetchBySlide = {};
    return;
  }

  const validKeys = new Set(slideDefinitions.map((slide) => String(slide?.id || "")).filter(Boolean));
  for (const key of Object.keys(templateRuntimeDataBySlide)) {
    if (!validKeys.has(key)) {
      delete templateRuntimeDataBySlide[key];
    }
  }

  for (const key of Object.keys(templateRuntimeFetchBySlide)) {
    if (!validKeys.has(key)) {
      delete templateRuntimeFetchBySlide[key];
    }
  }
}

function buildVisualRuntimeContext(slide, template = null, payloadOverride = undefined, endpointData = null, statePayload = null) {
  const stateSnapshot = statePayload && typeof statePayload === "object" ? statePayload : latestStatePayload || {};
  const slidePayload = slide?.payload === undefined || slide?.payload === null ? {} : slide.payload;
  const endpointPayload = endpointData && endpointData.payload !== undefined ? endpointData.payload : null;
  const hasEndpoint = Boolean(String(template?.apiEndpoint || "").trim());

  const payload =
    payloadOverride !== undefined
      ? payloadOverride
      : hasEndpoint
        ? endpointPayload !== null && endpointPayload !== undefined
          ? endpointPayload
          : slidePayload
        : slidePayload;

  const resolvedPayload = payload === undefined || payload === null ? {} : payload;

  return {
    payload: resolvedPayload,
    slidePayload: resolvedPayload,
    slide,
    kiosk: stateSnapshot.kiosk || kioskPayload || {},
    state:
      Object.keys(stateSnapshot).length > 0
        ? stateSnapshot
        : {
            mode: activeMode,
            teamName: currentTeamName,
            generatedAtUtc: new Date().toISOString(),
          },
    scoreboard: stateSnapshot.scoreboard || lastScoreboard || {},
    external: endpointPayload !== null && endpointPayload !== undefined ? endpointPayload : {},
    vars: endpointData?.variables || {},
    endpoint: endpointData || null,
    item: null,
    index: 0,
  };
}

function getSlidesForTemplateRefresh() {
  if (!slideDefinitions.length) {
    return [];
  }

  if (!lowPowerMode) {
    return slideDefinitions;
  }

  const current = slideDefinitions[slideIndex % slideDefinitions.length];
  const next =
    slideDefinitions.length > 1
      ? slideDefinitions[(slideIndex + 1) % slideDefinitions.length]
      : null;

  const selected = [current, next].filter(Boolean);
  const seen = new Set();
  const deduped = [];
  for (const slide of selected) {
    const key = String(slide?.id || "").trim();
    if (!key || seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(slide);
  }
  return deduped;
}

function encodeEndpointQueryValue(rawValue) {
  const text = String(rawValue ?? "");
  try {
    return encodeURIComponent(decodeURIComponent(text));
  } catch {
    return encodeURIComponent(text);
  }
}

function sanitizeTemplateEndpoint(rawEndpoint) {
  const endpoint = String(rawEndpoint || "").trim();
  if (!endpoint) {
    return "";
  }

  const hashIndex = endpoint.indexOf("#");
  const hash = hashIndex >= 0 ? endpoint.slice(hashIndex) : "";
  const withoutHash = hashIndex >= 0 ? endpoint.slice(0, hashIndex) : endpoint;

  const queryIndex = withoutHash.indexOf("?");
  if (queryIndex < 0) {
    return `${withoutHash}${hash}`;
  }

  const base = withoutHash.slice(0, queryIndex);
  const rawQuery = withoutHash.slice(queryIndex + 1);
  if (!rawQuery) {
    return `${base}${hash}`;
  }

  const encodedPairs = rawQuery
    .split("&")
    .filter((pair) => pair.length > 0)
    .map((pair) => {
      const separatorIndex = pair.indexOf("=");
      if (separatorIndex < 0) {
        return encodeEndpointQueryValue(pair);
      }

      const key = pair.slice(0, separatorIndex);
      const value = pair.slice(separatorIndex + 1);
      return `${key}=${encodeEndpointQueryValue(value)}`;
    });

  if (!encodedPairs.length) {
    return `${base}${hash}`;
  }

  return `${base}?${encodedPairs.join("&")}${hash}`;
}

function buildTemplateEndpointRequest(template, context) {
  const endpointTemplate = String(template?.apiEndpoint || "").trim();
  if (!endpointTemplate) {
    return null;
  }

  const variableDefinitions =
    template?.apiVariables && typeof template.apiVariables === "object" && !Array.isArray(template.apiVariables)
      ? template.apiVariables
      : {};
  const resolvedVariables = {};
  for (const [key, value] of Object.entries(variableDefinitions)) {
    const resolved = resolveInterpolatedValue(value, context);
    resolvedVariables[key] = resolved === undefined || resolved === null ? "" : resolved;
  }

  const endpointContext = {
    ...context,
    vars: resolvedVariables,
    variables: resolvedVariables,
  };
  const endpoint = sanitizeTemplateEndpoint(resolveInterpolatedValue(endpointTemplate, endpointContext));
  if (!endpoint) {
    return null;
  }

  return {
    endpoint,
    variables: resolvedVariables,
  };
}

function hasFreshLowPowerTemplateData(entry) {
  if (!lowPowerMode || !entry || entry.error) {
    return false;
  }

  const fetchedAtMs = Number(entry.fetchedAtMs || 0);
  if (!Number.isFinite(fetchedAtMs) || fetchedAtMs <= 0) {
    return false;
  }

  return Date.now() - fetchedAtMs < lowPowerTemplateSlideTtlMs;
}

function shouldThrottleTemplateRetry(entry) {
  if (!entry || !entry.error) {
    return false;
  }

  const fetchedAtMs = Number(entry.fetchedAtMs || 0);
  if (!Number.isFinite(fetchedAtMs) || fetchedAtMs <= 0) {
    return false;
  }

  return Date.now() - fetchedAtMs < templateApiErrorRetryMs;
}

async function refreshTemplateRuntimeDataForSlide(slide, statePayload) {
  const slideKey = String(slide?.id || "").trim();
  if (!slideKey) {
    return false;
  }

  const template = getVisualTemplateForSlide(slide);
  if (!template || typeof template !== "object") {
    if (templateRuntimeDataBySlide[slideKey]) {
      delete templateRuntimeDataBySlide[slideKey];
      return true;
    }
    return false;
  }

  const baseContext = buildVisualRuntimeContext(slide, template, slide.payload || {}, null, statePayload);
  const requestConfig = buildTemplateEndpointRequest(template, baseContext);
  if (!requestConfig) {
    if (templateRuntimeDataBySlide[slideKey]) {
      delete templateRuntimeDataBySlide[slideKey];
      return true;
    }
    return false;
  }

  const previous = templateRuntimeDataBySlide[slideKey];
  if (hasFreshLowPowerTemplateData(previous) || shouldThrottleTemplateRetry(previous)) {
    return false;
  }

  const requestSignature = JSON.stringify({
    endpoint: requestConfig.endpoint,
    variables: requestConfig.variables,
  });

  const existingFetch = templateRuntimeFetchBySlide[slideKey];
  if (existingFetch && existingFetch.requestSignature === requestSignature) {
    return existingFetch.promise;
  }

  const fetchPromise = (async () => {
    let payload = null;
    let error = "";
    try {
      const response = await fetch(requestConfig.endpoint, { cache: "no-store" });
      payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = payload && typeof payload === "object" ? payload.detail || payload.error || "" : "";
        error = `Template API request failed (${response.status})${detail ? `: ${detail}` : ""}`;
        payload = null;
      }
    } catch (fetchError) {
      error = fetchError instanceof Error ? fetchError.message : "Template API request failed.";
      payload = null;
    }

    if (error) {
      if (payload === null && previous && Object.prototype.hasOwnProperty.call(previous, "payload")) {
        payload = previous.payload;
      }
      if (payload === null) {
        payload = slide?.payload && typeof slide.payload === "object" ? slide.payload : null;
      }
      error = `${error} [${requestConfig.endpoint}]`;
    }

    const signature = JSON.stringify({
      endpoint: requestConfig.endpoint,
      variables: requestConfig.variables,
      payload,
      error,
    });

    const latestEntry = templateRuntimeDataBySlide[slideKey];
    if (latestEntry?.signature === signature) {
      return false;
    }

    const nowMs = Date.now();
    templateRuntimeDataBySlide[slideKey] = {
      endpoint: requestConfig.endpoint,
      variables: requestConfig.variables,
      payload,
      error,
      fetchedAtUtc: new Date(nowMs).toISOString(),
      fetchedAtMs: nowMs,
      signature,
    };
    return true;
  })();

  templateRuntimeFetchBySlide[slideKey] = {
    requestSignature,
    promise: fetchPromise,
  };

  try {
    return await fetchPromise;
  } finally {
    const currentFetch = templateRuntimeFetchBySlide[slideKey];
    if (currentFetch && currentFetch.promise === fetchPromise) {
      delete templateRuntimeFetchBySlide[slideKey];
    }
  }
}

async function refreshTemplateRuntimeData(statePayload) {
  if (!slideDefinitions.length) {
    const hadCache = Object.keys(templateRuntimeDataBySlide).length > 0;
    templateRuntimeDataBySlide = {};
    templateRuntimeFetchBySlide = {};
    return hadCache;
  }

  pruneTemplateRuntimeDataBySlide();

  const refreshSlides = getSlidesForTemplateRefresh();
  if (!refreshSlides.length) {
    return false;
  }

  const updates = await Promise.all(refreshSlides.map((slide) => refreshTemplateRuntimeDataForSlide(slide, statePayload)));
  return updates.some(Boolean);
}

function applyInlineStyleObject(node, styleObject, context) {
  if (!styleObject || typeof styleObject !== "object") {
    return;
  }

  for (const [key, value] of Object.entries(styleObject)) {
    const cssValue = resolveInterpolatedValue(value, context);
    if (cssValue === undefined || cssValue === null || cssValue === "") {
      continue;
    }
    node.style.setProperty(key, String(cssValue));
  }
}

function applyElementBounds(node, element, context) {
  const left = resolveInterpolatedValue(element.x, context);
  const top = resolveInterpolatedValue(element.y, context);
  const width = resolveInterpolatedValue(element.w, context);
  const height = resolveInterpolatedValue(element.h, context);
  const right = resolveInterpolatedValue(element.right, context);
  const bottom = resolveInterpolatedValue(element.bottom, context);

  if (left !== undefined && left !== null && left !== "") {
    node.style.left = String(left);
  }
  if (top !== undefined && top !== null && top !== "") {
    node.style.top = String(top);
  }
  if (width !== undefined && width !== null && width !== "") {
    node.style.width = String(width);
  }
  if (height !== undefined && height !== null && height !== "") {
    node.style.height = String(height);
  }
  if (right !== undefined && right !== null && right !== "") {
    node.style.right = String(right);
  }
  if (bottom !== undefined && bottom !== null && bottom !== "") {
    node.style.bottom = String(bottom);
  }
}

function createSceneTextElement(element, context) {
  const tagName = String(element.tag || "p").toLowerCase();
  const safeTag = ["p", "h2", "h3", "div", "span"].includes(tagName) ? tagName : "p";
  const node = document.createElement(safeTag);

  if (element.textPath) {
    const value = resolveExpression(element.textPath, context);
    appendInlineTemplateContent(node, value === undefined || value === null ? "" : String(value), context);
  } else {
    appendInlineTemplateContent(node, element.text || "", context);
  }

  node.classList.add("scene-text");

  const textFontSize = toCssLength(resolveInterpolatedValue(element.textFontSize ?? element.fontSize, context));
  if (textFontSize) {
    node.style.fontSize = textFontSize;
  }

  const textColor = resolveInterpolatedValue(element.textColor ?? element.color, context);
  if (textColor !== undefined && textColor !== null && String(textColor).trim()) {
    node.style.color = String(textColor).trim();
  }

  const textFontWeight = resolveInterpolatedValue(element.textFontWeight ?? element.fontWeight, context);
  if (textFontWeight !== undefined && textFontWeight !== null && String(textFontWeight).trim()) {
    node.style.fontWeight = String(textFontWeight).trim();
  }

  return node;
}

function createSceneImageElement(element, context) {
  const node = document.createElement("img");
  const source = element.srcPath
    ? resolveExpression(element.srcPath, context)
    : resolveInterpolatedValue(element.src || "", context);

  node.classList.add("scene-image");
  const sourceText = String(source || "").trim();
  if (sourceText) {
    node.src = sourceText;
  } else {
    node.classList.add("scene-image-empty");
  }
  node.alt = interpolateTemplate(element.alt || "Slide image", context);
  node.loading = lowPowerMode ? "lazy" : "eager";
  return node;
}

function createSceneBarElement(element, context) {
  const wrapper = document.createElement("div");
  wrapper.classList.add("scene-bar");

  const rawValue = element.valuePath ? resolveExpression(element.valuePath, context) : resolveInterpolatedValue(element.value || 0, context);
  const numericValue = Math.max(0, Number(rawValue || 0));
  const maxValue = Math.max(1, Number(element.maxValue || 100));
  const percent = Math.max(0, Math.min(100, (numericValue / maxValue) * 100));

  const label = document.createElement("p");
  label.classList.add("scene-bar-label");
  label.textContent = interpolateTemplate(element.labelTemplate || "", context);

  const track = document.createElement("div");
  track.classList.add("scene-bar-track");

  const fill = document.createElement("div");
  fill.classList.add("scene-bar-fill");
  fill.style.width = `${percent.toFixed(1)}%`;

  track.appendChild(fill);
  if (label.textContent.trim()) {
    wrapper.appendChild(label);
  }
  wrapper.appendChild(track);

  return wrapper;
}

function isTruthyTemplateValue(rawValue) {
  if (typeof rawValue === "boolean") {
    return rawValue;
  }

  const text = String(rawValue ?? "").trim().toLowerCase();
  return Boolean(text) && !["0", "false", "no", "off", "null", "undefined", "nan"].includes(text);
}

function evaluateTemplateCondition(conditionValue, context) {
  if (typeof conditionValue === "string") {
    let expression = conditionValue.trim();
    if (!expression) {
      return false;
    }

    let invert = false;
    while (expression.startsWith("!")) {
      invert = !invert;
      expression = expression.slice(1).trim();
    }

    let resolvedValue;
    if (expression.includes("{{")) {
      resolvedValue = resolveInterpolatedValue(expression, context);
    } else if (/^(payload|slidePayload|slide|kiosk|state|scoreboard|external|vars|endpoint|item|index)(\.|$)/.test(expression)) {
      resolvedValue = resolveExpression(expression, context);
    } else {
      resolvedValue = expression;
    }

    const result = isTruthyTemplateValue(resolvedValue);
    return invert ? !result : result;
  }

  return isTruthyTemplateValue(conditionValue);
}

function toCssLength(rawValue) {
  const text = String(rawValue ?? "").trim();
  if (!text) {
    return "";
  }

  if (/^-?\d+(\.\d+)?$/.test(text)) {
    return `${text}px`;
  }

  return text;
}

function normalizeListRevealDirection(rawDirection) {
  const value = String(rawDirection || "").trim().toLowerCase();
  if (
    ["reverse", "desc", "descending", "from-end", "fromend", "bottom-up", "bottom-to-top", "countdown"].includes(
      value
    )
  ) {
    return "reverse";
  }
  return "forward";
}

function resolveSceneListRevealConfig(element, context) {
  if (lowPowerMode && !keepLowPowerTransitions) {
    return null;
  }

  const enabledValue = resolveInterpolatedValue(
    element?.continuousReveal ?? element?.sequentialReveal ?? element?.revealSequential,
    context
  );
  if (!isTruthyTemplateValue(enabledValue)) {
    return null;
  }

  const intervalRaw = resolveInterpolatedValue(element?.staggerMs ?? element?.revealIntervalMs ?? element?.revealStepMs ?? 620, context);
  const startDelayRaw = resolveInterpolatedValue(element?.revealStartDelayMs ?? 120, context);
  const fadeRaw = resolveInterpolatedValue(element?.revealFadeMs ?? 420, context);
  const directionRaw = resolveInterpolatedValue(element?.revealOrder ?? element?.revealDirection ?? "reverse", context);
  const highlightRaw = resolveInterpolatedValue(element?.revealHighlightColor, context);
  const settledRaw = resolveInterpolatedValue(element?.revealSettledColor ?? "#ffffff", context);
  const imageSelectorRaw = resolveInterpolatedValue(element?.revealImageSelector ?? element?.revealImageTarget ?? "", context);
  const imageFadeRaw = resolveInterpolatedValue(element?.revealImageFadeMs ?? 280, context);

  const highlightColor = highlightRaw !== undefined && highlightRaw !== null ? String(highlightRaw).trim() : "";
  const settledColor = settledRaw !== undefined && settledRaw !== null ? String(settledRaw).trim() : "#ffffff";
  const imageSelector = imageSelectorRaw !== undefined && imageSelectorRaw !== null ? String(imageSelectorRaw).trim() : "";

  return {
    direction: normalizeListRevealDirection(directionRaw),
    intervalMs: Math.max(120, Number(intervalRaw || 620)),
    startDelayMs: Math.max(0, Number(startDelayRaw || 0)),
    fadeMs: Math.max(120, Number(fadeRaw || 420)),
    highlightColor,
    settledColor: settledColor || "#ffffff",
    imageSelector,
    imagePath: String(element?.revealImagePath || "").trim(),
    imageAltTemplate: String(element?.revealImageAltTemplate || "").trim(),
    imageFadeMs: Math.max(120, Number(imageFadeRaw || 280)),
  };
}

function orderListRevealRows(rows, direction) {
  const ordered = Array.isArray(rows) ? rows.slice() : [];
  if (direction === "reverse") {
    ordered.reverse();
  }
  return ordered;
}

function resolveSceneRevealValue(rawValue, rowContext) {
  const text = String(rawValue || "").trim();
  if (!text) {
    return "";
  }

  if (text.includes("{{")) {
    const resolved = resolveInterpolatedValue(text, rowContext);
    return String(resolved || "").trim();
  }

  const resolved = resolveExpression(text, rowContext);
  return String(resolved || "").trim();
}

function ensureSceneRevealImageLayers(listReveal) {
  if (!listReveal || listReveal.imageLayersReady) {
    return;
  }
  listReveal.imageLayersReady = true;

  const selector = String(listReveal.imageSelector || "").trim();
  if (!selector) {
    return;
  }

  const sceneRoot = listReveal.sceneRoot;
  if (!sceneRoot || typeof sceneRoot.querySelector !== "function") {
    return;
  }

  const anchor = sceneRoot.querySelector(selector);
  if (!(anchor instanceof HTMLImageElement) || !(anchor.parentElement instanceof HTMLElement)) {
    return;
  }

  const entries = Array.isArray(listReveal.entries) ? listReveal.entries : [];
  if (!entries.length) {
    return;
  }

  const fadeMs = Math.max(120, Number(listReveal.imageFadeMs || 280));
  const parent = anchor.parentElement;
  const insertionPoint = anchor.nextSibling;
  let layerMap = anchor.__sceneRevealLayerMap;
  if (!(layerMap instanceof Map)) {
    layerMap = new Map();
    anchor.__sceneRevealLayerMap = layerMap;
  }

  const anchorBounds = {
    left: anchor.style.left || "",
    top: anchor.style.top || "",
    right: anchor.style.right || "",
    bottom: anchor.style.bottom || "",
    width: anchor.style.width || "",
    height: anchor.style.height || "",
    zIndex: anchor.style.zIndex || "",
  };
  for (const entry of entries) {
    const imageSource = String(entry?.imageSrc || "").trim();
    if (!imageSource) {
      continue;
    }

    let layer = layerMap.get(imageSource);
    if (!(layer instanceof HTMLImageElement)) {
      layer = document.createElement("img");
      layer.classList.add("scene-image", "scene-reveal-image-layer");
      layer.src = imageSource;
      layer.loading = "eager";
      layer.style.position = "absolute";
      if (anchorBounds.left) {
        layer.style.left = anchorBounds.left;
      }
      if (anchorBounds.top) {
        layer.style.top = anchorBounds.top;
      }
      if (anchorBounds.right) {
        layer.style.right = anchorBounds.right;
      }
      if (anchorBounds.bottom) {
        layer.style.bottom = anchorBounds.bottom;
      }
      if (anchorBounds.width) {
        layer.style.width = anchorBounds.width;
      }
      if (anchorBounds.height) {
        layer.style.height = anchorBounds.height;
      }
      if (anchorBounds.zIndex) {
        layer.style.zIndex = anchorBounds.zIndex;
      }
      layer.style.opacity = "0";
      layer.style.transition = `opacity ${fadeMs}ms ease-in-out`;
      layer.style.pointerEvents = "none";
      layer.style.willChange = "opacity";

      if (insertionPoint) {
        parent.insertBefore(layer, insertionPoint);
      } else {
        parent.appendChild(layer);
      }

      layerMap.set(imageSource, layer);
    }

    const imageAlt = String(entry?.imageAlt || anchor.alt || "Player headshot").trim();
    if (imageAlt && (!layer.alt || layer.alt === "Player headshot")) {
      layer.alt = imageAlt;
    }

    entry.imageLayer = layer;
  }

  if (layerMap.size > 0) {
    anchor.classList.add("scene-reveal-image-anchor");
    anchor.style.opacity = "0";
    anchor.style.pointerEvents = "none";
    listReveal.imageAnchor = anchor;
    listReveal.imageLayerMap = layerMap;
  }
}

function setSceneRevealActiveImageLayer(listReveal, revealEntry) {
  ensureSceneRevealImageLayers(listReveal);
  const layerMap = listReveal?.imageLayerMap;
  if (!(layerMap instanceof Map) || layerMap.size === 0) {
    return false;
  }

  for (const layer of layerMap.values()) {
    if (layer instanceof HTMLImageElement) {
      layer.style.opacity = "0";
    }
  }

  const activeLayer = revealEntry?.imageLayer;
  if (activeLayer instanceof HTMLImageElement) {
    activeLayer.style.opacity = "1";
  }

  return true;
}

function updateSceneRevealTargetImage(listReveal, revealEntry) {
  if (!listReveal || !revealEntry) {
    return;
  }

  if (setSceneRevealActiveImageLayer(listReveal, revealEntry)) {
    return;
  }

  const selector = String(listReveal.imageSelector || "").trim();
  if (!selector) {
    return;
  }

  const sceneRoot = listReveal.sceneRoot;
  if (!sceneRoot || typeof sceneRoot.querySelector !== "function") {
    return;
  }

  const target = sceneRoot.querySelector(selector);
  if (!(target instanceof HTMLImageElement)) {
    return;
  }

  const nextSource = String(revealEntry.imageSrc || "").trim();
  if (!nextSource) {
    return;
  }

  const nextAlt = String(revealEntry.imageAlt || "").trim();
  if (target.dataset.revealSrc === nextSource) {
    if (nextAlt) {
      target.alt = nextAlt;
    }
    return;
  }

  const fadeMs = Math.max(120, Number(listReveal.imageFadeMs || 280));
  const halfFadeMs = Math.max(80, Math.round(fadeMs * 0.5));
  target.style.transition = `opacity ${halfFadeMs}ms ease`;
  target.style.opacity = "0.14";

  queueSceneTimer(() => {
    target.src = nextSource;
    target.dataset.revealSrc = nextSource;
    if (nextAlt) {
      target.alt = nextAlt;
    }
    target.style.opacity = "1";
  }, halfFadeMs);
}

function triggerSceneListReveal(listReveal, baseDelayMs = 0) {
  const sourceEntries = Array.isArray(listReveal?.entries)
    ? listReveal.entries
    : Array.isArray(listReveal?.rows)
      ? listReveal.rows.map((rowNode) => ({ node: rowNode }))
      : [];
  if (!sourceEntries.length) {
    return;
  }

  const orderedEntries = orderListRevealRows(sourceEntries, listReveal.direction);
  let previousEntry = null;

  orderedEntries.forEach((entry, stepIndex) => {
    const rowNode = entry?.node;
    if (!rowNode) {
      return;
    }
    const triggerDelay = Math.max(0, Number(baseDelayMs || 0)) + listReveal.startDelayMs + stepIndex * listReveal.intervalMs;
    queueSceneTimer(() => {
      if (previousEntry && previousEntry.node && previousEntry.node !== rowNode) {
        previousEntry.node.classList.remove("scene-list-item-reveal-active");
        previousEntry.node.classList.add("scene-list-item-reveal-complete");
      }

      rowNode.classList.remove("scene-list-item-reveal-pending", "scene-list-item-reveal-complete");
      rowNode.classList.add("scene-list-item-reveal-visible", "scene-list-item-reveal-active");
      previousEntry = entry;
      updateSceneRevealTargetImage(listReveal, entry);
    }, triggerDelay);
  });
}

function createSceneListElement(element, context) {
  const kind = String(element.kind || "list").toLowerCase();
  const isGrid = kind === "grid";
  const revealConfig = resolveSceneListRevealConfig(element, context);
  const revealEntries = [];

  const wrapper = document.createElement("div");
  wrapper.classList.add("scene-collection");

  const panelValue =
    element.containerPanel !== undefined
      ? resolveInterpolatedValue(element.containerPanel, context)
      : resolveInterpolatedValue(element.showContainerPanel, context);
  if (isTruthyTemplateValue(panelValue)) {
    wrapper.classList.add("scene-collection-panel");
  }

  const titleTemplate = element.titleTemplate !== undefined ? element.titleTemplate : element.title;
  const titleText = titleTemplate ? interpolateTemplate(titleTemplate, context).trim() : "";
  if (titleText) {
    wrapper.classList.add("scene-collection-with-title");
    const title = document.createElement("p");
    title.classList.add("scene-collection-title");
    title.textContent = titleText;

    const collectionTitleFontSize = toCssLength(resolveInterpolatedValue(element.titleFontSize, context));
    if (collectionTitleFontSize) {
      title.style.fontSize = collectionTitleFontSize;
    }

    const collectionTitleColor = resolveInterpolatedValue(element.titleColor, context);
    if (collectionTitleColor !== undefined && collectionTitleColor !== null && String(collectionTitleColor).trim()) {
      title.style.color = String(collectionTitleColor).trim();
    }

    const collectionTitleWeight = resolveInterpolatedValue(element.titleFontWeight, context);
    if (collectionTitleWeight !== undefined && collectionTitleWeight !== null && String(collectionTitleWeight).trim()) {
      title.style.fontWeight = String(collectionTitleWeight).trim();
    }

    wrapper.appendChild(title);
  }

  const itemsNode = document.createElement("div");
  itemsNode.classList.add(isGrid ? "scene-grid" : "scene-list");
  if (isGrid) {
    const resolvedColumns = resolveInterpolatedValue(element.columns ?? element.gridColumns ?? 2, context);
    const parsedColumns = Number(resolvedColumns || 2);
    const columns = Number.isFinite(parsedColumns) && parsedColumns > 0 ? parsedColumns : 2;
    itemsNode.style.setProperty("--scene-grid-columns", String(columns));
  }

  const gridGapValue = toCssLength(resolveInterpolatedValue(element.gridGap ?? element.gap, context));
  if (gridGapValue) {
    itemsNode.style.gap = gridGapValue;
  }

  const alignXValue = String(
    resolveInterpolatedValue(element.gridAlignX ?? element.listAlignX ?? element.justifyItems, context) ?? ""
  ).trim();
  if (alignXValue) {
    itemsNode.style.justifyItems = alignXValue;
  }

  const alignYValue = String(
    resolveInterpolatedValue(element.gridAlignY ?? element.listAlignY ?? element.alignItems, context) ?? ""
  ).trim();
  if (alignYValue) {
    itemsNode.style.alignItems = alignYValue;
  }
  wrapper.appendChild(itemsNode);

  const configuredItems = Array.isArray(element.items) ? element.items : null;
  const rawItems = configuredItems !== null ? configuredItems : element.itemsPath ? resolveExpression(element.itemsPath, context) : [];
  const items = Array.isArray(rawItems) ? rawItems : [];
  const maxItems = Math.max(1, Number(element.maxItems || items.length || 1));

  const selected = [];
  for (const sourceItem of items) {
    const rowSettings = sourceItem && typeof sourceItem === "object" && !Array.isArray(sourceItem) ? sourceItem : null;
    const provisionalContext = {
      ...context,
      item: sourceItem,
      index: selected.length + 1,
    };

    if (rowSettings && Object.prototype.hasOwnProperty.call(rowSettings, "when")) {
      if (!evaluateTemplateCondition(rowSettings.when, provisionalContext)) {
        continue;
      }
    }

    selected.push(sourceItem);
    if (selected.length >= maxItems) {
      break;
    }
  }

  if (!selected.length) {
    const empty = document.createElement("p");
    empty.classList.add("scene-list-empty");
    empty.textContent = interpolateTemplate(element.emptyText || "No data available", context);
    itemsNode.appendChild(empty);
    return wrapper;
  }

  selected.forEach((item, index) => {
    const rowContext = {
      ...context,
      item,
      index: index + 1,
    };

    const rowSettings = item && typeof item === "object" && !Array.isArray(item) ? item : null;

    const row = document.createElement("article");
    row.classList.add("scene-list-item");

    const rowClassName = rowSettings && rowSettings.className !== undefined ? rowSettings.className : element.itemClassName;
    if (rowClassName) {
      for (const className of String(rowClassName).split(" ")) {
        if (className.trim()) {
          row.classList.add(className.trim());
        }
      }
    }

    const rowStyle = rowSettings && rowSettings.style !== undefined ? rowSettings.style : element.itemStyle;
    applyInlineStyleObject(row, rowStyle, rowContext);

    const imagePath = String(
      rowSettings && rowSettings.imagePath !== undefined ? rowSettings.imagePath : element.itemImagePath || ""
    ).trim();
    if (imagePath) {
      const imageSource = resolveExpression(imagePath, rowContext);
      const imageText = String(imageSource || "").trim();
      if (imageText) {
        row.classList.add("scene-list-item-has-image");

        const image = document.createElement("img");
        image.classList.add("scene-list-item-image");
        image.src = imageText;

        const imageSizeValue =
          rowSettings && rowSettings.imageSize !== undefined ? rowSettings.imageSize : element.itemImageSize;
        const imageWidthValue =
          rowSettings && rowSettings.imageWidth !== undefined
            ? rowSettings.imageWidth
            : element.itemImageWidth !== undefined
              ? element.itemImageWidth
              : imageSizeValue;
        const imageHeightValue =
          rowSettings && rowSettings.imageHeight !== undefined
            ? rowSettings.imageHeight
            : element.itemImageHeight !== undefined
              ? element.itemImageHeight
              : imageSizeValue;

        const imageWidth = toCssLength(resolveInterpolatedValue(imageWidthValue, rowContext));
        const imageHeight = toCssLength(resolveInterpolatedValue(imageHeightValue, rowContext));
        if (imageWidth) {
          image.style.width = imageWidth;
          row.style.setProperty("--scene-list-image-column-width", imageWidth);
        } else if (imageHeight) {
          row.style.setProperty("--scene-list-image-column-width", imageHeight);
        }
        if (imageHeight) {
          image.style.height = imageHeight;
        }

        const imageAltTemplate =
          rowSettings && rowSettings.imageAltTemplate !== undefined
            ? rowSettings.imageAltTemplate
            : rowSettings && rowSettings.imageAlt !== undefined
              ? rowSettings.imageAlt
              : element.itemImageAltTemplate || "Item logo";
        image.alt = interpolateTemplate(imageAltTemplate, rowContext);
        image.loading = lowPowerMode ? "lazy" : "eager";
        row.appendChild(image);
      }
    }

    const content = document.createElement("div");
    content.classList.add("scene-list-content");

    const title = document.createElement("p");
    title.classList.add("scene-list-title");
    const titleTemplate =
      rowSettings && rowSettings.titleTemplate !== undefined
        ? rowSettings.titleTemplate
        : rowSettings && rowSettings.title !== undefined
          ? rowSettings.title
          : element.itemTitleTemplate || "{{item}}";
    appendInlineTemplateContent(title, titleTemplate, rowContext);

    const itemTitleFontSize = toCssLength(
      resolveInterpolatedValue(
        rowSettings && rowSettings.titleFontSize !== undefined ? rowSettings.titleFontSize : element.itemTitleFontSize,
        rowContext
      )
    );
    if (itemTitleFontSize) {
      title.style.fontSize = itemTitleFontSize;
    }

    const itemTitleColor = resolveInterpolatedValue(
      rowSettings && rowSettings.titleColor !== undefined ? rowSettings.titleColor : element.itemTitleColor,
      rowContext
    );
    if (itemTitleColor !== undefined && itemTitleColor !== null && String(itemTitleColor).trim()) {
      title.style.color = String(itemTitleColor).trim();
    }

    const itemTitleWeight = resolveInterpolatedValue(
      rowSettings && rowSettings.titleFontWeight !== undefined ? rowSettings.titleFontWeight : element.itemTitleFontWeight,
      rowContext
    );
    if (itemTitleWeight !== undefined && itemTitleWeight !== null && String(itemTitleWeight).trim()) {
      title.style.fontWeight = String(itemTitleWeight).trim();
    }

    const itemTitleAlign = resolveInterpolatedValue(
      rowSettings && rowSettings.titleAlign !== undefined ? rowSettings.titleAlign : element.itemTitleAlign,
      rowContext
    );
    if (itemTitleAlign !== undefined && itemTitleAlign !== null && String(itemTitleAlign).trim()) {
      title.style.textAlign = String(itemTitleAlign).trim();
    }

    content.appendChild(title);

    const subtitleTemplate =
      rowSettings && rowSettings.subtitleTemplate !== undefined
        ? rowSettings.subtitleTemplate
        : rowSettings && rowSettings.subtitle !== undefined
          ? rowSettings.subtitle
          : element.itemSubtitleTemplate;

    if (subtitleTemplate) {
      const subtitle = document.createElement("p");
      subtitle.classList.add("scene-list-subtitle");
      appendInlineTemplateContent(subtitle, subtitleTemplate, rowContext);

      const subtitleHasText = Boolean(String(subtitle.textContent || "").trim());
      const subtitleHasInlineElements = subtitle.childElementCount > 0;
      if (subtitleHasText || subtitleHasInlineElements) {
        const itemSubtitleFontSize = toCssLength(
          resolveInterpolatedValue(
            rowSettings && rowSettings.subtitleFontSize !== undefined
              ? rowSettings.subtitleFontSize
              : element.itemSubtitleFontSize,
            rowContext
          )
        );
        if (itemSubtitleFontSize) {
          subtitle.style.fontSize = itemSubtitleFontSize;
        }

        const itemSubtitleColor = resolveInterpolatedValue(
          rowSettings && rowSettings.subtitleColor !== undefined ? rowSettings.subtitleColor : element.itemSubtitleColor,
          rowContext
        );
        if (itemSubtitleColor !== undefined && itemSubtitleColor !== null && String(itemSubtitleColor).trim()) {
          subtitle.style.color = String(itemSubtitleColor).trim();
        }

        const itemSubtitleWeight = resolveInterpolatedValue(
          rowSettings && rowSettings.subtitleFontWeight !== undefined
            ? rowSettings.subtitleFontWeight
            : element.itemSubtitleFontWeight,
          rowContext
        );
        if (itemSubtitleWeight !== undefined && itemSubtitleWeight !== null && String(itemSubtitleWeight).trim()) {
          subtitle.style.fontWeight = String(itemSubtitleWeight).trim();
        }

        const itemSubtitleAlign = resolveInterpolatedValue(
          rowSettings && rowSettings.subtitleAlign !== undefined ? rowSettings.subtitleAlign : element.itemSubtitleAlign,
          rowContext
        );
        if (itemSubtitleAlign !== undefined && itemSubtitleAlign !== null && String(itemSubtitleAlign).trim()) {
          subtitle.style.textAlign = String(itemSubtitleAlign).trim();
        }

        content.appendChild(subtitle);
      }
    }

    row.appendChild(content);

    if (revealConfig) {
      const revealEntry = {
        node: row,
      };

      if (revealConfig.imageSelector && revealConfig.imagePath) {
        const revealImageSource = resolveSceneRevealValue(revealConfig.imagePath, rowContext);
        if (revealImageSource) {
          revealEntry.imageSrc = revealImageSource;
        }
      }
      if (revealConfig.imageSelector && revealConfig.imageAltTemplate) {
        revealEntry.imageAlt = interpolateTemplate(revealConfig.imageAltTemplate, rowContext);
      }

      row.classList.add("scene-list-item-reveal-pending");
      row.style.setProperty("--scene-reveal-fade-ms", `${revealConfig.fadeMs}ms`);
      if (revealConfig.highlightColor) {
        row.style.setProperty("--scene-reveal-highlight-color", revealConfig.highlightColor);
      }
      if (revealConfig.settledColor) {
        row.style.setProperty("--scene-reveal-settled-color", revealConfig.settledColor);
      }
      revealEntries.push(revealEntry);
    } else {
      const staggerMs = Math.max(0, Number(element.staggerMs || 0));
      if (staggerMs > 0) {
        row.style.animationDelay = `${index * staggerMs}ms`;
        row.classList.add("scene-list-item-stagger");
      }
    }

    itemsNode.appendChild(row);
  });

  if (revealConfig && revealEntries.length) {
    wrapper.__sceneListReveal = {
      entries: revealEntries,
      direction: revealConfig.direction,
      intervalMs: revealConfig.intervalMs,
      startDelayMs: revealConfig.startDelayMs,
      imageSelector: revealConfig.imageSelector,
      imageFadeMs: revealConfig.imageFadeMs,
    };
  }

  return wrapper;
}

function createSceneElement(element, context, options = {}) {
  if (Object.prototype.hasOwnProperty.call(element, "when") && !evaluateTemplateCondition(element.when, context)) {
    return null;
  }

  const skipEnterAnimation = Boolean(options && options.skipEnterAnimation);

  const kind = String(element.kind || "text").toLowerCase();
  let node;

  if (kind === "image") {
    node = createSceneImageElement(element, context);
  } else if (kind === "bar") {
    node = createSceneBarElement(element, context);
  } else if (kind === "list" || kind === "grid") {
    node = createSceneListElement(element, context);
  } else {
    node = createSceneTextElement(element, context);
  }

  node.classList.add("scene-el");

  if (element.className) {
    for (const className of String(element.className).split(" ")) {
      if (className.trim()) {
        node.classList.add(className.trim());
      }
    }
  }

  const changeKeyValue = resolveInterpolatedValue(element.changeKeys ?? element.changeKey, context);
  if (changeKeyValue !== undefined && changeKeyValue !== null) {
    const text = String(changeKeyValue).trim();
    if (text) {
      node.setAttribute("data-live-change-keys", text);
    }
  }

  applyElementBounds(node, element, context);
  applyInlineStyleObject(node, element.style, context);

  let enterMotion = normalizeMotion(element.enter, visualSceneConfig.elementDefaults.enter);
  let exitMotion = normalizeMotion(element.exit, visualSceneConfig.elementDefaults.exit);

  if (lowPowerMode && !keepLowPowerTransitions) {
    enterMotion = {
      effect: "fade",
      durationMs: 120,
      delayMs: 0,
      easing: "linear",
    };
    exitMotion = {
      effect: "fade",
      durationMs: 100,
      delayMs: 0,
      easing: "linear",
    };
  }

  if (skipEnterAnimation) {
    enterMotion = {
      ...enterMotion,
      durationMs: 0,
      delayMs: 0,
      easing: "linear",
    };
  }

  node.classList.add(`enter-${enterMotion.effect}`);
  node.classList.add(`exit-${exitMotion.effect}`);
  node.style.setProperty("--enter-duration", `${enterMotion.durationMs}ms`);
  node.style.setProperty("--enter-ease", enterMotion.easing);
  node.style.setProperty("--exit-duration", `${exitMotion.durationMs}ms`);
  node.style.setProperty("--exit-ease", exitMotion.easing);

  if (lowPowerMode && !keepLowPowerTransitions) {
    node.classList.add("is-visible");
  } else if (skipEnterAnimation) {
    node.classList.add("is-visible");
  } else {
    queueSceneTimer(() => {
      node.classList.add("is-visible");
    }, enterMotion.delayMs);
  }

  let listReveal = node && node.__sceneListReveal ? node.__sceneListReveal : null;
  const disableListReveal = skipEnterAnimation || (lowPowerMode && !keepLowPowerTransitions);
  if (disableListReveal && listReveal && Array.isArray(listReveal.entries)) {
    for (const entry of listReveal.entries) {
      const rowNode = entry?.node;
      if (!rowNode) {
        continue;
      }
      rowNode.classList.remove("scene-list-item-reveal-pending", "scene-list-item-reveal-active");
      rowNode.classList.add("scene-list-item-reveal-visible", "scene-list-item-reveal-complete");
    }
    listReveal = null;
  }

  return {
    node,
    maxOutMs: exitMotion.durationMs + exitMotion.delayMs,
    enterDelayMs: enterMotion.delayMs,
    listReveal,
  };
}

function resolveEarlyExitBeforeEndMs(element, context) {
  const configured = resolveInterpolatedValue(element?.exitBeforeSlideEndMs ?? element?.exitLeadMs, context);
  const numeric = Number(configured);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return 0;
  }
  return Math.max(0, numeric);
}

function resolveEarlyExitAtMs(element, context, slideDurationMs, enterDelayMs = 0) {
  const minVisibleMs = 120;
  const enterAtMs = Math.max(0, Number(enterDelayMs || 0));

  const explicitAt = Number(resolveInterpolatedValue(element?.exitAtMs, context));
  if (Number.isFinite(explicitAt) && explicitAt >= enterAtMs + minVisibleMs) {
    return Math.max(0, explicitAt);
  }

  const explicitAfter = Number(resolveInterpolatedValue(element?.exitAfterEnterMs ?? element?.exitAfterMs, context));
  if (Number.isFinite(explicitAfter) && explicitAfter >= 0) {
    const candidateAtMs = Math.max(0, enterAtMs + explicitAfter);
    if (candidateAtMs >= enterAtMs + minVisibleMs) {
      return candidateAtMs;
    }
  }

  const beforeEndMs = resolveEarlyExitBeforeEndMs(element, context);
  if (beforeEndMs > 0) {
    const candidateAtMs = Math.max(0, slideDurationMs - beforeEndMs);
    if (candidateAtMs >= enterAtMs + minVisibleMs) {
      return candidateAtMs;
    }
  }

  return null;
}

function resolveBackgroundImage(imageValue) {
  if (!imageValue) {
    return "";
  }

  const text = String(imageValue).trim();
  if (!text) {
    return "";
  }

  if (text.startsWith("url(") || text.startsWith("linear-gradient") || text.startsWith("radial-gradient")) {
    return text;
  }

  return `url("${text.replaceAll('"', '\\"')}")`;
}

function isGradientBackgroundValue(backgroundValue) {
  const text = String(backgroundValue || "").trim().toLowerCase();
  return text.startsWith("linear-gradient(") || text.startsWith("radial-gradient(") || text.startsWith("conic-gradient(");
}

function isUrlBackgroundValue(backgroundValue) {
  const text = String(backgroundValue || "").trim().toLowerCase();
  return text.startsWith("url(");
}

function getVisualTemplateForSlide(slide) {
  if (!visualSceneConfig.enabled) {
    return null;
  }

  const templates = visualSceneConfig.templates || {};
  if (templates[slide.id]) {
    return templates[slide.id];
  }
  if (templates[slide.type]) {
    return templates[slide.type];
  }

  return null;
}

function renderVisualTemplateSlide(slide, options = {}) {
  const template = getVisualTemplateForSlide(slide);
  if (!template || typeof template !== "object") {
    return false;
  }

  const skipEnterAnimation = Boolean(options && options.skipEnterAnimation);

  const slideKey = String(slide?.id || "").trim();
  const endpointData = slideKey ? templateRuntimeDataBySlide[slideKey] || null : null;
  const context = buildVisualRuntimeContext(slide, template, undefined, endpointData, latestStatePayload);

  const transitionIn = normalizeMotion(template.transitionIn, {
    effect: "slide-left",
    durationMs: visualSceneConfig.slideTransitionMs,
    delayMs: 0,
    easing: "cubic-bezier(0.22, 1, 0.36, 1)",
  });
  const transitionOut = normalizeMotion(template.transitionOut, {
    effect: "fade",
    durationMs: visualSceneConfig.slideTransitionMs,
    delayMs: 0,
    easing: "ease",
  });

  const scene = document.createElement("article");
  scene.classList.add("kiosk-slide", "slide-surface", "visual-scene", `scene-enter-${transitionIn.effect}`);
  scene.style.setProperty("--scene-in-duration", `${transitionIn.durationMs}ms`);
  scene.style.setProperty("--scene-in-ease", transitionIn.easing);
  scene.style.setProperty("--scene-out-duration", `${transitionOut.durationMs}ms`);
  scene.style.setProperty("--scene-out-ease", transitionOut.easing);

  const backgroundConfig = template.background || {};
  const bgNode = document.createElement("div");
  bgNode.classList.add("scene-background");

  const backgroundColor = resolveInterpolatedValue(backgroundConfig.color, context);
  const hasGradientColor = isGradientBackgroundValue(backgroundColor);
  const gradientMotionDurationMs = Math.max(
    8000,
    Number(resolveInterpolatedValue(backgroundConfig.motionDurationMs, context) || 26000)
  );
  if (backgroundColor) {
    bgNode.style.background = String(backgroundColor);
  }

  const backgroundImage = resolveInterpolatedValue(backgroundConfig.image, context);
  const resolvedImage = resolveBackgroundImage(backgroundImage);
  const hasGradientImage = isGradientBackgroundValue(resolvedImage);
  const hasUrlImage = isUrlBackgroundValue(resolvedImage);
  if (resolvedImage) {
    bgNode.style.backgroundImage = resolvedImage;
    bgNode.style.backgroundSize = String(resolveInterpolatedValue(backgroundConfig.size, context) || "cover");
    bgNode.style.backgroundPosition = String(resolveInterpolatedValue(backgroundConfig.position, context) || "center");
    bgNode.style.backgroundRepeat = String(resolveInterpolatedValue(backgroundConfig.repeat, context) || "no-repeat");
    bgNode.style.backgroundBlendMode = String(resolveInterpolatedValue(backgroundConfig.blendMode, context) || "normal");
  }

  if (!lowPowerMode && hasUrlImage) {
    bgNode.classList.add("scene-background-image-motion");
  } else if (!lowPowerMode && (hasGradientColor || hasGradientImage)) {
    bgNode.classList.add("scene-background-gradient-motion");
    bgNode.style.setProperty("--scene-gradient-motion-duration", `${gradientMotionDurationMs}ms`);
  }

  scene.appendChild(bgNode);

  const overlayValue = resolveInterpolatedValue(backgroundConfig.overlay, context);
  if (overlayValue) {
    const overlayNode = document.createElement("div");
    overlayNode.classList.add("scene-overlay");
    overlayNode.style.background = String(overlayValue);
    if (!lowPowerMode && isGradientBackgroundValue(overlayValue)) {
      const overlayMotionDurationMs = Math.max(
        8000,
        Number(resolveInterpolatedValue(backgroundConfig.overlayMotionDurationMs ?? backgroundConfig.motionDurationMs, context) || 22000)
      );
      overlayNode.classList.add("scene-overlay-gradient-motion");
      overlayNode.style.setProperty("--scene-overlay-motion-duration", `${overlayMotionDurationMs}ms`);
    }
    scene.appendChild(overlayNode);
  }

  const layerNode = document.createElement("div");
  layerNode.classList.add("scene-layer");
  scene.appendChild(layerNode);

  if (endpointData && endpointData.error) {
    const errorNode = document.createElement("p");
    errorNode.classList.add("scene-text", "scene-subtitle", "scene-template-error");
    const detail = String(endpointData.error || "").trim();
    const preview = detail.length > 220 ? `${detail.slice(0, 217)}...` : detail;
    errorNode.textContent = `Template API error: ${preview}`;
    errorNode.style.position = "absolute";
    errorNode.style.left = "5%";
    errorNode.style.top = "90%";
    errorNode.style.width = "90%";
    errorNode.style.padding = "0.32rem 0.48rem";
    errorNode.style.borderRadius = "0.34rem";
    errorNode.style.fontSize = "0.78rem";
    errorNode.style.lineHeight = "1.2";
    errorNode.style.color = "#ffd6d6";
    errorNode.style.background = "rgba(70, 14, 18, 0.78)";
    errorNode.style.zIndex = "30";
    layerNode.appendChild(errorNode);
  }

  const elements = Array.isArray(template.elements) ? template.elements : [];
  const slideDurationMs = Math.max(5000, Number(slide.durationSeconds || 10) * 1000);
  const suppressIntraSlideChoreography = skipEnterAnimation || (lowPowerMode && !keepLowPowerTransitions);
  let maxOutMs = transitionOut.durationMs + transitionOut.delayMs;
  const earlyExitPlans = [];
  const listRevealPlans = [];
  for (const element of elements) {
    if (!element || typeof element !== "object") {
      continue;
    }

    const rendered = createSceneElement(element, context, { skipEnterAnimation });
    if (!rendered) {
      continue;
    }
    maxOutMs = Math.max(maxOutMs, rendered.maxOutMs);
    const earlyExitAtMs = suppressIntraSlideChoreography ? null : resolveEarlyExitAtMs(element, context, slideDurationMs, rendered.enterDelayMs);
    if (earlyExitAtMs !== null) {
      earlyExitPlans.push({
        node: rendered.node,
        atMs: earlyExitAtMs,
      });
    }

    if (!suppressIntraSlideChoreography && rendered.listReveal) {
      rendered.listReveal.sceneRoot = scene;
      listRevealPlans.push({
        listReveal: rendered.listReveal,
        enterDelayMs: rendered.enterDelayMs,
      });
    }

    layerNode.appendChild(rendered.node);
  }

  currentSlideOutMs = Math.max(320, Math.min(1800, maxOutMs));

  for (const plan of listRevealPlans) {
    triggerSceneListReveal(plan.listReveal, plan.enterDelayMs);
  }

  for (const plan of earlyExitPlans) {
    const triggerMs = Math.max(0, Number(plan.atMs || 0));
    queueSceneTimer(() => {
      plan.node.classList.add("is-exiting");
    }, triggerMs);
  }

  slideContainer.innerHTML = "";
  slideContainer.appendChild(scene);

  if (lowPowerMode && !keepLowPowerTransitions) {
    scene.classList.add("is-visible");
  } else if (skipEnterAnimation) {
    scene.classList.add("is-visible");
  } else {
    window.requestAnimationFrame(() => {
      scene.classList.add("is-visible");
    });
  }

  return true;
}

function applyHighlightSourceForCurrentSlide() {
  if (activeMode === "live_stream") {
    return false;
  }

  const payloadHighlights = Array.isArray(activeSlidePayload?.highlights)
    ? activeSlidePayload.highlights.filter((clip) => clip && clip.url)
    : [];

  if (activeSlideType === "live_game_status") {
    const freshLiveHighlights = filterHighlightsByAgeHours(payloadHighlights, 4);
    return setActiveHighlights(freshLiveHighlights);
  }

  const featuredFallback =
    activeSlideType === "featured_player" && Array.isArray(kioskPayload?.featuredPlayer?.highlights)
      ? kioskPayload.featuredPlayer.highlights.filter((clip) => clip && clip.url)
      : [];

  const slideHighlights = payloadHighlights.length ? payloadHighlights : featuredFallback;
  const targetHighlights = slideHighlights.length ? slideHighlights : baseHighlights;
  return setActiveHighlights(targetHighlights);
}

function extractLiveStatusSnapshot(payload) {
  const inning = payload?.inning && typeof payload.inning === "object" ? payload.inning : {};
  const count = payload?.count && typeof payload.count === "object" ? payload.count : {};
  const runners = payload?.baseRunners && typeof payload.baseRunners === "object" ? payload.baseRunners : {};

  return {
    inningState: String(inning.state || "").trim(),
    inningNumber: Number(inning.number || 0),
    balls: Number(count.balls || 0),
    strikes: Number(count.strikes || 0),
    outs: Number(count.outs || 0),
    occupancyCode: String(runners.occupancyCode || "000"),
    firstRunnerKey: String(runners?.first?.id || runners?.first?.fullName || ""),
    secondRunnerKey: String(runners?.second?.id || runners?.second?.fullName || ""),
    thirdRunnerKey: String(runners?.third?.id || runners?.third?.fullName || ""),
    awayRuns: Number(payload?.score?.away?.runs || payload?.away?.runs || 0),
    homeRuns: Number(payload?.score?.home?.runs || payload?.home?.runs || 0),
  };
}

function collectLiveStatusChangeKeys(previousSnapshot, nextSnapshot) {
  const changeKeys = new Set();
  if (!previousSnapshot || !nextSnapshot) {
    return changeKeys;
  }

  if (
    previousSnapshot.inningState !== nextSnapshot.inningState ||
    previousSnapshot.inningNumber !== nextSnapshot.inningNumber
  ) {
    changeKeys.add("inning");
  }
  if (previousSnapshot.balls !== nextSnapshot.balls) {
    changeKeys.add("count.balls");
  }
  if (previousSnapshot.strikes !== nextSnapshot.strikes) {
    changeKeys.add("count.strikes");
  }
  if (previousSnapshot.outs !== nextSnapshot.outs) {
    changeKeys.add("count.outs");
  }
  if (
    previousSnapshot.occupancyCode !== nextSnapshot.occupancyCode ||
    previousSnapshot.firstRunnerKey !== nextSnapshot.firstRunnerKey
  ) {
    changeKeys.add("base.first");
  }
  if (
    previousSnapshot.occupancyCode !== nextSnapshot.occupancyCode ||
    previousSnapshot.secondRunnerKey !== nextSnapshot.secondRunnerKey
  ) {
    changeKeys.add("base.second");
  }
  if (
    previousSnapshot.occupancyCode !== nextSnapshot.occupancyCode ||
    previousSnapshot.thirdRunnerKey !== nextSnapshot.thirdRunnerKey
  ) {
    changeKeys.add("base.third");
  }
  if (previousSnapshot.awayRuns !== nextSnapshot.awayRuns || previousSnapshot.homeRuns !== nextSnapshot.homeRuns) {
    changeKeys.add("score");
  }

  return changeKeys;
}

function parseLiveChangeKeyList(rawValue) {
  return String(rawValue || "")
    .split(/[|,\s]+/g)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function flashLiveChangeNodes(changeKeys) {
  if (!(slideContainer instanceof HTMLElement) || !changeKeys || !changeKeys.size) {
    return;
  }

  const nodes = slideContainer.querySelectorAll("[data-live-change-keys]");
  for (const node of nodes) {
    const nodeKeys = parseLiveChangeKeyList(node.getAttribute("data-live-change-keys"));
    if (!nodeKeys.length) {
      continue;
    }

    const shouldFlash = nodeKeys.some((key) => changeKeys.has(key));
    if (!shouldFlash) {
      continue;
    }

    node.classList.remove("live-value-flash");
    // Restart animation when values change repeatedly.
    void node.offsetWidth;
    node.classList.add("live-value-flash");
    node.addEventListener(
      "animationend",
      () => {
        node.classList.remove("live-value-flash");
      },
      { once: true }
    );
  }
}

function renderStatusSlide(payload) {
  const status = payload?.statusText || lastScoreboard?.status?.detailed || "No live game right now";
  const inningState = payload?.inningState || lastScoreboard?.inning?.state || "";
  const inningNum = payload?.inningNumber || lastScoreboard?.inning?.number || 0;
  const count = payload?.count || lastScoreboard?.count || { balls: 0, strikes: 0, outs: 0 };
  const inningText = inningState ? `${inningState} ${inningNum || ""}`.trim() : "No active inning";

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(currentTeamName)} Pulse</p>
      <p class="kiosk-subtitle">${escapeHtml(status)}</p>
      <p class="kiosk-meta">${escapeHtml(inningText)} | B ${count.balls} S ${count.strikes} O ${count.outs}</p>
      <p class="kiosk-caption">Mode</p>
      <p class="kiosk-subtitle">${escapeHtml(modeText(activeMode))}</p>
    </article>
  `;
}

function renderLiveCountRow(label, slots, changeKey) {
  const sourceSlots = Array.isArray(slots) ? slots : [];
  const renderedSlots = sourceSlots
    .map((slot, index) => {
      const icon = String(slot?.icon || "").trim();
      const active = Boolean(slot?.active);
      const dotClass = `live-dot ${active ? "is-active" : "is-inactive"}`;
      if (icon) {
        return `<img class="${dotClass}" src="${escapeHtml(icon)}" alt="${escapeHtml(label)} ${index + 1}" />`;
      }
      return `<span class="${dotClass}" aria-hidden="true"></span>`;
    })
    .join("");

  return `
    <div class="live-dot-row" data-live-change-keys="${escapeHtml(changeKey)}">
      <span class="live-dot-label">${escapeHtml(label)}</span>
      <span class="live-dot-track">${renderedSlots}</span>
    </div>
  `;
}

function renderLiveBaseSlot(baseLabel, baseData, changeKey) {
  const icon = String(baseData?.icon || "").trim();
  const runner = String(baseData?.runnerLastName || baseData?.runner || "--").trim();
  const occupied = Boolean(baseData?.occupied);
  const baseClass = `live-base-slot ${occupied ? "is-occupied" : "is-empty"}`;
  const iconMarkup = icon
    ? `<img class="live-base-icon" src="${escapeHtml(icon)}" alt="${escapeHtml(baseLabel)}" />`
    : `<span class="live-base-icon-fallback" aria-hidden="true"></span>`;

  return `
    <div class="${baseClass}" data-live-change-keys="${escapeHtml(changeKey)}">
      ${iconMarkup}
      <span class="live-base-label">${escapeHtml(baseLabel)}</span>
      <span class="live-base-runner">${escapeHtml(runner || "--")}</span>
    </div>
  `;
}

function renderLiveGameStatusSlide(payload) {
  const score = payload?.score && typeof payload.score === "object" ? payload.score : {};
  const away = score.away && typeof score.away === "object" ? score.away : payload?.away || {};
  const home = score.home && typeof score.home === "object" ? score.home : payload?.home || {};
  const inning = payload?.inning && typeof payload.inning === "object" ? payload.inning : score.inning || {};
  const batter = payload?.currentBatter && typeof payload.currentBatter === "object" ? payload.currentBatter : {};
  const pitcher = payload?.currentPitcher && typeof payload.currentPitcher === "object" ? payload.currentPitcher : {};
  const onDeck = payload?.onDeck && typeof payload.onDeck === "object" ? payload.onDeck : {};
  const indicators = payload?.indicators && typeof payload.indicators === "object" ? payload.indicators : {};
  const countIndicators = indicators?.count && typeof indicators.count === "object" ? indicators.count : {};
  const baseIndicators = indicators?.bases && typeof indicators.bases === "object" ? indicators.bases : {};

  const awayLabel = String(away.name || away.abbreviation || away.abbrev || "Away").trim();
  const homeLabel = String(home.name || home.abbreviation || home.abbrev || "Home").trim();
  const inningLabel = String(inning.label || `${inning.state || ""} ${inning.number || ""}`.trim() || "Inning TBD");

  const awayLogo = String(payload?.away?.logoUrls?.capOnDark || payload?.away?.logoUrls?.primary || "").trim();
  const homeLogo = String(payload?.home?.logoUrls?.capOnDark || payload?.home?.logoUrls?.primary || "").trim();

  const ballsSlots = Array.isArray(countIndicators?.balls) ? countIndicators.balls : [];
  const strikesSlots = Array.isArray(countIndicators?.strikes) ? countIndicators.strikes : [];
  const outsSlots = Array.isArray(countIndicators?.outs) ? countIndicators.outs : [];

  const baseFirst = baseIndicators?.first && typeof baseIndicators.first === "object" ? baseIndicators.first : {};
  const baseSecond = baseIndicators?.second && typeof baseIndicators.second === "object" ? baseIndicators.second : {};
  const baseThird = baseIndicators?.third && typeof baseIndicators.third === "object" ? baseIndicators.third : {};

  const awayLogoMarkup = awayLogo
    ? `<img class="live-team-logo" src="${escapeHtml(awayLogo)}" alt="${escapeHtml(awayLabel)}" />`
    : `<span class="live-team-fallback">${escapeHtml(String(awayLabel || "Away").slice(0, 3).toUpperCase())}</span>`;
  const homeLogoMarkup = homeLogo
    ? `<img class="live-team-logo" src="${escapeHtml(homeLogo)}" alt="${escapeHtml(homeLabel)}" />`
    : `<span class="live-team-fallback">${escapeHtml(String(homeLabel || "Home").slice(0, 3).toUpperCase())}</span>`;

  return `
    <article class="kiosk-slide live-status-slide">
      <p class="kiosk-title">${escapeHtml(payload?.title || "Live Game Center")}</p>
      <p class="kiosk-meta" data-live-change-keys="inning">${escapeHtml(inningLabel)}</p>
      <div class="live-status-grid">
        <div class="live-status-card">
          <p class="kiosk-caption">Score</p>
          <div class="live-score-line" data-live-change-keys="score">
            <span class="live-score-team">${awayLogoMarkup}</span>
            <span class="live-score-runs">${Number(away.runs || 0)}</span>
            <span class="live-score-separator">-</span>
            <span class="live-score-runs">${Number(home.runs || 0)}</span>
            <span class="live-score-team">${homeLogoMarkup}</span>
          </div>
        </div>
        <div class="live-status-card">
          <p class="kiosk-caption">Matchup</p>
          <p class="leader-value">Pitcher: ${escapeHtml(pitcher.fullName || "TBD")}</p>
          <p class="leader-meta">Batter: ${escapeHtml(batter.fullName || "TBD")}</p>
          <p class="leader-meta">On deck: ${escapeHtml(onDeck.fullName || "TBD")}</p>
        </div>
        <div class="live-status-card">
          <p class="kiosk-caption">Count</p>
          <div class="live-count-stack">
            ${renderLiveCountRow("Balls", ballsSlots, "count.balls")}
            ${renderLiveCountRow("Strikes", strikesSlots, "count.strikes")}
            ${renderLiveCountRow("Outs", outsSlots, "count.outs")}
          </div>
        </div>
        <div class="live-status-card">
          <p class="kiosk-caption">Runners</p>
          <div class="live-bases-grid">
            ${renderLiveBaseSlot("1B", baseFirst, "base.first")}
            ${renderLiveBaseSlot("2B", baseSecond, "base.second")}
            ${renderLiveBaseSlot("3B", baseThird, "base.third")}
          </div>
        </div>
      </div>
      <p class="kiosk-meta">Highlights from this game play in the right panel while this slide is active.</p>
    </article>
  `;
}

function renderPreviousGameSlide(payload) {
  const previousGame = payload || kioskPayload?.previousGame;
  if (!previousGame) {
    return '<article class="kiosk-slide"><p class="kiosk-title">Previous Game Story</p><p class="kiosk-subtitle">No final game data found yet.</p></article>';
  }

  const plays = (previousGame.playByPlay || [])
    .slice(0, 6)
    .map((play) => {
      const inning = escapeHtml(play.inning || "Play");
      const description = escapeHtml(play.description || play.event || "Play");
      return `<li class="pbp-item"><span class="pbp-inning">${inning}</span>${description}</li>`;
    })
    .join("");

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">Previous Game</p>
      <p class="kiosk-subtitle">${escapeHtml(previousGame.date || "")}: ${escapeHtml(previousGame.result || "Final")}</p>
      <p class="kiosk-meta">${escapeHtml(previousGame.padresLine || "")}</p>
      <p class="kiosk-caption">Key Plays</p>
      <ul class="pbp-list">${plays || '<li class="pbp-item">No play-by-play items available.</li>'}</ul>
    </article>
  `;
}

function renderFeaturedPlayerSlide(payload) {
  const featured = payload || kioskPayload?.featuredPlayer;
  if (!featured) {
    return '<article class="kiosk-slide"><p class="kiosk-title">Featured Player Breakdown</p><p class="kiosk-subtitle">No featured player game data available yet.</p></article>';
  }

  const meter = Math.max(0, Math.min(100, Number(featured.hotStreakMeter || 0)));
  const eventsText = (featured.events || []).length
    ? escapeHtml((featured.events || []).join(" "))
    : "No plate appearances found.";

  const detailBits = [];
  if (Number(featured.walks || 0) > 0) {
    detailBits.push(`${featured.walks} Walk${featured.walks === 1 ? "" : "s"}`);
  }
  if (Number(featured.strikeouts || 0) > 0) {
    detailBits.push(`${featured.strikeouts} Strikeout${featured.strikeouts === 1 ? "" : "s"}`);
  }
  if (Number(featured.doubles || 0) > 0) {
    detailBits.push(`${featured.doubles} Double${featured.doubles === 1 ? "" : "s"}`);
  }
  if (Number(featured.triples || 0) > 0) {
    detailBits.push(`${featured.triples} Triple${featured.triples === 1 ? "" : "s"}`);
  }
  if (Number(featured.homeRuns || 0) > 0) {
    detailBits.push(`${featured.homeRuns} Home Run${featured.homeRuns === 1 ? "" : "s"}`);
  }

  const detailText = detailBits.length ? escapeHtml(detailBits.join(" | ")) : "No extra-base production in this game.";
  const headshot = featured.headshotUrl
    ? `<img class="featured-photo" src="${escapeHtml(featured.headshotUrl)}" alt="${escapeHtml(featured.name)}" />`
    : "";

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(featured.name || "Featured Player")}</p>
      <p class="kiosk-subtitle">${escapeHtml(featured.date || "")}: ${escapeHtml(featured.line || "0-0")} | ${escapeHtml(String(featured.rbi || 0))} RBI</p>
      <div class="featured-layout">
        ${headshot}
        <div>
          <p class="featured-statline">${escapeHtml(featured.line || "0-0")}</p>
          <p class="featured-line">Hit Streak: ${escapeHtml(String(featured.hitStreak || 0))}</p>
          <p class="featured-events">${eventsText}</p>
          <p class="featured-events">${detailText}</p>
          <div class="hot-meter">
            <div class="hot-meter-track">
              <div class="hot-meter-fill" style="width:${meter}%;"></div>
            </div>
            <p class="hot-meter-label">Hot Streak Meter: ${escapeHtml(featured.hotStreakLabel || "Warm")} (${meter}%)</p>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderScheduleSlide(payload) {
  const games = Array.isArray(payload?.games) ? payload.games : [];
  if (!games.length) {
    return '<article class="kiosk-slide"><p class="kiosk-title">Upcoming Schedule</p><p class="kiosk-subtitle">No games found in the selected range.</p></article>';
  }

  const rows = games
    .slice(0, 6)
    .map((game) => {
      const when = game.gameDate ? formatTimestamp(game.gameDate) : game.officialDate || "Date TBD";
      const matchup = game.matchup || `${game.homeAway || ""} vs ${game.opponentName || "Opponent"}`;
      const detail = [game.status || "", game.venue || ""].filter(Boolean).join(" | ");

      return `
        <li class="leader-item">
          <p class="leader-name">${escapeHtml(when)}</p>
          <p class="leader-value">${escapeHtml(matchup)}</p>
          <p class="leader-meta">${escapeHtml(detail)}</p>
        </li>
      `;
    })
    .join("");

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">Upcoming Schedule</p>
      <ul class="leader-list">${rows}</ul>
    </article>
  `;
}

function renderGameTodaySlide(payload) {
  const games = Array.isArray(payload?.games) ? payload.games : [];
  const headline = String(payload?.headline || (games.length > 1 ? "Doubleheader Today" : "Game Today"));

  if (!games.length) {
    return `
      <article class="kiosk-slide">
        <p class="kiosk-title">${escapeHtml(headline)}</p>
        <p class="kiosk-subtitle">No game is scheduled for this team today.</p>
      </article>
    `;
  }

  const rows = games
    .slice(0, 2)
    .map((game, index) => {
      const gameNumber = Number(game?.gameNumber || 0);
      const label = gameNumber > 0 ? `Game ${gameNumber}` : `Game ${index + 1}`;
      const startText = game?.gameDate ? formatTimestamp(game.gameDate) : game?.officialDate || "Time TBD";
      const matchup =
        game?.matchup ||
        `${game?.away?.name || "Away"} at ${game?.home?.name || "Home"}`;

      const detailParts = [];
      const statusText = String(game?.status?.detailed || "").trim();
      const venueText = String(game?.venue || "").trim();
      if (statusText) {
        detailParts.push(statusText);
      }
      if (venueText) {
        detailParts.push(venueText);
      }

      const scoreVisible = ["Live", "Final"].includes(String(game?.status?.abstract || ""));
      if (scoreVisible) {
        detailParts.push(
          `${game?.away?.name || "Away"} ${Number(game?.away?.runs || 0)} - ${Number(game?.home?.runs || 0)} ${game?.home?.name || "Home"}`
        );
      }

      return `
        <li class="leader-item">
          <p class="leader-name">${escapeHtml(label)} | ${escapeHtml(startText)}</p>
          <p class="leader-value">${escapeHtml(matchup)}</p>
          <p class="leader-meta">${escapeHtml(detailParts.join(" | "))}</p>
        </li>
      `;
    })
    .join("");

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(headline)}</p>
      <ul class="leader-list">${rows}</ul>
    </article>
  `;
}

function renderWeatherSlide(payload) {
  if (!payload || payload.unavailable) {
    const message = payload?.message || "Weather forecast is unavailable right now.";
    return `<article class="kiosk-slide"><p class="kiosk-title">Next Game Weather</p><p class="kiosk-subtitle">${escapeHtml(message)}</p></article>`;
  }

  const venueLine = [payload.venue || "", payload.cityState || ""].filter(Boolean).join(" | ");
  const forecastTime = payload.forecastTimeLocal ? formatTimestamp(payload.forecastTimeLocal) : "";

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">Next Game Weather</p>
      <p class="kiosk-subtitle">${escapeHtml(payload.condition || "Forecast")}</p>
      <p class="kiosk-meta">${escapeHtml(venueLine)}</p>
      <p class="kiosk-meta">${escapeHtml(forecastTime)}</p>
      <div class="weather-grid">
        <p class="weather-pill">Temp ${escapeHtml(String(payload.temperatureF ?? "-"))}F</p>
        <p class="weather-pill">Feels ${escapeHtml(String(payload.feelsLikeF ?? "-"))}F</p>
        <p class="weather-pill">Rain ${escapeHtml(String(payload.precipProbability ?? "-"))}%</p>
        <p class="weather-pill">Wind ${escapeHtml(String(payload.windSpeedKph ?? "-"))} kph</p>
      </div>
    </article>
  `;
}

function renderHittingLeadersSlide(payload) {
  const leaders = Array.isArray(payload?.leaders) ? payload.leaders : [];
  if (!leaders.length) {
    return '<article class="kiosk-slide"><p class="kiosk-title">Hitting Leaders</p><p class="kiosk-subtitle">No hitting stats available yet.</p></article>';
  }

  const rows = leaders
    .map((leader) => {
      const name = `${leader.name || "Player"}${leader.position ? ` (${leader.position})` : ""}`;
      const value = `AVG ${leader.avg || ".000"} | OPS ${leader.ops || ".000"} | HR ${leader.homeRuns || 0} | RBI ${leader.rbi || 0}`;
      return `<li class="leader-item"><p class="leader-name">${escapeHtml(name)}</p><p class="leader-value">${escapeHtml(value)}</p></li>`;
    })
    .join("");

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(payload.teamName || "Team")} Hitting Leaders</p>
      <ul class="leader-list">${rows}</ul>
    </article>
  `;
}

function renderPitchingLeadersSlide(payload) {
  const leaders = Array.isArray(payload?.leaders) ? payload.leaders : [];
  if (!leaders.length) {
    return '<article class="kiosk-slide"><p class="kiosk-title">Pitching Leaders</p><p class="kiosk-subtitle">No pitching stats available yet.</p></article>';
  }

  const rows = leaders
    .map((leader) => {
      const name = `${leader.name || "Player"}${leader.position ? ` (${leader.position})` : ""}`;
      const value = `ERA ${leader.era || "-"} | WHIP ${leader.whip || "-"} | SO ${leader.strikeouts || 0} | IP ${leader.inningsPitched || "0.0"}`;
      return `<li class="leader-item"><p class="leader-name">${escapeHtml(name)}</p><p class="leader-value">${escapeHtml(value)}</p></li>`;
    })
    .join("");

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(payload.teamName || "Team")} Pitching Leaders</p>
      <ul class="leader-list">${rows}</ul>
    </article>
  `;
}

function renderPlayerBreakdownSlide(payload) {
  if (!payload) {
    return '<article class="kiosk-slide"><p class="kiosk-title">Player Breakdown</p><p class="kiosk-subtitle">No player data available.</p></article>';
  }

  const meter = Math.max(0, Math.min(100, Number(payload.hotMeter || 0)));
  const headshot = payload.headshotUrl
    ? `<img class="featured-photo" src="${escapeHtml(payload.headshotUrl)}" alt="${escapeHtml(payload.name || "Player")}" />`
    : "";

  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(payload.name || "Player")}</p>
      <p class="kiosk-subtitle">${escapeHtml(payload.teamName || "Team")}${payload.position ? ` | ${escapeHtml(payload.position)}` : ""}</p>
      <div class="featured-layout">
        ${headshot}
        <div>
          <p class="featured-line">${escapeHtml(payload.seasonLine || "Season line unavailable")}</p>
          <p class="featured-events">${escapeHtml(payload.lastGameLine || "No last game line available")}</p>
          <div class="hot-meter">
            <div class="hot-meter-track">
              <div class="hot-meter-fill" style="width:${meter}%;"></div>
            </div>
            <p class="hot-meter-label">Hot Streak Meter: ${escapeHtml(payload.hotLabel || "Warm")} (${meter}%)</p>
          </div>
        </div>
      </div>
    </article>
  `;
}

function renderUnknownSlide(slide) {
  return `
    <article class="kiosk-slide">
      <p class="kiosk-title">${escapeHtml(slide.title || "Slide")}</p>
      <p class="kiosk-subtitle">Template type ${escapeHtml(slide.type || "unknown")} is not rendered in UI yet.</p>
    </article>
  `;
}

function animateNodeIn(node, inDurationMs, inEasing, outDurationMs, outEasing) {
  if (!node) {
    return;
  }

  node.classList.add("slide-surface");
  node.style.setProperty("--scene-in-duration", `${Math.max(140, Number(inDurationMs || 650))}ms`);
  node.style.setProperty("--scene-in-ease", String(inEasing || "cubic-bezier(0.22, 1, 0.36, 1)"));
  node.style.setProperty("--scene-out-duration", `${Math.max(120, Number(outDurationMs || 520))}ms`);
  node.style.setProperty("--scene-out-ease", String(outEasing || "ease"));

  window.requestAnimationFrame(() => {
    node.classList.add("is-visible");
  });
}

function renderActiveSlide(playOnSourceChange = true, options = {}) {
  clearSceneTimers();

  const refreshOnly = Boolean(options && options.refreshOnly);
  const skipEnterAnimation = Boolean(options && options.skipEnterAnimation);

  if (!slideDefinitions.length) {
    activeSlideType = "";
    activeSlidePayload = null;
    previousLiveStatusSnapshot = null;
    syncLiveGameHighlightPanel();
    if (slideName) {
      slideName.textContent = "Slides disabled";
    }
    slideContainer.innerHTML = '<p class="slide-empty">Slide deck is disabled in layout config.</p>';

    const sourceChanged = applyHighlightSourceForCurrentSlide();
    if (playOnSourceChange && sourceChanged && activeMode !== "live_stream") {
      playNextHighlight();
    }
    return;
  }

  if (refreshOnly && slideSwapTimer) {
    return;
  }

  const slide = slideDefinitions[slideIndex % slideDefinitions.length];
  activeSlideType = slide.type;
  activeSlidePayload = slide.payload || {};

  let liveChangeKeys = new Set();
  if (activeSlideType === "live_game_status") {
    const nextSnapshot = extractLiveStatusSnapshot(activeSlidePayload);
    liveChangeKeys = collectLiveStatusChangeKeys(previousLiveStatusSnapshot, nextSnapshot);
    previousLiveStatusSnapshot = nextSnapshot;
  } else {
    previousLiveStatusSnapshot = null;
  }

  syncLiveGameHighlightPanel();
  if (slideName) {
    slideName.textContent = slide.title || slideTitleForType(slide.type);
  }

  if (lowPowerMode) {
    const activeSlideId = String(slide.id || "");
    refreshTemplateRuntimeDataForSlide(slide, latestStatePayload)
      .then((didChange) => {
        if (!didChange || !slideDefinitions.length) {
          return;
        }
        const currentSlide = slideDefinitions[slideIndex % slideDefinitions.length];
        if (String(currentSlide?.id || "") === activeSlideId && shouldRenderCurrentSlideOnRefresh()) {
          renderActiveSlide(false, { refreshOnly: true, skipEnterAnimation: true });
        }
      })
      .catch(() => {
        // Ignore template API errors here; renderVisualTemplateSlide shows per-slide errors.
      });

    if (slideDefinitions.length > 1) {
      const nextSlide = slideDefinitions[(slideIndex + 1) % slideDefinitions.length];
      refreshTemplateRuntimeDataForSlide(nextSlide, latestStatePayload).catch(() => {
        // Ignore prefetch failures; next render pass will retry.
      });
    }
  }

  if (!renderVisualTemplateSlide(slide, { skipEnterAnimation })) {
    if (slide.type === "previous_game_pbp") {
      slideContainer.innerHTML = renderPreviousGameSlide(activeSlidePayload);
    } else if (slide.type === "featured_player") {
      slideContainer.innerHTML = renderFeaturedPlayerSlide(activeSlidePayload);
    } else if (slide.type === "game_today") {
      slideContainer.innerHTML = renderGameTodaySlide(activeSlidePayload);
    } else if (slide.type === "schedule_overview") {
      slideContainer.innerHTML = renderScheduleSlide(activeSlidePayload);
    } else if (slide.type === "upcoming_weather") {
      slideContainer.innerHTML = renderWeatherSlide(activeSlidePayload);
    } else if (slide.type === "team_hitting_leaders") {
      slideContainer.innerHTML = renderHittingLeadersSlide(activeSlidePayload);
    } else if (slide.type === "team_pitching_leaders") {
      slideContainer.innerHTML = renderPitchingLeadersSlide(activeSlidePayload);
    } else if (slide.type === "player_breakdown") {
      slideContainer.innerHTML = renderPlayerBreakdownSlide(activeSlidePayload);
    } else if (slide.type === "live_game_status") {
      slideContainer.innerHTML = renderLiveGameStatusSlide(activeSlidePayload);
    } else if (slide.type === "status") {
      slideContainer.innerHTML = renderStatusSlide(activeSlidePayload);
    } else {
      slideContainer.innerHTML = renderUnknownSlide(slide);
    }

    const fallbackNode = slideContainer.firstElementChild;
    currentSlideOutMs = Math.max(320, Math.min(1600, Number(visualSceneConfig.slideTransitionMs || 650)));
    if (skipEnterAnimation) {
      if (fallbackNode) {
        fallbackNode.classList.add("slide-surface", "is-visible");
        fallbackNode.style.setProperty("--scene-in-duration", "0ms");
        fallbackNode.style.setProperty("--scene-in-ease", "linear");
        fallbackNode.style.setProperty("--scene-out-duration", `${currentSlideOutMs}ms`);
        fallbackNode.style.setProperty("--scene-out-ease", "ease");
      }
    } else {
      animateNodeIn(fallbackNode, visualSceneConfig.slideTransitionMs, "cubic-bezier(0.22, 1, 0.36, 1)", currentSlideOutMs, "ease");
    }
  }

  if (activeSlideType === "live_game_status" && liveChangeKeys.size > 0) {
    flashLiveChangeNodes(liveChangeKeys);
  }

  const sourceChanged = applyHighlightSourceForCurrentSlide();
  if (playOnSourceChange && sourceChanged && activeMode !== "live_stream") {
    playNextHighlight();
  }
}

function clearSlideTimer() {
  if (slideTimer) {
    window.clearTimeout(slideTimer);
    slideTimer = null;
  }
  if (slideSwapTimer) {
    window.clearTimeout(slideSwapTimer);
    slideSwapTimer = null;
  }
}

function transitionToNextSlide() {
  if (!slideDefinitions.length) {
    return;
  }

  const activeNode = slideContainer.firstElementChild;
  const outMs = Math.max(280, Math.min(1800, Number(currentSlideOutMs || 650)));

  if (activeNode && (!lowPowerMode || keepLowPowerTransitions)) {
    activeNode.classList.add("is-leaving");
    const animatedElements = activeNode.querySelectorAll(".scene-el");
    for (const element of animatedElements) {
      element.classList.add("is-exiting");
    }
  }

  const lowPowerOutMs = lowPowerMode && !keepLowPowerTransitions ? 40 : outMs;
  slideSwapTimer = window.setTimeout(() => {
    slideIndex = (slideIndex + 1) % slideDefinitions.length;
    renderActiveSlide(true);
    scheduleNextSlide();
  }, lowPowerOutMs);
}

function scheduleNextSlide() {
  clearSlideTimer();
  if (!slideDefinitions.length) {
    return;
  }
  if (slideDefinitions.length <= 1) {
    return;
  }

  const currentSlide = slideDefinitions[slideIndex % slideDefinitions.length];
  const durationMs = Math.max(5000, Number(currentSlide.durationSeconds || 10) * 1000);
  const outMs = Math.max(280, Math.min(1800, Number(currentSlideOutMs || 650)));
  const holdMs = Math.max(1200, durationMs - outMs);

  slideTimer = window.setTimeout(() => {
    transitionToNextSlide();
  }, holdMs);
}

function shouldRenderCurrentSlideOnRefresh() {
  if (!slideDefinitions.length) {
    return false;
  }
  if (slideDefinitions.length <= 1) {
    return true;
  }
  const currentSlide = slideDefinitions[slideIndex % slideDefinitions.length];
  const template = currentSlide ? getVisualTemplateForSlide(currentSlide) : null;
  if (template && typeof template === "object" && String(template.apiEndpoint || "").trim()) {
    return true;
  }
  return activeSlideType === "live_game_status";
}

function restartSlideRotation(resetIndex = true) {
  clearSlideTimer();

  if (resetIndex) {
    slideIndex = 0;
  } else if (slideDefinitions.length > 0) {
    slideIndex = slideIndex % slideDefinitions.length;
  }

  renderActiveSlide(true);
  scheduleNextSlide();
}

function updateKioskPayload(kiosk) {
  kioskPayload = kiosk || {};

  const nextSlides = normalizeSlides(kioskPayload);
  const nextSignature = buildSlideLayoutSignature(nextSlides);

  if (nextSignature !== kioskLayoutSignature) {
    kioskLayoutSignature = nextSignature;
    slideDefinitions = nextSlides;
    pruneTemplateRuntimeDataBySlide();
    restartSlideRotation(true);
    return;
  }

  // Keep rotation timing stable when only payload values change.
  slideDefinitions = nextSlides;
  pruneTemplateRuntimeDataBySlide();
  if (shouldRenderCurrentSlideOnRefresh()) {
    renderActiveSlide(false, { refreshOnly: true, skipEnterAnimation: true });
  }
}

async function refreshState() {
  if (refreshStatePromise) {
    return refreshStatePromise;
  }

  refreshStatePromise = (async () => {
    try {
      await refreshVisualSceneConfig(false);

      const response = await fetch(stateUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const state = await response.json();
      latestStatePayload = state;
      const mode = state.mode || "highlights";
      const modeChanged = mode !== activeMode;
      activeMode = mode;
      currentTeamName = state.teamName || currentTeamName;

      updateModeBadge(mode);
      renderScoreboard(state.scoreboard || null);
      setBaseHighlights(state.highlights || []);
      updateKioskPayload(state.kiosk || {});

      const templateDataChanged = await refreshTemplateRuntimeData(state);
      if (templateDataChanged && slideDefinitions.length && shouldRenderCurrentSlideOnRefresh()) {
        renderActiveSlide(false, { refreshOnly: true, skipEnterAnimation: true });
      }

      updateStamp.textContent = state.generatedAtUtc
        ? `Last update: ${formatTimestamp(state.generatedAtUtc)}`
        : "Last update: unavailable";

      if (mode === "live_stream" && state.streamUrl) {
        clipTitle.textContent = "Live stream mode";
        clipMeta.textContent = "Using configured stream URL";
        noVideoMessage.classList.add("hidden");

        if (modeChanged || currentVideoKey !== state.streamUrl) {
          currentVideoKey = state.streamUrl;
          playSource(state.streamUrl);
        }
        return;
      }

      if (!currentVideoKey || modeChanged) {
        playNextHighlight();
      }
    } catch (error) {
      statusLine.textContent = "Could not refresh game state";
      detailLine.textContent = error instanceof Error ? error.message : "Unknown error";
    }
  })();

  try {
    await refreshStatePromise;
  } finally {
    refreshStatePromise = null;
  }
}

video.addEventListener("ended", () => {
  if (activeMode !== "live_stream") {
    playNextHighlight();
  }
});

video.addEventListener("error", () => {
  if (activeMode !== "live_stream") {
    playNextHighlight();
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() === "u") {
    video.muted = !video.muted;
    clipMeta.textContent = video.muted ? "Audio muted (press U to unmute)" : "Audio enabled";
  }
});

refreshVisualSceneConfig(true).finally(() => {
  refreshState();
});
startStatePolling();
startVisualTemplatePolling();
