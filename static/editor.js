const EFFECTS = ["fade", "slide-up", "slide-down", "slide-left", "slide-right", "zoom"];
const API_URL = "/api/visual-scenes";
const KIOSK_TEMPLATE_API_URL = "/api/kiosk-templates";
const STATE_API_URL = "/api/state";
const PREVIEW_LARGE_MODE_STORAGE_KEY = "padres.editor.previewLargeMode";
const EDITOR_TARGET_CANVAS_WIDTH = 1280;
const EDITOR_TARGET_CANVAS_HEIGHT = 720;

const DEFAULT_CONFIG = {
  enabled: true,
  slideTransitionMs: 650,
  elementDefaults: {
    enter: {
      effect: "slide-up",
      durationMs: 700,
      delayMs: 0,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
    },
    exit: {
      effect: "fade",
      durationMs: 460,
      delayMs: 0,
      easing: "ease",
    },
  },
  templates: {},
};

const DEFAULT_KIOSK_TEMPLATE_CONFIG = {
  enabled: true,
  defaultDurationSeconds: 14,
  templates: [],
};

const AUTO_TEMPLATE_TYPES = new Set([
  "status",
  "live_game_status",
  "game_today",
  "schedule_overview",
  "upcoming_weather",
  "team_hitting_leaders",
  "team_pitching_leaders",
  "player_breakdowns",
  "previous_game_pbp",
  "featured_player",
]);

const editorDom = {
  saveStatus: document.getElementById("saveStatus"),
  jsonPreview: document.getElementById("jsonPreview"),

  globalEnabled: document.getElementById("globalEnabled"),
  globalSlideTransitionMs: document.getElementById("globalSlideTransitionMs"),
  globalEnterEffect: document.getElementById("globalEnterEffect"),
  globalEnterDurationMs: document.getElementById("globalEnterDurationMs"),
  globalEnterDelayMs: document.getElementById("globalEnterDelayMs"),
  globalExitEffect: document.getElementById("globalExitEffect"),
  globalExitDurationMs: document.getElementById("globalExitDurationMs"),
  globalExitDelayMs: document.getElementById("globalExitDelayMs"),

  templateList: document.getElementById("templateList"),
  activeTemplateLabel: document.getElementById("activeTemplateLabel"),
  addTemplateBtn: document.getElementById("addTemplateBtn"),
  duplicateTemplateBtn: document.getElementById("duplicateTemplateBtn"),
  removeTemplateBtn: document.getElementById("removeTemplateBtn"),

  templateTransitionInEffect: document.getElementById("templateTransitionInEffect"),
  templateTransitionInDuration: document.getElementById("templateTransitionInDuration"),
  templateTransitionOutEffect: document.getElementById("templateTransitionOutEffect"),
  templateTransitionOutDuration: document.getElementById("templateTransitionOutDuration"),
  templateName: document.getElementById("templateName"),
  templateDurationSeconds: document.getElementById("templateDurationSeconds"),
  backgroundColor: document.getElementById("backgroundColor"),
  backgroundImage: document.getElementById("backgroundImage"),
  backgroundSize: document.getElementById("backgroundSize"),
  backgroundPosition: document.getElementById("backgroundPosition"),
  backgroundRepeat: document.getElementById("backgroundRepeat"),
  backgroundBlendMode: document.getElementById("backgroundBlendMode"),
  backgroundOverlay: document.getElementById("backgroundOverlay"),
  templateApiEndpoint: document.getElementById("templateApiEndpoint"),
  templateApiVariableFields: document.getElementById("templateApiVariableFields"),

  playerBreakdownControls: document.getElementById("playerBreakdownControls"),
  playerBreakdownTemplateSelect: document.getElementById("playerBreakdownTemplateSelect"),
  playerStatPreset: document.getElementById("playerStatPreset"),
  playerHitterStatPreset: document.getElementById("playerHitterStatPreset"),
  playerPitcherStatPreset: document.getElementById("playerPitcherStatPreset"),
  playerMissingStatValue: document.getElementById("playerMissingStatValue"),
  playerStatSeparator: document.getElementById("playerStatSeparator"),
  playerLabelValueSeparator: document.getElementById("playerLabelValueSeparator"),
  playerStatKeys: document.getElementById("playerStatKeys"),
  playerHitterStatKeys: document.getElementById("playerHitterStatKeys"),
  playerPitcherStatKeys: document.getElementById("playerPitcherStatKeys"),
  playerStatLabelsJson: document.getElementById("playerStatLabelsJson"),

  newElementKind: document.getElementById("newElementKind"),
  addElementBtn: document.getElementById("addElementBtn"),
  duplicateElementBtn: document.getElementById("duplicateElementBtn"),
  removeElementBtn: document.getElementById("removeElementBtn"),
  moveElementUpBtn: document.getElementById("moveElementUpBtn"),
  moveElementDownBtn: document.getElementById("moveElementDownBtn"),
  elementList: document.getElementById("elementList"),
  elementEditor: document.getElementById("elementEditor"),

  elementKind: document.getElementById("elementKind"),
  elementClassName: document.getElementById("elementClassName"),
  elementX: document.getElementById("elementX"),
  elementY: document.getElementById("elementY"),
  elementW: document.getElementById("elementW"),
  elementH: document.getElementById("elementH"),
  elementRight: document.getElementById("elementRight"),
  elementBottom: document.getElementById("elementBottom"),
  elementEnterEffect: document.getElementById("elementEnterEffect"),
  elementEnterDuration: document.getElementById("elementEnterDuration"),
  elementEnterDelay: document.getElementById("elementEnterDelay"),
  elementExitEffect: document.getElementById("elementExitEffect"),
  elementExitDuration: document.getElementById("elementExitDuration"),
  elementExitDelay: document.getElementById("elementExitDelay"),
  elementExitBeforeEnd: document.getElementById("elementExitBeforeEnd"),

  textTag: document.getElementById("textTag"),
  textValue: document.getElementById("textValue"),
  textPath: document.getElementById("textPath"),
  textFontSize: document.getElementById("textFontSize"),
  textColor: document.getElementById("textColor"),
  textFontWeight: document.getElementById("textFontWeight"),

  imageSrc: document.getElementById("imageSrc"),
  imageSrcPath: document.getElementById("imageSrcPath"),
  imageAlt: document.getElementById("imageAlt"),

  listItemsPath: document.getElementById("listItemsPath"),
  listItemsJson: document.getElementById("listItemsJson"),
  listItemsAddRowBtn: document.getElementById("listItemsAddRowBtn"),
  listItemsRemoveRowBtn: document.getElementById("listItemsRemoveRowBtn"),
  listTitleTemplate: document.getElementById("listTitleTemplate"),
  listTitleFontSize: document.getElementById("listTitleFontSize"),
  listTitleColor: document.getElementById("listTitleColor"),
  listContainerPanel: document.getElementById("listContainerPanel"),
  listColumns: document.getElementById("listColumns"),
  listGridGap: document.getElementById("listGridGap"),
  listGridAlignX: document.getElementById("listGridAlignX"),
  listGridAlignY: document.getElementById("listGridAlignY"),
  listItemImagePath: document.getElementById("listItemImagePath"),
  listItemImageAltTemplate: document.getElementById("listItemImageAltTemplate"),
  listItemImageWidth: document.getElementById("listItemImageWidth"),
  listItemImageHeight: document.getElementById("listItemImageHeight"),
  listMaxItems: document.getElementById("listMaxItems"),
  listItemTitleTemplate: document.getElementById("listItemTitleTemplate"),
  listItemSubtitleTemplate: document.getElementById("listItemSubtitleTemplate"),
  listItemTitleFontSize: document.getElementById("listItemTitleFontSize"),
  listItemTitleColor: document.getElementById("listItemTitleColor"),
  listItemTitleAlign: document.getElementById("listItemTitleAlign"),
  listItemSubtitleFontSize: document.getElementById("listItemSubtitleFontSize"),
  listItemSubtitleColor: document.getElementById("listItemSubtitleColor"),
  listItemSubtitleAlign: document.getElementById("listItemSubtitleAlign"),
  listEmptyText: document.getElementById("listEmptyText"),
  listStaggerMs: document.getElementById("listStaggerMs"),

  barValue: document.getElementById("barValue"),
  barValuePath: document.getElementById("barValuePath"),
  barMaxValue: document.getElementById("barMaxValue"),
  barLabelTemplate: document.getElementById("barLabelTemplate"),

  elementStyleJson: document.getElementById("elementStyleJson"),

  kindTextFields: document.getElementById("kindTextFields"),
  kindImageFields: document.getElementById("kindImageFields"),
  kindListFields: document.getElementById("kindListFields"),
  kindBarFields: document.getElementById("kindBarFields"),

  saveBtn: document.getElementById("saveBtn"),
  reloadBtn: document.getElementById("reloadBtn"),
  refreshRuntimeDataBtn: document.getElementById("refreshRuntimeDataBtn"),
  playRuntimePreviewBtn: document.getElementById("playRuntimePreviewBtn"),
  runtimeSlideLabel: document.getElementById("runtimeSlideLabel"),
  runtimeScrubSlider: document.getElementById("runtimeScrubSlider"),
  runtimeScrubValue: document.getElementById("runtimeScrubValue"),
  runtimePreviewStage: document.getElementById("runtimePreviewStage"),
  keySourceSelect: document.getElementById("keySourceSelect"),
  keySearchInput: document.getElementById("keySearchInput"),
  keyFinderList: document.getElementById("keyFinderList"),

  previewLayout: document.getElementById("previewLayout"),
  previewLargeMode: document.getElementById("previewLargeMode"),

  canvasShowGrid: document.getElementById("canvasShowGrid"),
  canvasSnapToggle: document.getElementById("canvasSnapToggle"),
  canvasSnapStep: document.getElementById("canvasSnapStep"),
  canvasReadout: document.getElementById("canvasReadout"),
  canvasStage: document.getElementById("canvasStage"),
  canvasBackground: document.getElementById("canvasBackground"),
  canvasOverlay: document.getElementById("canvasOverlay"),
  canvasElements: document.getElementById("canvasElements"),
};

const editorState = {
  config: deepClone(DEFAULT_CONFIG),
  kioskTemplateConfig: deepClone(DEFAULT_KIOSK_TEMPLATE_CONFIG),
  kioskMeta: {
    presets: {},
    labelOverrides: {},
  },
  selectedPlayerBreakdownTemplateId: "",
  selectedTemplateKey: "",
  selectedElementIndex: -1,
  dirty: false,
  previewState: null,
  runtimeTemplateData: {},
  keyFilterText: "",
  keySource: "payload",
  keyTreeExpandedPaths: new Set(["payload"]),
  runtimeScrubSeconds: 0,
  runtimePreviewModel: null,
  runtimeMotionFrameId: null,
  previewTimers: [],
};

const canvasState = {
  activePointerId: null,
  mode: "",
  elementIndex: -1,
  stageWidth: 0,
  stageHeight: 0,
  startClientX: 0,
  startClientY: 0,
  startRect: null,
  activeBox: null,
};

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeMotion(rawMotion, fallback) {
  const source = isPlainObject(rawMotion) ? rawMotion : {};
  const safeFallback = isPlainObject(fallback) ? fallback : {};

  return {
    effect: EFFECTS.includes(source.effect) ? source.effect : safeFallback.effect || "fade",
    durationMs: Math.max(120, Number(source.durationMs ?? safeFallback.durationMs ?? 600)),
    delayMs: Math.max(0, Number(source.delayMs ?? safeFallback.delayMs ?? 0)),
    easing: String(source.easing || safeFallback.easing || "ease"),
  };
}

function normalizeConfig(rawConfig) {
  const source = isPlainObject(rawConfig) ? rawConfig : {};
  const normalized = deepClone(DEFAULT_CONFIG);

  normalized.enabled = Boolean(source.enabled ?? normalized.enabled);
  normalized.slideTransitionMs = Math.max(200, Number(source.slideTransitionMs ?? normalized.slideTransitionMs));

  normalized.elementDefaults = {
    enter: normalizeMotion(source.elementDefaults?.enter, normalized.elementDefaults.enter),
    exit: normalizeMotion(source.elementDefaults?.exit, normalized.elementDefaults.exit),
  };

  const templates = {};
  if (Array.isArray(source.templates)) {
    source.templates.forEach((template, index) => {
      if (!isPlainObject(template)) {
        return;
      }
      const key = String(template.match || template.type || template.id || `template-${index + 1}`).trim();
      if (!key) {
        return;
      }
      templates[key] = normalizeTemplate(template);
    });
  } else if (isPlainObject(source.templates)) {
    for (const [key, template] of Object.entries(source.templates)) {
      if (!isPlainObject(template)) {
        continue;
      }
      templates[key] = normalizeTemplate(template);
    }
  }

  normalized.templates = templates;
  return normalized;
}

function normalizeKioskTemplateConfig(rawConfig) {
  const source = isPlainObject(rawConfig) ? rawConfig : {};
  const normalized = deepClone(DEFAULT_KIOSK_TEMPLATE_CONFIG);

  normalized.enabled = Boolean(source.enabled ?? normalized.enabled);
  normalized.defaultDurationSeconds = Math.max(5, Number(source.defaultDurationSeconds ?? normalized.defaultDurationSeconds));

  const templates = Array.isArray(source.templates) ? source.templates : [];
  normalized.templates = templates
    .filter((template) => isPlainObject(template))
    .map((template, index) => {
      const parsed = deepClone(template);
      const templateType = String(parsed.type || "").trim();
      if (!AUTO_TEMPLATE_TYPES.has(templateType)) {
        return null;
      }

      parsed.id = String(parsed.id || `template-${index + 1}`).trim() || `template-${index + 1}`;
      parsed.type = templateType;
      parsed.enabled = Boolean(parsed.enabled ?? true);
      parsed.durationSeconds = Math.max(5, Number(parsed.durationSeconds ?? normalized.defaultDurationSeconds));
      return parsed;
    })
    .filter((template) => template !== null);

  return normalized;
}

function normalizeTemplate(rawTemplate) {
  const template = isPlainObject(rawTemplate) ? deepClone(rawTemplate) : {};
  template.transitionIn = normalizeMotion(template.transitionIn, {
    effect: "slide-left",
    durationMs: 760,
    delayMs: 0,
    easing: "cubic-bezier(0.22, 1, 0.36, 1)",
  });
  template.transitionOut = normalizeMotion(template.transitionOut, {
    effect: "fade",
    durationMs: 520,
    delayMs: 0,
    easing: "ease",
  });

  if (!isPlainObject(template.background)) {
    template.background = {};
  }

  if (!Array.isArray(template.elements)) {
    template.elements = [];
  }

  if (template.name !== undefined) {
    const templateName = String(template.name || "").trim();
    if (templateName) {
      template.name = templateName;
    } else {
      delete template.name;
    }
  }

  if (template.apiVariables !== undefined && !isPlainObject(template.apiVariables)) {
    delete template.apiVariables;
  }

  template.elements = template.elements
    .filter((element) => isPlainObject(element))
    .map((element) => normalizeElement(element));

  return template;
}

function normalizeElement(rawElement) {
  const element = isPlainObject(rawElement) ? deepClone(rawElement) : defaultElement("text");
  if (!["text", "image", "list", "grid", "bar"].includes(String(element.kind || ""))) {
    element.kind = "text";
  }

  if (element.enter !== undefined) {
    element.enter = normalizeMotion(element.enter, { effect: "slide-up", durationMs: 700, delayMs: 0, easing: "ease" });
  }
  if (element.exit !== undefined) {
    element.exit = normalizeMotion(element.exit, { effect: "fade", durationMs: 460, delayMs: 0, easing: "ease" });
  }

  if (element.style !== undefined && !isPlainObject(element.style)) {
    delete element.style;
  }

  return element;
}

function defaultTemplate() {
  return {
    transitionIn: {
      effect: "slide-left",
      durationMs: 760,
      delayMs: 0,
      easing: "cubic-bezier(0.22, 1, 0.36, 1)",
    },
    transitionOut: {
      effect: "fade",
      durationMs: 520,
      delayMs: 0,
      easing: "ease",
    },
    background: {
      color: "linear-gradient(135deg, #0f2138 0%, #142f4f 42%, #1f4f47 100%)",
      overlay: "linear-gradient(90deg, rgba(3, 8, 16, 0.78), rgba(3, 8, 16, 0.2))",
    },
    elements: [
      {
        kind: "text",
        text: "New Slide",
        x: "6%",
        y: "12%",
        w: "56%",
        className: "scene-title",
        enter: {
          effect: "slide-right",
          durationMs: 820,
          delayMs: 120,
        },
      },
    ],
  };
}

function defaultElement(kind) {
  if (kind === "image") {
    return {
      kind: "image",
      src: "",
      alt: "Image",
      x: "62%",
      y: "20%",
      w: "30%",
      h: "60%",
      enter: { effect: "zoom", durationMs: 840, delayMs: 180 },
    };
  }

  if (kind === "grid") {
    return {
      kind: "grid",
      itemsPath: "payload.games",
      columns: 2,
      maxItems: 4,
      itemTitleTemplate: "{{item.matchup}}",
      itemSubtitleTemplate: "{{item.status}}",
      x: "5%",
      y: "24%",
      w: "90%",
      h: "66%",
      staggerMs: 70,
      enter: { effect: "slide-up", durationMs: 740, delayMs: 180 },
    };
  }

  if (kind === "list") {
    return {
      kind: "list",
      itemsPath: "payload.games",
      maxItems: 5,
      itemTitleTemplate: "{{item.matchup}}",
      itemSubtitleTemplate: "{{item.status}}",
      x: "5%",
      y: "24%",
      w: "90%",
      h: "66%",
      staggerMs: 70,
      enter: { effect: "slide-up", durationMs: 740, delayMs: 180 },
    };
  }

  if (kind === "bar") {
    return {
      kind: "bar",
      valuePath: "payload.hotMeter",
      maxValue: 100,
      labelTemplate: "Metric",
      x: "5%",
      y: "68%",
      w: "52%",
      enter: { effect: "slide-up", durationMs: 700, delayMs: 180 },
    };
  }

  return {
    kind: "text",
    text: "New text",
    x: "5%",
    y: "20%",
    w: "56%",
    className: "scene-subtitle",
    enter: { effect: "slide-up", durationMs: 700, delayMs: 120 },
  };
}

function getTemplateKeys() {
  return Object.keys(editorState.config.templates || {});
}

function generateUniqueTemplateKey(baseKey) {
  const root = String(baseKey || "template_copy").trim() || "template_copy";
  const templates = editorState.config.templates || {};
  if (!Object.prototype.hasOwnProperty.call(templates, root)) {
    return root;
  }

  let index = 2;
  while (Object.prototype.hasOwnProperty.call(templates, `${root}_${index}`)) {
    index += 1;
  }
  return `${root}_${index}`;
}

function getSelectedTemplate() {
  if (!editorState.selectedTemplateKey) {
    return null;
  }
  return editorState.config.templates?.[editorState.selectedTemplateKey] || null;
}

function getTemplateDisplayName(templateKey, templateValue) {
  const keyText = String(templateKey || "").trim();
  const customName = String(templateValue?.name || "").trim();
  if (!customName) {
    return keyText;
  }
  if (!keyText || customName === keyText) {
    return customName;
  }
  return `${customName} (${keyText})`;
}

function mapVisualTemplateKeyToAutoTemplateType(templateKey) {
  const key = String(templateKey || "").trim();
  if (!key) {
    return "";
  }
  if (key === "player_breakdown") {
    return "player_breakdowns";
  }
  return key;
}

function getLinkedKioskTemplatesForSelectedVisualTemplate() {
  const templateType = mapVisualTemplateKeyToAutoTemplateType(editorState.selectedTemplateKey);
  if (!templateType) {
    return [];
  }

  const templates = Array.isArray(editorState.kioskTemplateConfig?.templates) ? editorState.kioskTemplateConfig.templates : [];
  return templates.filter(
    (template) => isPlainObject(template) && String(template.type || "").trim() === templateType
  );
}

function getSelectedElement() {
  const template = getSelectedTemplate();
  if (!template || !Array.isArray(template.elements)) {
    return null;
  }
  if (editorState.selectedElementIndex < 0 || editorState.selectedElementIndex >= template.elements.length) {
    return null;
  }
  return template.elements[editorState.selectedElementIndex];
}

function setStatus(message, isError = false) {
  editorDom.saveStatus.textContent = message;
  editorDom.saveStatus.style.color = isError ? "#b8442f" : "#4f5f6f";
}

function parseStoredBoolean(rawValue, fallback = false) {
  const text = String(rawValue ?? "").trim().toLowerCase();
  if (!text) {
    return fallback;
  }
  if (["1", "true", "yes", "on"].includes(text)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(text)) {
    return false;
  }
  return fallback;
}

function applyPreviewLargeMode(isLarge, rerender = false) {
  const enabled = Boolean(isLarge);
  if (editorDom.previewLayout) {
    editorDom.previewLayout.classList.toggle("is-large", enabled);
  }
  if (editorDom.previewLargeMode) {
    editorDom.previewLargeMode.checked = enabled;
  }

  if (rerender) {
    renderCanvas();
    renderRuntimePreview(false);
  }
}

function initializePreviewLargeMode() {
  const defaultEnabled = true;
  let enabled = defaultEnabled;

  try {
    enabled = parseStoredBoolean(window.localStorage.getItem(PREVIEW_LARGE_MODE_STORAGE_KEY), defaultEnabled);
  } catch {
    enabled = defaultEnabled;
  }

  applyPreviewLargeMode(enabled, false);
}

function setDirty(value = true) {
  editorState.dirty = value;
  if (value) {
    setStatus("Unsaved changes.");
  } else {
    setStatus("No pending changes.");
  }
}

function ensureSelections() {
  ensurePlayerBreakdownSelection();

  const keys = getTemplateKeys();

  if (!keys.length) {
    editorState.selectedTemplateKey = "";
    editorState.selectedElementIndex = -1;
    return;
  }

  if (!keys.includes(editorState.selectedTemplateKey)) {
    editorState.selectedTemplateKey = keys[0];
    editorState.selectedElementIndex = 0;
  }

  const template = getSelectedTemplate();
  if (!template || !Array.isArray(template.elements) || !template.elements.length) {
    editorState.selectedElementIndex = -1;
    return;
  }

  if (editorState.selectedElementIndex < 0 || editorState.selectedElementIndex >= template.elements.length) {
    editorState.selectedElementIndex = 0;
  }
}

function setSelectOptions(selectNode, allowBlank = false) {
  const currentValue = selectNode.value;
  const options = [];

  if (allowBlank) {
    options.push({ value: "", label: "Inherit" });
  }

  EFFECTS.forEach((effect) => {
    options.push({ value: effect, label: effect });
  });

  selectNode.innerHTML = "";
  options.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.value;
    option.textContent = row.label;
    selectNode.appendChild(option);
  });

  if ([...selectNode.options].some((option) => option.value === currentValue)) {
    selectNode.value = currentValue;
  }
}

function initializeEffectSelects() {
  setSelectOptions(editorDom.globalEnterEffect, false);
  setSelectOptions(editorDom.globalExitEffect, false);
  setSelectOptions(editorDom.templateTransitionInEffect, false);
  setSelectOptions(editorDom.templateTransitionOutEffect, false);
  setSelectOptions(editorDom.elementEnterEffect, true);
  setSelectOptions(editorDom.elementExitEffect, true);
}

function setInputValue(inputNode, value) {
  inputNode.value = value === undefined || value === null ? "" : String(value);
}

function setMaybeStringField(target, key, value) {
  const text = String(value ?? "").trim();
  if (!text) {
    delete target[key];
    return;
  }
  target[key] = text;
}

function setMaybeRawStringField(target, key, value) {
  const text = String(value ?? "");
  if (text === "") {
    delete target[key];
    return;
  }
  target[key] = text;
}

function normalizeEndpointVariableKey(rawKey) {
  const key = String(rawKey ?? "").trim();
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
    return "";
  }
  return key;
}

function parseEndpointVariableKey(expression) {
  const token = String(expression || "").trim();
  if (!token) {
    return "";
  }

  if (token.startsWith("vars.")) {
    return normalizeEndpointVariableKey(token.slice("vars.".length));
  }

  if (token.startsWith("variables.")) {
    return normalizeEndpointVariableKey(token.slice("variables.".length));
  }

  return normalizeEndpointVariableKey(token);
}

function extractEndpointVariableKeys(endpointTemplate) {
  const rawTemplate = String(endpointTemplate || "");
  if (!rawTemplate.includes("{{")) {
    return [];
  }

  const tokenPattern = /\{\{\s*([^}]+)\s*\}\}/g;
  const keys = [];
  const seen = new Set();

  let match = tokenPattern.exec(rawTemplate);
  while (match) {
    const token = parseTemplateToken(match[1]);
    const variableKey = parseEndpointVariableKey(token.expression);
    if (variableKey && !seen.has(variableKey)) {
      seen.add(variableKey);
      keys.push(variableKey);
    }
    match = tokenPattern.exec(rawTemplate);
  }

  return keys;
}

function syncTemplateApiVariablesWithEndpoint(template) {
  if (!isPlainObject(template)) {
    return [];
  }

  const endpointVariableKeys = extractEndpointVariableKeys(template.apiEndpoint);
  if (!endpointVariableKeys.length) {
    delete template.apiVariables;
    return [];
  }

  const currentValues = isPlainObject(template.apiVariables) ? template.apiVariables : {};
  const nextValues = {};
  endpointVariableKeys.forEach((key) => {
    nextValues[key] = Object.prototype.hasOwnProperty.call(currentValues, key) ? currentValues[key] : "";
  });
  template.apiVariables = nextValues;
  return endpointVariableKeys;
}

function getTemplateApiVariableValues(template) {
  const keys = extractEndpointVariableKeys(template?.apiEndpoint);
  const sourceValues = isPlainObject(template?.apiVariables) ? template.apiVariables : {};
  const values = {};

  keys.forEach((key) => {
    values[key] = Object.prototype.hasOwnProperty.call(sourceValues, key) ? sourceValues[key] : "";
  });

  return {
    keys,
    values,
  };
}

function setMaybeNumberField(target, key, value, minValue = 0) {
  const text = String(value ?? "").trim();
  if (!text) {
    delete target[key];
    return;
  }

  const numeric = Number(text);
  if (Number.isNaN(numeric)) {
    return;
  }
  target[key] = Math.max(minValue, numeric);
}

function parseListItemsJson(rawText) {
  const text = String(rawText || "").trim();
  if (!text) {
    return [];
  }

  const parsed = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error("List Items JSON must be an array.");
  }
  return parsed;
}

function getEditableListItems(element) {
  const draftText = String(editorDom.listItemsJson?.value || "").trim();
  if (draftText) {
    return parseListItemsJson(draftText);
  }

  if (Array.isArray(element?.items)) {
    return deepClone(element.items);
  }

  return [];
}

function parseKeyList(rawValue) {
  const text = String(rawValue || "");
  const tokens = text
    .split(/[\n,]/g)
    .map((part) => part.trim())
    .filter(Boolean);

  const deduped = [];
  const seen = new Set();
  for (const token of tokens) {
    const key = token;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(key);
  }
  return deduped;
}

function keyListToText(value) {
  if (!Array.isArray(value) || !value.length) {
    return "";
  }
  return value.join(", ");
}

function setMaybeKeyArrayField(target, key, rawValue) {
  const parsed = parseKeyList(rawValue);
  if (!parsed.length) {
    delete target[key];
    return;
  }
  target[key] = parsed;
}

function getPlayerBreakdownTemplates() {
  const templates = Array.isArray(editorState.kioskTemplateConfig?.templates) ? editorState.kioskTemplateConfig.templates : [];
  return templates.filter((template) => isPlainObject(template) && String(template.type || "").trim() === "player_breakdowns");
}

function getPlayerBreakdownTemplateId(template, index) {
  const templateId = String(template?.id || "").trim();
  if (templateId) {
    return templateId;
  }
  return `player-breakdowns-${index + 1}`;
}

function getSelectedPlayerBreakdownTemplate() {
  const templates = getPlayerBreakdownTemplates();
  if (!templates.length) {
    return null;
  }

  if (!editorState.selectedPlayerBreakdownTemplateId) {
    return templates[0];
  }

  const selected = templates.find((template, index) => {
    const templateId = getPlayerBreakdownTemplateId(template, index);
    return templateId === editorState.selectedPlayerBreakdownTemplateId;
  });
  return selected || templates[0];
}

function ensurePlayerBreakdownSelection() {
  const templates = getPlayerBreakdownTemplates();
  if (!templates.length) {
    editorState.selectedPlayerBreakdownTemplateId = "";
    return;
  }

  const selectedExists = templates.some((template, index) => {
    const templateId = getPlayerBreakdownTemplateId(template, index);
    return templateId === editorState.selectedPlayerBreakdownTemplateId;
  });

  if (!selectedExists) {
    editorState.selectedPlayerBreakdownTemplateId = getPlayerBreakdownTemplateId(templates[0], 0);
  }
}

function setSelectFromArray(selectNode, values, includeBlankLabel) {
  if (!selectNode) {
    return;
  }

  const previous = String(selectNode.value || "");
  selectNode.innerHTML = "";

  if (includeBlankLabel) {
    const blankOption = document.createElement("option");
    blankOption.value = "";
    blankOption.textContent = includeBlankLabel;
    selectNode.appendChild(blankOption);
  }

  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    selectNode.appendChild(option);
  });

  if ([...selectNode.options].some((option) => option.value === previous)) {
    selectNode.value = previous;
  }
}

function clampValue(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function parseLengthToPx(rawValue, axisPixels, fallbackPixels) {
  const fallback = Number.isFinite(fallbackPixels) ? fallbackPixels : 0;
  if (rawValue === undefined || rawValue === null) {
    return fallback;
  }

  const valueText = String(rawValue).trim();
  if (!valueText) {
    return fallback;
  }

  if (valueText.endsWith("%")) {
    const numeric = Number(valueText.slice(0, -1));
    if (Number.isNaN(numeric)) {
      return fallback;
    }
    return (numeric / 100) * axisPixels;
  }

  if (valueText.endsWith("px")) {
    const numeric = Number(valueText.slice(0, -2));
    return Number.isNaN(numeric) ? fallback : numeric;
  }

  const numeric = Number(valueText);
  return Number.isNaN(numeric) ? fallback : numeric;
}

function defaultElementHeightPx(kind, stageHeight) {
  if (kind === "image") {
    return stageHeight * 0.28;
  }
  if (kind === "list" || kind === "grid") {
    return stageHeight * 0.36;
  }
  if (kind === "bar") {
    return stageHeight * 0.12;
  }
  return stageHeight * 0.13;
}

function getElementRectPx(element, stageWidth, stageHeight) {
  const kind = String(element?.kind || "text");
  const fallbackWidth = stageWidth * 0.24;
  const fallbackHeight = defaultElementHeightPx(kind, stageHeight);

  let width = parseLengthToPx(element?.w, stageWidth, fallbackWidth);
  let height = parseLengthToPx(element?.h, stageHeight, fallbackHeight);

  width = clampValue(width, stageWidth * 0.04, stageWidth);
  height = clampValue(height, stageHeight * 0.04, stageHeight);

  let left = stageWidth * 0.05;
  let top = stageHeight * 0.06;

  if (String(element?.x ?? "").trim()) {
    left = parseLengthToPx(element.x, stageWidth, left);
  } else if (String(element?.right ?? "").trim()) {
    const rightPx = parseLengthToPx(element.right, stageWidth, 0);
    left = stageWidth - rightPx - width;
  }

  if (String(element?.y ?? "").trim()) {
    top = parseLengthToPx(element.y, stageHeight, top);
  } else if (String(element?.bottom ?? "").trim()) {
    const bottomPx = parseLengthToPx(element.bottom, stageHeight, 0);
    top = stageHeight - bottomPx - height;
  }

  left = clampValue(left, 0, Math.max(0, stageWidth - width));
  top = clampValue(top, 0, Math.max(0, stageHeight - height));

  return {
    left,
    top,
    width,
    height,
  };
}

function computeSnapStepPercent() {
  const step = Number(editorDom.canvasSnapStep?.value || "1");
  if (!Number.isFinite(step) || step <= 0) {
    return 1;
  }
  return step;
}

function snapPxByPercent(pxValue, axisPixels, snapEnabled) {
  if (!snapEnabled || axisPixels <= 0) {
    return pxValue;
  }

  const step = computeSnapStepPercent();
  const rawPercent = (pxValue / axisPixels) * 100;
  const snappedPercent = Math.round(rawPercent / step) * step;
  return (snappedPercent / 100) * axisPixels;
}

function toPercentString(pxValue, axisPixels) {
  if (!Number.isFinite(pxValue) || axisPixels <= 0) {
    return "0%";
  }
  return `${((pxValue / axisPixels) * 100).toFixed(2)}%`;
}

function toTargetPxString(pxValue, stageAxisPixels, targetAxisPixels) {
  if (!Number.isFinite(pxValue) || stageAxisPixels <= 0 || targetAxisPixels <= 0) {
    return "0px";
  }
  return `${Math.round((pxValue / stageAxisPixels) * targetAxisPixels)}px`;
}

function applyRectToElement(element, rect, stageWidth, stageHeight, updateSize) {
  element.x = toPercentString(rect.left, stageWidth);
  element.y = toPercentString(rect.top, stageHeight);
  delete element.right;
  delete element.bottom;

  if (updateSize || String(element.w ?? "").trim()) {
    element.w = toPercentString(rect.width, stageWidth);
  }
  if (updateSize || String(element.h ?? "").trim()) {
    element.h = toPercentString(rect.height, stageHeight);
  }
}

function elementPreviewText(element) {
  const kind = String(element?.kind || "text");
  if (kind === "text") {
    return String(element.textPath || element.text || "Text");
  }
  if (kind === "image") {
    return String(element.srcPath || element.src || "Image");
  }
  if (kind === "list") {
    return String(element.itemsPath || "List");
  }
  if (kind === "grid") {
    return String(element.itemsPath || "Grid");
  }
  if (kind === "bar") {
    return String(element.valuePath || element.value || "Bar");
  }
  return kind;
}

function getCssBackgroundImage(rawImage) {
  const value = String(rawImage || "").trim();
  if (!value) {
    return "";
  }

  if (value.startsWith("url(") || value.startsWith("linear-gradient") || value.startsWith("radial-gradient")) {
    return value;
  }

  return `url("${value.replaceAll('"', '\\"')}")`;
}

function isGradientBackgroundValue(backgroundValue) {
  const text = String(backgroundValue || "").trim().toLowerCase();
  return text.startsWith("linear-gradient(") || text.startsWith("radial-gradient(") || text.startsWith("conic-gradient(");
}

function isUrlBackgroundValue(backgroundValue) {
  const text = String(backgroundValue || "").trim().toLowerCase();
  return text.startsWith("url(");
}

function updateCanvasReadoutForElement(element, rect) {
  if (!element || !rect) {
    editorDom.canvasReadout.textContent = "No element selected. (Target 1280x720)";
    return;
  }

  const stageWidth = canvasState.stageWidth || editorDom.canvasStage.clientWidth || 1;
  const stageHeight = canvasState.stageHeight || editorDom.canvasStage.clientHeight || 1;

  const xText = toPercentString(rect.left, stageWidth);
  const yText = toPercentString(rect.top, stageHeight);
  const wText = toPercentString(rect.width, stageWidth);
  const hText = toPercentString(rect.height, stageHeight);

  const xPxText = toTargetPxString(rect.left, stageWidth, EDITOR_TARGET_CANVAS_WIDTH);
  const yPxText = toTargetPxString(rect.top, stageHeight, EDITOR_TARGET_CANVAS_HEIGHT);
  const wPxText = toTargetPxString(rect.width, stageWidth, EDITOR_TARGET_CANVAS_WIDTH);
  const hPxText = toTargetPxString(rect.height, stageHeight, EDITOR_TARGET_CANVAS_HEIGHT);

  editorDom.canvasReadout.textContent = `x ${xText} (${xPxText}) | y ${yText} (${yPxText}) | w ${wText} (${wPxText}) | h ${hText} (${hPxText})`;
}

function updatePositionInputsFromElement(element) {
  if (!element) {
    return;
  }
  setInputValue(editorDom.elementX, element.x || "");
  setInputValue(editorDom.elementY, element.y || "");
  setInputValue(editorDom.elementW, element.w || "");
  setInputValue(editorDom.elementH, element.h || "");
  setInputValue(editorDom.elementRight, element.right || "");
  setInputValue(editorDom.elementBottom, element.bottom || "");
}

function stopRuntimePreviewMotion() {
  if (editorState.runtimeMotionFrameId !== null) {
    window.cancelAnimationFrame(editorState.runtimeMotionFrameId);
    editorState.runtimeMotionFrameId = null;
  }
}

function buildRuntimeMotionTransform(timeMs, motionLayer) {
  const durationMs = Math.max(1000, Number(motionLayer?.durationMs || 18000));
  const phase = (timeMs % durationMs) / durationMs;
  const theta = phase * Math.PI * 2;

  const shiftX = Number(motionLayer?.amplitudeXPercent || 0) * Math.sin(theta + Number(motionLayer?.phaseOffsetX || 0));
  const shiftY = Number(motionLayer?.amplitudeYPercent || 0) * Math.cos(theta * 0.86 + Number(motionLayer?.phaseOffsetY || 0));
  const baseScale = Number(motionLayer?.baseScale || 1.1);
  const scaleAmplitude = Number(motionLayer?.scaleAmplitude || 0.02);
  const scale = baseScale + scaleAmplitude * Math.sin(theta * 0.64 + Number(motionLayer?.phaseOffsetScale || 0));

  const positionX =
    50 + Number(motionLayer?.positionAmplitudeXPercent || 0) * Math.sin(theta + Number(motionLayer?.phaseOffsetX || 0));
  const positionY =
    50 + Number(motionLayer?.positionAmplitudeYPercent || 0) * Math.cos(theta * 0.82 + Number(motionLayer?.phaseOffsetY || 0));

  return {
    transform: `translate3d(${shiftX.toFixed(3)}%, ${shiftY.toFixed(3)}%, 0) scale(${scale.toFixed(4)})`,
    backgroundPosition: `${positionX.toFixed(3)}% ${positionY.toFixed(3)}%`,
  };
}

function applyRuntimePreviewMotionForTimeMs(model, timeMs) {
  const layers = Array.isArray(model?.motionLayers) ? model.motionLayers : [];
  if (!layers.length) {
    return;
  }

  for (const motionLayer of layers) {
    if (!motionLayer?.node) {
      continue;
    }
    const motionState = buildRuntimeMotionTransform(timeMs, motionLayer);
    if (motionLayer.applyTransform !== false) {
      motionLayer.node.style.transform = motionState.transform;
    }
    if (motionLayer.applyBackgroundPosition) {
      motionLayer.node.style.backgroundPosition = motionState.backgroundPosition;
    }
  }
}

function startRuntimePreviewMotion(model, startTimeMs = 0) {
  stopRuntimePreviewMotion();
  const layers = Array.isArray(model?.motionLayers) ? model.motionLayers : [];
  if (!layers.length) {
    return;
  }

  const origin = performance.now() - Math.max(0, Number(startTimeMs || 0));
  const tick = (now) => {
    const elapsedMs = Math.max(0, now - origin);
    applyRuntimePreviewMotionForTimeMs(model, elapsedMs);
    editorState.runtimeMotionFrameId = window.requestAnimationFrame(tick);
  };

  editorState.runtimeMotionFrameId = window.requestAnimationFrame(tick);
}

function clearRuntimePreviewTimers() {
  stopRuntimePreviewMotion();
  for (const timerId of editorState.previewTimers) {
    window.clearTimeout(timerId);
  }
  editorState.previewTimers = [];
}

function queueRuntimePreviewTimer(callback, delayMs) {
  const timerId = window.setTimeout(callback, Math.max(0, Number(delayMs || 0)));
  editorState.previewTimers.push(timerId);
}

function setRuntimeScrubUnavailable() {
  if (!editorDom.runtimeScrubSlider || !editorDom.runtimeScrubValue) {
    return;
  }

  editorDom.runtimeScrubSlider.disabled = true;
  editorDom.runtimeScrubSlider.min = "0";
  editorDom.runtimeScrubSlider.max = "0";
  editorDom.runtimeScrubSlider.step = "0.1";
  editorDom.runtimeScrubSlider.value = "0";
  editorDom.runtimeScrubValue.textContent = "0.0s / 0.0s";
}

function updateRuntimeScrubUi(totalSeconds, currentSeconds) {
  if (!editorDom.runtimeScrubSlider || !editorDom.runtimeScrubValue) {
    return;
  }

  const safeTotal = Number.isFinite(totalSeconds) ? Math.max(0, totalSeconds) : 0;
  const safeCurrent = Number.isFinite(currentSeconds) ? clampValue(currentSeconds, 0, safeTotal || 0) : 0;

  editorDom.runtimeScrubSlider.disabled = safeTotal <= 0;
  editorDom.runtimeScrubSlider.min = "0";
  editorDom.runtimeScrubSlider.max = safeTotal.toFixed(1);
  editorDom.runtimeScrubSlider.step = "0.1";
  editorDom.runtimeScrubSlider.value = safeCurrent.toFixed(1);
  editorDom.runtimeScrubValue.textContent = `${safeCurrent.toFixed(1)}s / ${safeTotal.toFixed(1)}s`;
}

function applyRuntimePreviewAtSeconds(seconds) {
  const model = editorState.runtimePreviewModel;
  if (!model) {
    return;
  }

  clearRuntimePreviewTimers();

  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const boundedSeconds = clampValue(safeSeconds, 0, model.playbackDurationMs / 1000);
  const timeMs = boundedSeconds * 1000;
  editorState.runtimeScrubSeconds = boundedSeconds;

  model.scene.classList.remove("is-visible", "is-leaving");
  model.scene.style.setProperty("--scene-in-duration", "0ms");
  model.scene.style.setProperty("--scene-out-duration", "0ms");
  model.scene.classList.add("is-visible");
  if (timeMs >= model.holdMs) {
    model.scene.classList.add("is-leaving");
  }

  model.renderedElements.forEach((row) => {
    const node = row.node;
    node.classList.remove("is-visible", "is-exiting");
    node.style.setProperty("--enter-duration", "0ms");
    node.style.setProperty("--exit-duration", "0ms");

    if (timeMs >= row.enterMotion.delayMs) {
      node.classList.add("is-visible");
    }

    const earlyExitStartMs = Number.isFinite(row.earlyExitAtMs) ? Math.max(0, Number(row.earlyExitAtMs || 0)) : Number.POSITIVE_INFINITY;
    const transitionExitStartMs = model.holdMs + row.exitMotion.delayMs;
    const exitStartMs = Math.min(earlyExitStartMs, transitionExitStartMs);
    if (timeMs >= exitStartMs) {
      node.classList.add("is-exiting");
    }

    if (row.listReveal) {
      applyRuntimeListRevealState(row.listReveal, timeMs - row.enterMotion.delayMs);
    }
  });

  applyRuntimePreviewMotionForTimeMs(model, timeMs);

  updateRuntimeScrubUi(model.playbackDurationMs / 1000, boundedSeconds);

  const endpointInfo = model.endpointInfo || "";
  const endpointError = model.endpointError || "";
  editorDom.runtimeSlideLabel.textContent = `Previewing ${model.slideTitle} @ ${boundedSeconds.toFixed(1)}s/${(
    model.playbackDurationMs / 1000
  ).toFixed(1)}s using ${model.sourceLine}${endpointInfo}${endpointError}`;
}

function formatSampleValue(value) {
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "undefined";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    const previewItems = value.slice(0, 2).map((item) => formatSampleValue(item)).join(", ");
    return `[${value.length}] ${previewItems}`.trim();
  }
  if (isPlainObject(value)) {
    const keys = Object.keys(value);
    return `{${keys.slice(0, 4).join(",")}${keys.length > 4 ? ",..." : ""}}`;
  }
  return String(value);
}

function getPathValue(source, path) {
  if (!path || typeof path !== "string") {
    return undefined;
  }

  const segments = path
    .split(".")
    .map((segment) => segment.trim())
    .filter(Boolean);

  let current = source;
  for (const segment of segments) {
    if (current == null || typeof current !== "object") {
      return undefined;
    }
    current = current[segment];
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

  if (token.startsWith("scoreboard.")) {
    return getPathValue(context.scoreboard, token.slice("scoreboard.".length));
  }
  if (token === "scoreboard") {
    return context.scoreboard;
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

function collectKeyRows(source, basePath, rows, depth = 0) {
  if (rows.length >= 500 || depth > 7) {
    return;
  }

  if (Array.isArray(source)) {
    rows.push({
      path: `${basePath}.length`,
      sample: String(source.length),
    });

    source.slice(0, 4).forEach((item, index) => {
      collectKeyRows(item, `${basePath}.${index}`, rows, depth + 1);
    });
    return;
  }

  if (isPlainObject(source)) {
    for (const [key, value] of Object.entries(source)) {
      const nextPath = basePath ? `${basePath}.${key}` : key;
      rows.push({
        path: nextPath,
        sample: formatSampleValue(value),
      });

      if (value !== null && typeof value === "object") {
        collectKeyRows(value, nextPath, rows, depth + 1);
      }

      if (rows.length >= 500) {
        break;
      }
    }
    return;
  }

  rows.push({
    path: basePath,
    sample: formatSampleValue(source),
  });
}

function copyText(text) {
  const value = String(text || "");
  if (!value) {
    return;
  }

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(value).catch(() => {
      // Ignore clipboard failures and fall back silently.
    });
    return;
  }

  const fallbackInput = document.createElement("textarea");
  fallbackInput.value = value;
  fallbackInput.style.position = "fixed";
  fallbackInput.style.opacity = "0";
  document.body.appendChild(fallbackInput);
  fallbackInput.focus();
  fallbackInput.select();
  document.execCommand("copy");
  fallbackInput.remove();
}

function pickRuntimeSlideForTemplate(statePayload, templateKey) {
  const slides = Array.isArray(statePayload?.kiosk?.slides) ? statePayload.kiosk.slides : [];
  if (!slides.length) {
    return null;
  }

  const key = String(templateKey || "").trim();
  if (!key) {
    return slides[0];
  }

  const exactId = slides.find((slide) => String(slide?.id || "") === key);
  if (exactId) {
    return exactId;
  }

  const exactType = slides.find((slide) => String(slide?.type || "") === key);
  if (exactType) {
    return exactType;
  }

  const lowerKey = key.toLowerCase();
  const fuzzyType = slides.find((slide) => String(slide?.type || "").toLowerCase().includes(lowerKey));
  if (fuzzyType) {
    return fuzzyType;
  }

  return slides[0];
}

function clearRuntimeTemplateDataForKey(templateKey) {
  const key = String(templateKey || "").trim();
  if (!key) {
    return;
  }
  delete editorState.runtimeTemplateData[key];
}

function buildRuntimeContextFromState(statePayload, templateKey, options = {}) {
  const safeState = isPlainObject(statePayload) ? statePayload : {};
  const runtimeSlide = pickRuntimeSlideForTemplate(safeState, templateKey);
  const template =
    isPlainObject(editorState.config?.templates) && isPlainObject(editorState.config.templates[templateKey])
      ? editorState.config.templates[templateKey]
      : null;

  const fallbackSlide = {
    id: templateKey,
    type: templateKey,
    title: templateKey || "Preview Slide",
    durationSeconds: 10,
    payload: {},
  };

  const slide = runtimeSlide || fallbackSlide;
  const slidePayload = slide.payload === undefined || slide.payload === null ? {} : slide.payload;

  const cacheKey = String(templateKey || "").trim();
  const endpointData = editorState.runtimeTemplateData[cacheKey] || null;
  const endpointPayload = endpointData && endpointData.payload !== undefined ? endpointData.payload : null;
  const hasEndpoint = Boolean(String(template?.apiEndpoint || "").trim());

  const preferSlidePayload = Boolean(options.preferSlidePayload);
  const payload = preferSlidePayload
    ? slidePayload
    : hasEndpoint
      ? endpointPayload !== null && endpointPayload !== undefined
        ? endpointPayload
        : {}
      : slidePayload;

  const resolvedPayload = payload === undefined || payload === null ? {} : payload;

  return {
    state: safeState,
    kiosk: safeState.kiosk || {},
    slide,
    payload: resolvedPayload,
    slidePayload: resolvedPayload,
    external: endpointPayload !== null && endpointPayload !== undefined ? endpointPayload : {},
    vars: isPlainObject(endpointData?.variables) ? endpointData.variables : {},
    endpoint: endpointData,
    scoreboard: safeState.scoreboard || {},
    item: null,
    index: 0,
  };
}

function getRuntimeContext() {
  return buildRuntimeContextFromState(editorState.previewState || {}, editorState.selectedTemplateKey);
}

function buildTemplateEndpointRequest(template, context) {
  const endpointTemplate = String(template?.apiEndpoint || "").trim();
  if (!endpointTemplate) {
    return null;
  }

  const endpointVariableKeys = extractEndpointVariableKeys(endpointTemplate);
  const variableDefinitions = isPlainObject(template?.apiVariables) ? template.apiVariables : {};
  const variableKeys = endpointVariableKeys.length ? endpointVariableKeys : Object.keys(variableDefinitions);

  const resolvedVariables = {};
  for (const key of variableKeys) {
    let value = Object.prototype.hasOwnProperty.call(variableDefinitions, key) ? variableDefinitions[key] : "";

    if (
      (value === undefined || value === null || (typeof value === "string" && value.trim() === "")) &&
      isPlainObject(context?.slide?.payload) &&
      Object.prototype.hasOwnProperty.call(context.slide.payload, key)
    ) {
      value = context.slide.payload[key];
    }

    const resolved = resolveInterpolatedValue(value, context);
    resolvedVariables[key] = resolved === undefined || resolved === null ? "" : resolved;
  }

  const endpointContext = {
    ...context,
    vars: resolvedVariables,
    variables: resolvedVariables,
    ...resolvedVariables,
  };
  const endpoint = String(resolveInterpolatedValue(endpointTemplate, endpointContext) || "").trim();
  if (!endpoint) {
    return null;
  }

  return {
    endpoint,
    variables: resolvedVariables,
  };
}

async function refreshSelectedTemplateRuntimeData() {
  const templateKey = String(editorState.selectedTemplateKey || "").trim();
  if (!templateKey || !editorState.previewState) {
    return;
  }

  const template = getSelectedTemplate();
  if (!template) {
    clearRuntimeTemplateDataForKey(templateKey);
    return;
  }

  const baseContext = buildRuntimeContextFromState(editorState.previewState, templateKey, { preferSlidePayload: true });
  const requestConfig = buildTemplateEndpointRequest(template, baseContext);
  if (!requestConfig) {
    clearRuntimeTemplateDataForKey(templateKey);
    return;
  }

  try {
    const response = await fetch(requestConfig.endpoint, { cache: "no-store" });
    const payload = await response.json().catch(() => null);

    if (!response.ok) {
      const detail = isPlainObject(payload) ? payload.detail || payload.error || "" : "";
      throw new Error(`Template API request failed (${response.status})${detail ? `: ${detail}` : ""}`);
    }

    editorState.runtimeTemplateData[templateKey] = {
      endpoint: requestConfig.endpoint,
      variables: requestConfig.variables,
      payload: payload === undefined ? null : payload,
      fetchedAtUtc: new Date().toISOString(),
      error: "",
    };
  } catch (error) {
    editorState.runtimeTemplateData[templateKey] = {
      endpoint: requestConfig.endpoint,
      variables: requestConfig.variables,
      payload: null,
      fetchedAtUtc: new Date().toISOString(),
      error: error instanceof Error ? error.message : "Template API request failed.",
    };
  }
}

function renderRuntimePreviewEmpty(message) {
  clearRuntimePreviewTimers();
  editorState.runtimePreviewModel = null;
  editorState.runtimeScrubSeconds = 0;
  setRuntimeScrubUnavailable();
  if (!editorDom.runtimePreviewStage) {
    return;
  }

  editorDom.runtimePreviewStage.innerHTML = "";
  const text = document.createElement("p");
  text.className = "runtime-preview-empty";
  text.textContent = message;
  editorDom.runtimePreviewStage.appendChild(text);
}

function createRuntimeTextElement(element, context) {
  const tagName = String(element.tag || "p").toLowerCase();
  const safeTag = ["p", "h2", "h3", "div", "span"].includes(tagName) ? tagName : "p";
  const node = document.createElement(safeTag);

  if (element.textPath) {
    const value = resolveExpression(element.textPath, context);
    appendInlineTemplateContent(node, value === undefined || value === null ? "" : String(value), context);
  } else {
    appendInlineTemplateContent(node, element.text || "", context);
  }

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

function createRuntimeImageElement(element, context) {
  const node = document.createElement("img");
  const source = element.srcPath
    ? resolveExpression(element.srcPath, context)
    : resolveInterpolatedValue(element.src || "", context);

  const sourceText = String(source || "").trim();
  if (sourceText) {
    node.src = sourceText;
  }
  node.alt = interpolateTemplate(element.alt || "Preview image", context);
  node.classList.add("scene-image");
  return node;
}

function createRuntimeBarElement(element, context) {
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

function resolveRuntimeListRevealConfig(element, context) {
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

function resolveRuntimeRevealValue(rawValue, rowContext) {
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

function ensureRuntimeRevealImageLayers(listReveal) {
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
  let layerMap = anchor.__runtimeRevealLayerMap;
  if (!(layerMap instanceof Map)) {
    layerMap = new Map();
    anchor.__runtimeRevealLayerMap = layerMap;
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

function setRuntimeRevealActiveImageLayer(listReveal, revealEntry) {
  ensureRuntimeRevealImageLayers(listReveal);
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

function updateRuntimeRevealTargetImage(listReveal, revealEntry) {
  if (!listReveal || !revealEntry) {
    return;
  }

  if (setRuntimeRevealActiveImageLayer(listReveal, revealEntry)) {
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
  window.requestAnimationFrame(() => {
    target.src = nextSource;
    target.dataset.revealSrc = nextSource;
    if (nextAlt) {
      target.alt = nextAlt;
    }
    target.style.opacity = "1";
  });
}

function applyRuntimeListRevealState(listReveal, elapsedMs) {
  const sourceEntries = Array.isArray(listReveal?.entries)
    ? listReveal.entries
    : Array.isArray(listReveal?.rows)
      ? listReveal.rows.map((rowNode) => ({ node: rowNode }))
      : [];
  if (!sourceEntries.length) {
    return;
  }

  const orderedEntries = orderListRevealRows(sourceEntries, listReveal.direction);
  const safeElapsedMs = Number.isFinite(elapsedMs) ? elapsedMs : -1;
  const startDelayMs = Math.max(0, Number(listReveal.startDelayMs || 0));
  const intervalMs = Math.max(1, Number(listReveal.intervalMs || 1));

  let visibleCount = 0;
  if (safeElapsedMs >= startDelayMs) {
    visibleCount = Math.min(orderedEntries.length, Math.floor((safeElapsedMs - startDelayMs) / intervalMs) + 1);
  }
  const activeIndex = visibleCount > 0 ? visibleCount - 1 : -1;
  let activeEntry = null;

  orderedEntries.forEach((entry, rowIndex) => {
    const rowNode = entry?.node;
    if (!rowNode) {
      return;
    }

    rowNode.classList.remove("scene-list-item-reveal-active");

    if (rowIndex < visibleCount) {
      rowNode.classList.remove("scene-list-item-reveal-pending");
      rowNode.classList.add("scene-list-item-reveal-visible");

      if (rowIndex === activeIndex) {
        rowNode.classList.remove("scene-list-item-reveal-complete");
        rowNode.classList.add("scene-list-item-reveal-active");
        activeEntry = entry;
      } else {
        rowNode.classList.add("scene-list-item-reveal-complete");
      }
      return;
    }

    rowNode.classList.add("scene-list-item-reveal-pending");
    rowNode.classList.remove("scene-list-item-reveal-visible", "scene-list-item-reveal-complete");
  });

  if (activeEntry) {
    updateRuntimeRevealTargetImage(listReveal, activeEntry);
  }
}

function createRuntimeListElement(element, context) {
  const kind = String(element.kind || "list").toLowerCase();
  const isGrid = kind === "grid";
  const revealConfig = resolveRuntimeListRevealConfig(element, context);
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
  const source = configuredItems !== null ? configuredItems : element.itemsPath ? resolveExpression(element.itemsPath, context) : [];
  const items = Array.isArray(source) ? source : [];
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
    empty.textContent = interpolateTemplate(element.emptyText || "No data", context);
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
      String(rowClassName)
        .split(" ")
        .map((name) => name.trim())
        .filter(Boolean)
        .forEach((name) => row.classList.add(name));
    }

    const rowStyle = rowSettings && rowSettings.style !== undefined ? rowSettings.style : element.itemStyle;
    applyRuntimeStyleObject(row, rowStyle, rowContext);

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
        const revealImageSource = resolveRuntimeRevealValue(revealConfig.imagePath, rowContext);
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
    wrapper.__runtimeListReveal = {
      entries: revealEntries,
      direction: revealConfig.direction,
      intervalMs: revealConfig.intervalMs,
      startDelayMs: revealConfig.startDelayMs,
      imageSelector: revealConfig.imageSelector,
      imageFadeMs: revealConfig.imageFadeMs,
    };
    applyRuntimeListRevealState(wrapper.__runtimeListReveal, -1);
  }

  return wrapper;
}

function applyRuntimeBounds(node, element, context) {
  const fieldMap = {
    x: "left",
    y: "top",
    w: "width",
    h: "height",
    right: "right",
    bottom: "bottom",
  };

  Object.entries(fieldMap).forEach(([sourceField, cssField]) => {
    const resolved = resolveInterpolatedValue(element[sourceField], context);
    if (resolved === undefined || resolved === null || resolved === "") {
      return;
    }
    node.style[cssField] = String(resolved);
  });
}

function applyRuntimeStyleObject(node, styleObject, context) {
  if (!isPlainObject(styleObject)) {
    return;
  }

  for (const [key, value] of Object.entries(styleObject)) {
    const resolved = resolveInterpolatedValue(value, context);
    if (resolved === undefined || resolved === null || resolved === "") {
      continue;
    }
    node.style.setProperty(key, String(resolved));
  }
}

function createRuntimeSceneElement(element, context) {
  if (Object.prototype.hasOwnProperty.call(element, "when") && !evaluateTemplateCondition(element.when, context)) {
    return null;
  }

  let node;
  const kind = String(element.kind || "text");
  if (kind === "image") {
    node = createRuntimeImageElement(element, context);
  } else if (kind === "list" || kind === "grid") {
    node = createRuntimeListElement(element, context);
  } else if (kind === "bar") {
    node = createRuntimeBarElement(element, context);
  } else {
    node = createRuntimeTextElement(element, context);
  }

  node.classList.add("runtime-el");
  if (element.className) {
    String(element.className)
      .split(" ")
      .map((name) => name.trim())
      .filter(Boolean)
      .forEach((name) => node.classList.add(name));
  }

  applyRuntimeBounds(node, element, context);
  applyRuntimeStyleObject(node, element.style, context);

  const enterMotion = normalizeMotion(element.enter, editorState.config.elementDefaults?.enter || DEFAULT_CONFIG.elementDefaults.enter);
  const exitMotion = normalizeMotion(element.exit, editorState.config.elementDefaults?.exit || DEFAULT_CONFIG.elementDefaults.exit);

  node.classList.add(`enter-${enterMotion.effect}`);
  node.classList.add(`exit-${exitMotion.effect}`);
  node.style.setProperty("--enter-duration", `${enterMotion.durationMs}ms`);
  node.style.setProperty("--enter-ease", enterMotion.easing);
  node.style.setProperty("--exit-duration", `${exitMotion.durationMs}ms`);
  node.style.setProperty("--exit-ease", exitMotion.easing);

  const listReveal = node && node.__runtimeListReveal ? node.__runtimeListReveal : null;

  return {
    node,
    enterMotion,
    exitMotion,
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

const KEY_FINDER_SOURCE_MAP = {
  payload: { valuePath: "payload", rootPath: "payload" },
  external: { valuePath: "external", rootPath: "external" },
  slidePayload: { valuePath: "payload", rootPath: "payload" },
  slide: { valuePath: "slide", rootPath: "slide" },
  vars: { valuePath: "vars", rootPath: "vars" },
  endpoint: { valuePath: "endpoint", rootPath: "endpoint" },
  kiosk: { valuePath: "kiosk", rootPath: "kiosk" },
  state: { valuePath: "state", rootPath: "state" },
  scoreboard: { valuePath: "scoreboard", rootPath: "scoreboard" },
};

const KEY_TREE_MAX_DEPTH = 48;

function normalizeKeyTreeExpandedPaths() {
  if (editorState.keyTreeExpandedPaths instanceof Set) {
    return editorState.keyTreeExpandedPaths;
  }

  const normalized = new Set();
  editorState.keyTreeExpandedPaths = normalized;
  return normalized;
}

function resetKeyTreeExpansion(rootPath) {
  const expanded = new Set();
  if (rootPath) {
    expanded.add(rootPath);
  }
  editorState.keyTreeExpandedPaths = expanded;
}

function getKeyFinderSourceContext(context) {
  const sourceDef = KEY_FINDER_SOURCE_MAP[editorState.keySource] || KEY_FINDER_SOURCE_MAP.payload;
  return {
    rootPath: sourceDef.rootPath,
    value: context?.[sourceDef.valuePath],
  };
}

function getKeyTreeValueType(value) {
  if (Array.isArray(value)) {
    return "array";
  }
  if (value === null) {
    return "null";
  }
  return typeof value;
}

function createKeyTreeNode(value, path, label, depth) {
  const node = {
    label,
    path,
    type: getKeyTreeValueType(value),
    sample: formatSampleValue(value),
    children: [],
  };

  const expandable = Array.isArray(value) || isPlainObject(value);
  if (!expandable) {
    return node;
  }

  if (depth >= KEY_TREE_MAX_DEPTH) {
    return node;
  }

  if (Array.isArray(value)) {
    const itemCount = value.length;
    node.children.push({
      label: "length",
      path: `${path}.length`,
      type: "number",
      sample: String(itemCount),
      children: [],
    });

    for (let index = 0; index < itemCount; index += 1) {
      node.children.push(
        createKeyTreeNode(value[index], `${path}.${index}`, `[${index}]`, depth + 1)
      );
    }

    return node;
  }

  const entries = Object.entries(value);
  for (const [key, childValue] of entries) {
    node.children.push(
      createKeyTreeNode(childValue, `${path}.${key}`, key, depth + 1)
    );
  }

  return node;
}

function buildKeyFinderTree(context) {
  const selectedSource = getKeyFinderSourceContext(context);
  const rootPath = selectedSource.rootPath;
  const rootNode = createKeyTreeNode(selectedSource.value, rootPath, rootPath, 0);

  return {
    rootPath,
    rootNode,
  };
}

function keyTreeNodeMatchesFilter(node, filterText) {
  if (!filterText) {
    return true;
  }

  const searchText = String(filterText).toLowerCase();
  return (
    String(node.path || "").toLowerCase().includes(searchText)
    || String(node.label || "").toLowerCase().includes(searchText)
    || String(node.sample || "").toLowerCase().includes(searchText)
  );
}

function keyTreeHasMatch(node, filterText) {
  if (!node) {
    return false;
  }
  if (keyTreeNodeMatchesFilter(node, filterText)) {
    return true;
  }
  return Array.isArray(node.children) && node.children.some((child) => keyTreeHasMatch(child, filterText));
}

function renderKeyTreeNode(node, container, options) {
  const filterText = options.filterText;
  const depth = options.depth;
  const expandedPaths = options.expandedPaths;

  const children = Array.isArray(node.children) ? node.children : [];
  const visibleChildren = filterText
    ? children.filter((child) => keyTreeHasMatch(child, filterText))
    : children;

  const selfMatches = keyTreeNodeMatchesFilter(node, filterText);
  if (filterText && !selfMatches && !visibleChildren.length) {
    return false;
  }

  const canExpand = visibleChildren.length > 0;
  const autoExpand = Boolean(filterText);
  const isExpanded = canExpand && (autoExpand || expandedPaths.has(node.path));

  const wrapper = document.createElement("article");
  wrapper.className = "key-tree-node";

  const row = document.createElement("div");
  row.className = "key-tree-row";
  row.style.setProperty("--tree-depth", String(depth));
  if (canExpand) {
    row.dataset.expandable = "1";
  }
  if (filterText && selfMatches) {
    row.classList.add("is-match");
  }

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "key-tree-toggle";
  if (canExpand) {
    toggle.textContent = isExpanded ? "▾" : "▸";
    toggle.setAttribute("aria-label", `${isExpanded ? "Collapse" : "Expand"} ${node.path}`);
  } else {
    toggle.textContent = "•";
    toggle.disabled = true;
    toggle.classList.add("is-placeholder");
  }

  const main = document.createElement("div");
  main.className = "key-tree-main";

  const path = document.createElement("p");
  path.className = "key-tree-path";
  path.textContent = node.path;

  const sample = document.createElement("p");
  sample.className = "key-tree-sample";
  sample.textContent = `${node.type}: ${node.sample || ""}`;

  main.appendChild(path);
  main.appendChild(sample);

  const actions = document.createElement("div");
  actions.className = "key-tree-actions";

  const copyPath = document.createElement("button");
  copyPath.type = "button";
  copyPath.className = "key-copy-btn";
  copyPath.textContent = "Copy path";
  copyPath.addEventListener("click", () => {
    copyText(node.path);
    setStatus(`Copied ${node.path}`);
  });

  const copyTemplate = document.createElement("button");
  copyTemplate.type = "button";
  copyTemplate.className = "key-copy-btn";
  copyTemplate.textContent = "Copy {{ }}";
  copyTemplate.addEventListener("click", () => {
    copyText(`{{${node.path}}}`);
    setStatus(`Copied {{${node.path}}}`);
  });

  actions.appendChild(copyPath);
  actions.appendChild(copyTemplate);

  row.appendChild(toggle);
  row.appendChild(main);
  row.appendChild(actions);

  if (canExpand) {
    const toggleExpansion = () => {
      if (expandedPaths.has(node.path)) {
        expandedPaths.delete(node.path);
      } else {
        expandedPaths.add(node.path);
      }
      renderKeyFinder();
    };

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleExpansion();
    });

    row.addEventListener("click", (event) => {
      if (event.target.closest(".key-tree-actions")) {
        return;
      }
      toggleExpansion();
    });
  }

  wrapper.appendChild(row);

  if (canExpand && isExpanded) {
    const childrenWrap = document.createElement("div");
    childrenWrap.className = "key-tree-children";

    visibleChildren.forEach((child) => {
      renderKeyTreeNode(child, childrenWrap, {
        filterText,
        depth: depth + 1,
        expandedPaths,
      });
    });

    wrapper.appendChild(childrenWrap);
  }

  container.appendChild(wrapper);
  return true;
}

function renderKeyFinder() {
  if (!editorDom.keyFinderList) {
    return;
  }

  editorDom.keyFinderList.innerHTML = "";
  editorDom.keyFinderList.classList.add("key-tree");

  if (!editorState.previewState) {
    const empty = document.createElement("p");
    empty.className = "key-finder-empty";
    empty.textContent = "Load runtime data to browse keys.";
    editorDom.keyFinderList.appendChild(empty);
    return;
  }

  const context = getRuntimeContext();
  const tree = buildKeyFinderTree(context);
  const filterText = String(editorState.keyFilterText || "").trim().toLowerCase();
  const expandedPaths = normalizeKeyTreeExpandedPaths();
  if (!expandedPaths.size && tree.rootPath) {
    expandedPaths.add(tree.rootPath);
  }

  const rendered = renderKeyTreeNode(tree.rootNode, editorDom.keyFinderList, {
    filterText,
    depth: 0,
    expandedPaths,
  });

  if (!rendered) {
    const empty = document.createElement("p");
    empty.className = "key-finder-empty";
    empty.textContent = "No keys match this filter.";
    editorDom.keyFinderList.appendChild(empty);
  }
}

function renderRuntimePreview(playAnimation = false) {
  if (!editorDom.runtimePreviewStage) {
    return;
  }

  clearRuntimePreviewTimers();

  const template = getSelectedTemplate();
  if (!template) {
    editorDom.runtimeSlideLabel.textContent = "No template selected.";
    renderRuntimePreviewEmpty("Select a template to preview its runtime rendering.");
    return;
  }

  if (!editorState.previewState) {
    editorDom.runtimeSlideLabel.textContent = "Runtime data not loaded.";
    renderRuntimePreviewEmpty("Use Refresh Data to pull /api/state and preview with live values.");
    return;
  }

  const context = getRuntimeContext();
  const stageNode = editorDom.runtimePreviewStage;
  stageNode.innerHTML = "";

  const transitionIn = normalizeMotion(template.transitionIn, {
    effect: "slide-left",
    durationMs: Math.max(240, Number(editorState.config.slideTransitionMs || 720)),
    delayMs: 0,
    easing: "cubic-bezier(0.22, 1, 0.36, 1)",
  });
  const transitionOut = normalizeMotion(template.transitionOut, {
    effect: "fade",
    durationMs: Math.max(220, Number(editorState.config.slideTransitionMs || 520)),
    delayMs: 0,
    easing: "ease",
  });

  const scene = document.createElement("article");
  scene.classList.add("runtime-scene");
  scene.style.setProperty("--scene-in-duration", `${transitionIn.durationMs}ms`);
  scene.style.setProperty("--scene-in-ease", transitionIn.easing);
  scene.style.setProperty("--scene-out-duration", `${transitionOut.durationMs}ms`);
  scene.style.setProperty("--scene-out-ease", transitionOut.easing);

  const motionLayers = [];

  const background = template.background || {};
  const backgroundNode = document.createElement("div");
  backgroundNode.classList.add("runtime-background");

  const bgColorResolved = resolveInterpolatedValue(background.color, context);
  const effectiveBgColor = String(bgColorResolved || "linear-gradient(135deg, #1b3650, #2a4f5d)");
  const hasGradientColor = isGradientBackgroundValue(effectiveBgColor);
  const gradientMotionDurationMs = Math.max(8000, Number(resolveInterpolatedValue(background.motionDurationMs, context) || 18000));
  const bgImage = resolveInterpolatedValue(background.image, context);
  const imageLayer = getCssBackgroundImage(bgImage);
  const hasGradientImage = isGradientBackgroundValue(imageLayer);
  const hasUrlImage = isUrlBackgroundValue(imageLayer);
  if (imageLayer) {
    backgroundNode.style.backgroundImage = `${imageLayer}, ${effectiveBgColor}`;
    backgroundNode.style.backgroundSize = `${String(resolveInterpolatedValue(background.size, context) || "cover")}, cover`;
    backgroundNode.style.backgroundPosition = `${String(resolveInterpolatedValue(background.position, context) || "center")}, center`;
    backgroundNode.style.backgroundRepeat = `${String(resolveInterpolatedValue(background.repeat, context) || "no-repeat")}, no-repeat`;
    backgroundNode.style.backgroundBlendMode = String(resolveInterpolatedValue(background.blendMode, context) || "normal");
  } else {
    backgroundNode.style.background = effectiveBgColor;
  }

  if (hasUrlImage) {
    backgroundNode.classList.add("runtime-background-image-motion");
    motionLayers.push({
      node: backgroundNode,
      durationMs: 22000,
      amplitudeXPercent: 2.4,
      amplitudeYPercent: 1.8,
      baseScale: 1.08,
      scaleAmplitude: 0.018,
      phaseOffsetX: 0,
      phaseOffsetY: 0,
      phaseOffsetScale: 0,
    });
  } else if (hasGradientColor || hasGradientImage) {
    backgroundNode.classList.add("runtime-background-gradient-motion");
    backgroundNode.style.setProperty("--runtime-gradient-motion-duration", `${gradientMotionDurationMs}ms`);
    backgroundNode.style.backgroundSize = "260% 260%";
    motionLayers.push({
      node: backgroundNode,
      durationMs: gradientMotionDurationMs,
      amplitudeXPercent: 3.5,
      amplitudeYPercent: 2.7,
      baseScale: 1.11,
      scaleAmplitude: 0.02,
      phaseOffsetX: 0,
      phaseOffsetY: 0.6,
      phaseOffsetScale: 0.2,
      applyTransform: true,
      applyBackgroundPosition: true,
      positionAmplitudeXPercent: 44,
      positionAmplitudeYPercent: 36,
    });
  } else {
    backgroundNode.style.transform = "";
  }
  backgroundNode.style.animation = "none";
  backgroundNode.style.animationPlayState = "paused";

  scene.appendChild(backgroundNode);

  const overlayValue = resolveInterpolatedValue(background.overlay, context);
  if (overlayValue) {
    const overlayNode = document.createElement("div");
    overlayNode.classList.add("runtime-overlay");
    overlayNode.style.background = String(overlayValue);
    if (isGradientBackgroundValue(overlayValue)) {
      const overlayMotionDurationMs = Math.max(
        8000,
        Number(resolveInterpolatedValue(background.overlayMotionDurationMs ?? background.motionDurationMs, context) || 16000)
      );
      overlayNode.classList.add("runtime-overlay-gradient-motion");
      overlayNode.style.setProperty("--runtime-overlay-motion-duration", `${overlayMotionDurationMs}ms`);
      overlayNode.style.backgroundSize = "240% 240%";
      motionLayers.push({
        node: overlayNode,
        durationMs: overlayMotionDurationMs,
        amplitudeXPercent: 2.8,
        amplitudeYPercent: 2.2,
        baseScale: 1.08,
        scaleAmplitude: 0.018,
        phaseOffsetX: 1.1,
        phaseOffsetY: 0.3,
        phaseOffsetScale: 0.9,
        applyTransform: true,
        applyBackgroundPosition: true,
        positionAmplitudeXPercent: 38,
        positionAmplitudeYPercent: 32,
      });
    }
    overlayNode.style.animation = "none";
    overlayNode.style.animationPlayState = "paused";
    scene.appendChild(overlayNode);
  }

  const layerNode = document.createElement("div");
  layerNode.classList.add("runtime-layer");
  scene.appendChild(layerNode);

  const slideDurationMs = Math.max(5000, Number(context.slide?.durationSeconds || 10) * 1000);
  const renderedElements = [];
  const elements = Array.isArray(template.elements) ? template.elements : [];
  elements.forEach((element) => {
    const rendered = createRuntimeSceneElement(element, context);
    if (!rendered) {
      return;
    }

    if (rendered.listReveal) {
      rendered.listReveal.sceneRoot = scene;
    }

    renderedElements.push({
      ...rendered,
      earlyExitAtMs: resolveEarlyExitAtMs(element, context, slideDurationMs, rendered.enterMotion.delayMs),
    });
    layerNode.appendChild(rendered.node);
  });

  stageNode.appendChild(scene);

  const maxEnterMs = renderedElements.reduce(
    (maxValue, row) => Math.max(maxValue, row.enterMotion.delayMs + row.enterMotion.durationMs),
    transitionIn.durationMs
  );
  const maxExitMs = renderedElements.reduce(
    (maxValue, row) => Math.max(maxValue, row.exitMotion.delayMs + row.exitMotion.durationMs),
    transitionOut.durationMs
  );
  const playbackDurationMs = Math.max(slideDurationMs, maxEnterMs + maxExitMs + 700);

  const slideTitle = String(context.slide?.title || context.slide?.type || editorState.selectedTemplateKey || "Slide");
  const sourceLine = context.slide?.id ? `${context.slide.id} | ${context.slide.type}` : editorState.selectedTemplateKey;
  const endpointInfo = context.endpoint?.endpoint ? ` | API ${context.endpoint.endpoint}` : "";
  const endpointError = context.endpoint?.error ? ` | API error: ${context.endpoint.error}` : "";
  const holdMs = Math.max(1200, playbackDurationMs - maxExitMs - 120);

  editorState.runtimePreviewModel = {
    scene,
    renderedElements,
    transitionIn,
    transitionOut,
    slideDurationMs,
    maxEnterMs,
    maxExitMs,
    holdMs,
    playbackDurationMs,
    motionLayers,
    slideTitle,
    sourceLine,
    endpointInfo,
    endpointError,
  };

  editorDom.runtimeSlideLabel.textContent = playAnimation
    ? `Playing ${slideTitle} (${Math.round(playbackDurationMs / 100) / 10}s) using ${sourceLine}${endpointInfo}${endpointError}`
    : `Previewing ${slideTitle} using ${sourceLine}${endpointInfo}${endpointError}`;

  if (!playAnimation) {
    applyRuntimePreviewAtSeconds(editorState.runtimeScrubSeconds || 0);
    return;
  }

  editorState.runtimeScrubSeconds = 0;
  updateRuntimeScrubUi(playbackDurationMs / 1000, editorState.runtimeScrubSeconds);
  startRuntimePreviewMotion(editorState.runtimePreviewModel, 0);

  window.requestAnimationFrame(() => {
    scene.classList.add("is-visible");
  });

  renderedElements.forEach((row) => {
    queueRuntimePreviewTimer(() => {
      row.node.classList.add("is-visible");
    }, row.enterMotion.delayMs);

    if (row.listReveal) {
      applyRuntimeListRevealState(row.listReveal, -1);
      const revealEntries = Array.isArray(row.listReveal.entries)
        ? row.listReveal.entries
        : Array.isArray(row.listReveal.rows)
          ? row.listReveal.rows
          : [];
      const revealStepCount = Math.max(0, revealEntries.length - 1);
      for (let step = 0; step <= revealStepCount; step += 1) {
        const revealElapsedMs = row.listReveal.startDelayMs + step * row.listReveal.intervalMs + 1;
        const revealTriggerMs = row.enterMotion.delayMs + row.listReveal.startDelayMs + step * row.listReveal.intervalMs;
        queueRuntimePreviewTimer(() => {
          applyRuntimeListRevealState(row.listReveal, revealElapsedMs);
        }, revealTriggerMs);
      }
    }
  });

  renderedElements.forEach((row) => {
    if (!Number.isFinite(row.earlyExitAtMs) || row.earlyExitAtMs < 0) {
      return;
    }
    const earlyExitStartMs = Math.max(0, Number(row.earlyExitAtMs || 0));
    queueRuntimePreviewTimer(() => {
      row.node.classList.add("is-exiting");
    }, earlyExitStartMs);
  });

  queueRuntimePreviewTimer(() => {
    scene.classList.add("is-leaving");

    renderedElements.forEach((row) => {
      queueRuntimePreviewTimer(() => {
        row.node.classList.add("is-exiting");
      }, row.exitMotion.delayMs);
    });
  }, holdMs);
}

async function refreshRuntimeData() {
  const response = await fetch(STATE_API_URL, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Runtime data load failed (${response.status})`);
  }
  editorState.previewState = await response.json();
  await refreshSelectedTemplateRuntimeData();
}

function renderTemplateList() {
  editorDom.templateList.innerHTML = "";

  const keys = getTemplateKeys();
  if (!keys.length) {
    const empty = document.createElement("p");
    empty.className = "panel-subtitle";
    empty.textContent = "No templates yet. Add one to begin.";
    editorDom.templateList.appendChild(empty);
    return;
  }

  keys.forEach((key) => {
    const template = editorState.config.templates?.[key] || null;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "template-item";
    if (key === editorState.selectedTemplateKey) {
      button.classList.add("active");
    }
    button.textContent = getTemplateDisplayName(key, template);
    button.title = key;
    button.addEventListener("click", () => {
      editorState.selectedTemplateKey = key;
      editorState.selectedElementIndex = 0;
      ensureSelections();
      renderAll();

      if (editorState.previewState) {
        refreshSelectedTemplateRuntimeData().then(() => {
          renderRuntimePreview(false);
          renderKeyFinder();
        });
      }
    });
    editorDom.templateList.appendChild(button);
  });
}

function renderGlobalForm() {
  editorDom.globalEnabled.checked = Boolean(editorState.config.enabled);
  setInputValue(editorDom.globalSlideTransitionMs, editorState.config.slideTransitionMs);

  const defaults = editorState.config.elementDefaults || {};
  const enter = defaults.enter || {};
  const exit = defaults.exit || {};

  setInputValue(editorDom.globalEnterEffect, enter.effect || "slide-up");
  setInputValue(editorDom.globalEnterDurationMs, enter.durationMs || 700);
  setInputValue(editorDom.globalEnterDelayMs, enter.delayMs || 0);

  setInputValue(editorDom.globalExitEffect, exit.effect || "fade");
  setInputValue(editorDom.globalExitDurationMs, exit.durationMs || 460);
  setInputValue(editorDom.globalExitDelayMs, exit.delayMs || 0);
}

function renderTemplateApiVariableFields(template, disabled = false) {
  const container = editorDom.templateApiVariableFields;
  if (!container) {
    return;
  }

  container.innerHTML = "";

  if (!template) {
    const empty = document.createElement("p");
    empty.className = "panel-subtitle";
    empty.textContent = "Select a template to configure API endpoint sample variables.";
    container.appendChild(empty);
    return;
  }

  const { keys, values } = getTemplateApiVariableValues(template);
  if (!keys.length) {
    const empty = document.createElement("p");
    empty.className = "panel-subtitle";
    empty.textContent = "No endpoint variables found. Use {{vars.someKey}} in API Endpoint to add sample inputs.";
    container.appendChild(empty);
    return;
  }

  keys.forEach((key) => {
    const inputId = `templateApiVar_${key}`;

    const label = document.createElement("label");
    label.setAttribute("for", inputId);
    label.textContent = `Sample ${key}`;

    const input = document.createElement("input");
    input.id = inputId;
    input.type = "text";
    input.dataset.apiVariableKey = key;
    input.placeholder = `Value for ${key}`;
    input.disabled = Boolean(disabled);
    setInputValue(input, values[key]);

    container.appendChild(label);
    container.appendChild(input);
  });
}

function renderTemplateForm() {
  const template = getSelectedTemplate();
  const hasTemplate = Boolean(template);

  if (!hasTemplate) {
    editorDom.activeTemplateLabel.textContent = "No template selected";
    [
      editorDom.templateTransitionInEffect,
      editorDom.templateTransitionInDuration,
      editorDom.templateTransitionOutEffect,
      editorDom.templateTransitionOutDuration,
      editorDom.templateName,
      editorDom.templateDurationSeconds,
      editorDom.backgroundColor,
      editorDom.backgroundImage,
      editorDom.backgroundSize,
      editorDom.backgroundPosition,
      editorDom.backgroundRepeat,
      editorDom.backgroundBlendMode,
      editorDom.backgroundOverlay,
      editorDom.templateApiEndpoint,
    ].forEach((node) => {
      setInputValue(node, "");
      node.disabled = true;
    });

    renderTemplateApiVariableFields(null, true);
    return;
  }

  editorDom.activeTemplateLabel.textContent = `Editing: ${getTemplateDisplayName(editorState.selectedTemplateKey, template)}`;

  [
    editorDom.templateTransitionInEffect,
    editorDom.templateTransitionInDuration,
    editorDom.templateTransitionOutEffect,
    editorDom.templateTransitionOutDuration,
    editorDom.templateName,
    editorDom.backgroundColor,
    editorDom.backgroundImage,
    editorDom.backgroundSize,
    editorDom.backgroundPosition,
    editorDom.backgroundRepeat,
    editorDom.backgroundBlendMode,
    editorDom.backgroundOverlay,
    editorDom.templateApiEndpoint,
  ].forEach((node) => {
    node.disabled = false;
  });

  const transitionIn = template.transitionIn || {};
  const transitionOut = template.transitionOut || {};
  const background = template.background || {};

  setInputValue(editorDom.templateTransitionInEffect, transitionIn.effect || "slide-left");
  setInputValue(editorDom.templateTransitionInDuration, transitionIn.durationMs || 760);
  setInputValue(editorDom.templateTransitionOutEffect, transitionOut.effect || "fade");
  setInputValue(editorDom.templateTransitionOutDuration, transitionOut.durationMs || 520);
  setInputValue(editorDom.templateName, template.name || "");

  const linkedKioskTemplates = getLinkedKioskTemplatesForSelectedVisualTemplate();
  if (!linkedKioskTemplates.length) {
    setInputValue(editorDom.templateDurationSeconds, "");
    editorDom.templateDurationSeconds.disabled = true;
    editorDom.templateDurationSeconds.placeholder = "No matching kiosk template";
  } else {
    const defaultDuration = Math.max(5, Number(editorState.kioskTemplateConfig?.defaultDurationSeconds || 14));
    const durations = linkedKioskTemplates.map((linkedTemplate) => {
      const rawValue = linkedTemplate.durationSeconds;
      const numeric = Number(rawValue === undefined ? defaultDuration : rawValue);
      return Number.isFinite(numeric) ? Math.max(5, numeric) : defaultDuration;
    });
    const uniqueDurations = [...new Set(durations)];

    editorDom.templateDurationSeconds.disabled = false;
    if (uniqueDurations.length === 1) {
      setInputValue(editorDom.templateDurationSeconds, uniqueDurations[0]);
      editorDom.templateDurationSeconds.placeholder = "";
    } else {
      setInputValue(editorDom.templateDurationSeconds, "");
      editorDom.templateDurationSeconds.placeholder = "Mixed values";
    }
  }

  setInputValue(editorDom.backgroundColor, background.color || "");
  setInputValue(editorDom.backgroundImage, background.image || "");
  setInputValue(editorDom.backgroundSize, background.size || "");
  setInputValue(editorDom.backgroundPosition, background.position || "");
  setInputValue(editorDom.backgroundRepeat, background.repeat || "");
  setInputValue(editorDom.backgroundBlendMode, background.blendMode || "");
  setInputValue(editorDom.backgroundOverlay, background.overlay || "");
  setInputValue(editorDom.templateApiEndpoint, template.apiEndpoint || "");
  renderTemplateApiVariableFields(template, false);
}

function renderPlayerBreakdownControls() {
  if (!editorDom.playerBreakdownControls) {
    return;
  }

  const selectedVisualKey = String(editorState.selectedTemplateKey || "").trim();
  const shouldShow = selectedVisualKey === "player_breakdown" || selectedVisualKey === "player_breakdowns";
  editorDom.playerBreakdownControls.style.display = shouldShow ? "grid" : "none";

  const templates = getPlayerBreakdownTemplates();
  editorDom.playerBreakdownTemplateSelect.innerHTML = "";
  templates.forEach((template, index) => {
    const templateId = getPlayerBreakdownTemplateId(template, index);
    const option = document.createElement("option");
    option.value = templateId;
    const title = String(template.title || templateId);
    const team = String(template.team || "padres");
    option.textContent = `${templateId} (${team}) - ${title}`;
    editorDom.playerBreakdownTemplateSelect.appendChild(option);
  });

  const hasTemplate = templates.length > 0;
  const selectedTemplate = getSelectedPlayerBreakdownTemplate();
  const selectedTemplateId = hasTemplate
    ? getPlayerBreakdownTemplateId(selectedTemplate, templates.findIndex((template) => template === selectedTemplate))
    : "";

  if (hasTemplate) {
    editorState.selectedPlayerBreakdownTemplateId = selectedTemplateId;
    editorDom.playerBreakdownTemplateSelect.value = selectedTemplateId;
  }

  const presetNames = Object.keys(editorState.kioskMeta?.presets || {}).sort();
  setSelectFromArray(editorDom.playerStatPreset, presetNames, "Custom (none)");
  setSelectFromArray(editorDom.playerHitterStatPreset, presetNames, "Use shared preset");
  setSelectFromArray(editorDom.playerPitcherStatPreset, presetNames, "Use shared preset");

  const fields = [
    editorDom.playerBreakdownTemplateSelect,
    editorDom.playerStatPreset,
    editorDom.playerHitterStatPreset,
    editorDom.playerPitcherStatPreset,
    editorDom.playerMissingStatValue,
    editorDom.playerStatSeparator,
    editorDom.playerLabelValueSeparator,
    editorDom.playerStatKeys,
    editorDom.playerHitterStatKeys,
    editorDom.playerPitcherStatKeys,
    editorDom.playerStatLabelsJson,
  ];

  fields.forEach((node) => {
    node.disabled = !hasTemplate;
  });

  if (!hasTemplate || !selectedTemplate) {
    setInputValue(editorDom.playerStatPreset, "");
    setInputValue(editorDom.playerHitterStatPreset, "");
    setInputValue(editorDom.playerPitcherStatPreset, "");
    setInputValue(editorDom.playerMissingStatValue, "");
    setInputValue(editorDom.playerStatSeparator, "");
    setInputValue(editorDom.playerLabelValueSeparator, "");
    setInputValue(editorDom.playerStatKeys, "");
    setInputValue(editorDom.playerHitterStatKeys, "");
    setInputValue(editorDom.playerPitcherStatKeys, "");
    setInputValue(editorDom.playerStatLabelsJson, "");
    return;
  }

  setInputValue(editorDom.playerStatPreset, selectedTemplate.statPreset || "");
  setInputValue(editorDom.playerHitterStatPreset, selectedTemplate.hitterStatPreset || "");
  setInputValue(editorDom.playerPitcherStatPreset, selectedTemplate.pitcherStatPreset || "");
  setInputValue(editorDom.playerMissingStatValue, selectedTemplate.missingStatValue || "");
  setInputValue(editorDom.playerStatSeparator, selectedTemplate.statSeparator || "");
  setInputValue(editorDom.playerLabelValueSeparator, selectedTemplate.statLabelValueSeparator || "");
  setInputValue(editorDom.playerStatKeys, keyListToText(selectedTemplate.statKeys));
  setInputValue(editorDom.playerHitterStatKeys, keyListToText(selectedTemplate.hitterStatKeys));
  setInputValue(editorDom.playerPitcherStatKeys, keyListToText(selectedTemplate.pitcherStatKeys));

  const labelsJson = isPlainObject(selectedTemplate.statLabels) ? JSON.stringify(selectedTemplate.statLabels, null, 2) : "";
  setInputValue(editorDom.playerStatLabelsJson, labelsJson);
}

function elementLabel(element, index) {
  const kind = String(element.kind || "text");
  if (kind === "text") {
    return `${index + 1}. text: ${String(element.textPath || element.text || "content").slice(0, 38)}`;
  }
  if (kind === "image") {
    return `${index + 1}. image: ${String(element.srcPath || element.src || "source").slice(0, 38)}`;
  }
  if (kind === "list") {
    if (Array.isArray(element.items) && element.items.length) {
      return `${index + 1}. list: inline (${element.items.length})`;
    }
    return `${index + 1}. list: ${String(element.itemsPath || "items").slice(0, 38)}`;
  }
  if (kind === "grid") {
    if (Array.isArray(element.items) && element.items.length) {
      return `${index + 1}. grid: inline (${element.items.length})`;
    }
    return `${index + 1}. grid: ${String(element.itemsPath || "items").slice(0, 38)}`;
  }
  if (kind === "bar") {
    return `${index + 1}. bar: ${String(element.valuePath || element.value || "value").slice(0, 38)}`;
  }
  return `${index + 1}. ${kind}`;
}

function renderElementList() {
  editorDom.elementList.innerHTML = "";

  const template = getSelectedTemplate();
  editorDom.removeTemplateBtn.disabled = !template;
  if (editorDom.duplicateTemplateBtn) {
    editorDom.duplicateTemplateBtn.disabled = !template;
  }
  if (!template) {
    const empty = document.createElement("p");
    empty.className = "panel-subtitle";
    empty.textContent = "Select a template to edit elements.";
    editorDom.elementList.appendChild(empty);
    return;
  }

  const elements = template.elements || [];
  if (!elements.length) {
    const empty = document.createElement("p");
    empty.className = "panel-subtitle";
    empty.textContent = "No elements in this template.";
    editorDom.elementList.appendChild(empty);
    return;
  }

  elements.forEach((element, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "element-item";
    if (index === editorState.selectedElementIndex) {
      button.classList.add("active");
    }
    button.textContent = elementLabel(element, index);
    button.addEventListener("click", () => {
      editorState.selectedElementIndex = index;
      renderAll();
    });
    editorDom.elementList.appendChild(button);
  });
}

function setKindFieldVisibility(kind) {
  editorDom.kindTextFields.style.display = kind === "text" ? "grid" : "none";
  editorDom.kindImageFields.style.display = kind === "image" ? "grid" : "none";
  editorDom.kindListFields.style.display = kind === "list" || kind === "grid" ? "grid" : "none";
  editorDom.kindBarFields.style.display = kind === "bar" ? "grid" : "none";
}

function setElementEditorEnabled(enabled) {
  const nodes = editorDom.elementEditor.querySelectorAll("input, select, textarea");
  nodes.forEach((node) => {
    node.disabled = !enabled;
  });
}

function renderElementForm() {
  const element = getSelectedElement();
  const hasElement = Boolean(element);

  setElementEditorEnabled(hasElement);
  editorDom.removeElementBtn.disabled = !hasElement;
  if (editorDom.duplicateElementBtn) {
    editorDom.duplicateElementBtn.disabled = !hasElement;
  }
  editorDom.moveElementUpBtn.disabled = !hasElement;
  editorDom.moveElementDownBtn.disabled = !hasElement;

  if (!hasElement) {
    [
      editorDom.elementKind,
      editorDom.elementClassName,
      editorDom.elementX,
      editorDom.elementY,
      editorDom.elementW,
      editorDom.elementH,
      editorDom.elementRight,
      editorDom.elementBottom,
      editorDom.elementEnterEffect,
      editorDom.elementEnterDuration,
      editorDom.elementEnterDelay,
      editorDom.elementExitEffect,
      editorDom.elementExitDuration,
      editorDom.elementExitDelay,
      editorDom.elementExitBeforeEnd,
      editorDom.textTag,
      editorDom.textValue,
      editorDom.textPath,
      editorDom.textFontSize,
      editorDom.textColor,
      editorDom.textFontWeight,
      editorDom.imageSrc,
      editorDom.imageSrcPath,
      editorDom.imageAlt,
      editorDom.listTitleTemplate,
      editorDom.listTitleFontSize,
      editorDom.listTitleColor,
      editorDom.listColumns,
      editorDom.listGridGap,
      editorDom.listGridAlignX,
      editorDom.listGridAlignY,
      editorDom.listItemsPath,
      editorDom.listItemsJson,
      editorDom.listItemImagePath,
      editorDom.listItemImageAltTemplate,
      editorDom.listItemImageWidth,
      editorDom.listItemImageHeight,
      editorDom.listMaxItems,
      editorDom.listItemTitleTemplate,
      editorDom.listItemSubtitleTemplate,
      editorDom.listItemTitleFontSize,
      editorDom.listItemTitleColor,
      editorDom.listItemTitleAlign,
      editorDom.listItemSubtitleFontSize,
      editorDom.listItemSubtitleColor,
      editorDom.listItemSubtitleAlign,
      editorDom.listEmptyText,
      editorDom.listStaggerMs,
      editorDom.barValue,
      editorDom.barValuePath,
      editorDom.barMaxValue,
      editorDom.barLabelTemplate,
      editorDom.elementStyleJson,
    ].forEach((node) => {
      setInputValue(node, "");
    });
    editorDom.listContainerPanel.checked = false;
    setKindFieldVisibility("");
    return;
  }

  setInputValue(editorDom.elementKind, element.kind || "text");
  setInputValue(editorDom.elementClassName, element.className || "");
  setInputValue(editorDom.elementX, element.x || "");
  setInputValue(editorDom.elementY, element.y || "");
  setInputValue(editorDom.elementW, element.w || "");
  setInputValue(editorDom.elementH, element.h || "");
  setInputValue(editorDom.elementRight, element.right || "");
  setInputValue(editorDom.elementBottom, element.bottom || "");

  setInputValue(editorDom.elementEnterEffect, element.enter?.effect || "");
  setInputValue(editorDom.elementEnterDuration, element.enter?.durationMs || "");
  setInputValue(editorDom.elementEnterDelay, element.enter?.delayMs || "");
  setInputValue(editorDom.elementExitEffect, element.exit?.effect || "");
  setInputValue(editorDom.elementExitDuration, element.exit?.durationMs || "");
  setInputValue(editorDom.elementExitDelay, element.exit?.delayMs || "");
  const exitBeforeEndMs = element.exitBeforeSlideEndMs ?? element.exitLeadMs;
  setInputValue(
    editorDom.elementExitBeforeEnd,
    exitBeforeEndMs === undefined || exitBeforeEndMs === null ? "" : exitBeforeEndMs
  );

  setInputValue(editorDom.textTag, element.tag || "");
  setInputValue(editorDom.textValue, element.text || "");
  setInputValue(editorDom.textPath, element.textPath || "");
  setInputValue(editorDom.textFontSize, element.textFontSize || element.fontSize || "");
  setInputValue(editorDom.textColor, element.textColor || element.color || "");
  setInputValue(editorDom.textFontWeight, element.textFontWeight || element.fontWeight || "");

  setInputValue(editorDom.imageSrc, element.src || "");
  setInputValue(editorDom.imageSrcPath, element.srcPath || "");
  setInputValue(editorDom.imageAlt, element.alt || "");

  setInputValue(editorDom.listTitleTemplate, element.titleTemplate || element.title || "");
  setInputValue(editorDom.listTitleFontSize, element.titleFontSize || "");
  setInputValue(editorDom.listTitleColor, element.titleColor || "");
  editorDom.listContainerPanel.checked = Boolean(element.containerPanel);
  setInputValue(editorDom.listColumns, element.columns || element.gridColumns || "");
  setInputValue(editorDom.listGridGap, element.gridGap || element.gap || "");
  setInputValue(editorDom.listGridAlignX, element.gridAlignX || "");
  setInputValue(editorDom.listGridAlignY, element.gridAlignY || "");
  setInputValue(editorDom.listItemsPath, element.itemsPath || "");
  setInputValue(editorDom.listItemsJson, Array.isArray(element.items) ? JSON.stringify(element.items, null, 2) : "");
  setInputValue(editorDom.listItemImagePath, element.itemImagePath || "");
  setInputValue(editorDom.listItemImageAltTemplate, element.itemImageAltTemplate || "");
  setInputValue(editorDom.listItemImageWidth, element.itemImageWidth || element.itemImageSize || "");
  setInputValue(editorDom.listItemImageHeight, element.itemImageHeight || element.itemImageSize || "");
  setInputValue(editorDom.listMaxItems, element.maxItems || "");
  setInputValue(editorDom.listItemTitleTemplate, element.itemTitleTemplate || "");
  setInputValue(editorDom.listItemSubtitleTemplate, element.itemSubtitleTemplate || "");
  setInputValue(editorDom.listItemTitleFontSize, element.itemTitleFontSize || "");
  setInputValue(editorDom.listItemTitleColor, element.itemTitleColor || "");
  setInputValue(editorDom.listItemTitleAlign, element.itemTitleAlign || element.itemTitleTextAlign || "");
  setInputValue(editorDom.listItemSubtitleFontSize, element.itemSubtitleFontSize || "");
  setInputValue(editorDom.listItemSubtitleColor, element.itemSubtitleColor || "");
  setInputValue(editorDom.listItemSubtitleAlign, element.itemSubtitleAlign || element.itemSubtitleTextAlign || "");
  setInputValue(editorDom.listEmptyText, element.emptyText || "");
  setInputValue(editorDom.listStaggerMs, element.staggerMs || "");

  setInputValue(editorDom.barValue, element.value || "");
  setInputValue(editorDom.barValuePath, element.valuePath || "");
  setInputValue(editorDom.barMaxValue, element.maxValue || "");
  setInputValue(editorDom.barLabelTemplate, element.labelTemplate || "");

  setInputValue(editorDom.elementStyleJson, element.style ? JSON.stringify(element.style, null, 2) : "");

  setKindFieldVisibility(String(element.kind || "text"));
}

function applyCanvasBackground(template) {
  const background = template?.background || {};
  const baseLayer = String(background.color || "linear-gradient(135deg, #18324a, #234a57)");
  const imageLayer = getCssBackgroundImage(background.image);

  if (imageLayer) {
    editorDom.canvasBackground.style.backgroundImage = `${imageLayer}, ${baseLayer}`;
    editorDom.canvasBackground.style.backgroundSize = `${String(background.size || "cover")}, cover`;
    editorDom.canvasBackground.style.backgroundPosition = `${String(background.position || "center")}, center`;
    editorDom.canvasBackground.style.backgroundRepeat = `${String(background.repeat || "no-repeat")}, no-repeat`;
    editorDom.canvasBackground.style.backgroundBlendMode = String(background.blendMode || "normal");
  } else {
    editorDom.canvasBackground.style.background = baseLayer;
    editorDom.canvasBackground.style.backgroundImage = "";
    editorDom.canvasBackground.style.backgroundSize = "";
    editorDom.canvasBackground.style.backgroundPosition = "";
    editorDom.canvasBackground.style.backgroundRepeat = "";
    editorDom.canvasBackground.style.backgroundBlendMode = "";
  }

  const overlay = String(background.overlay || "").trim();
  editorDom.canvasOverlay.style.background = overlay || "transparent";
}

function beginCanvasInteraction(event, elementIndex, mode, boxNode) {
  if (event.button !== 0) {
    return;
  }

  const template = getSelectedTemplate();
  if (!template || !Array.isArray(template.elements) || !template.elements[elementIndex]) {
    return;
  }

  event.preventDefault();
  event.stopPropagation();

  if (editorState.selectedElementIndex !== elementIndex) {
    editorState.selectedElementIndex = elementIndex;
    renderElementList();
    renderElementForm();

    const canvasBoxes = editorDom.canvasElements?.querySelectorAll(".canvas-element-box") || [];
    canvasBoxes.forEach((node) => node.classList.remove("is-selected"));
    boxNode?.classList.add("is-selected");
  }

  const stageWidth = editorDom.canvasStage.clientWidth;
  const stageHeight = editorDom.canvasStage.clientHeight;
  const element = template.elements[elementIndex];
  const startRect = getElementRectPx(element, stageWidth, stageHeight);

  canvasState.activePointerId = event.pointerId;
  canvasState.mode = mode;
  canvasState.elementIndex = elementIndex;
  canvasState.stageWidth = stageWidth;
  canvasState.stageHeight = stageHeight;
  canvasState.startClientX = event.clientX;
  canvasState.startClientY = event.clientY;
  canvasState.startRect = startRect;
  canvasState.activeBox = boxNode;

  updateCanvasReadoutForElement(element, startRect);

  if (boxNode && typeof boxNode.setPointerCapture === "function") {
    try {
      boxNode.setPointerCapture(event.pointerId);
    } catch {
      // Ignore capture failures in unsupported browsers.
    }
  }
}

function handleCanvasPointerMove(event) {
  if (canvasState.activePointerId === null || event.pointerId !== canvasState.activePointerId) {
    return;
  }

  const template = getSelectedTemplate();
  if (!template || !Array.isArray(template.elements)) {
    return;
  }

  const element = template.elements[canvasState.elementIndex];
  if (!element) {
    return;
  }

  event.preventDefault();

  const dx = event.clientX - canvasState.startClientX;
  const dy = event.clientY - canvasState.startClientY;
  const minWidth = canvasState.stageWidth * 0.04;
  const minHeight = canvasState.stageHeight * 0.04;

  const nextRect = {
    left: canvasState.startRect.left,
    top: canvasState.startRect.top,
    width: canvasState.startRect.width,
    height: canvasState.startRect.height,
  };

  if (canvasState.mode === "resize") {
    nextRect.width = clampValue(canvasState.startRect.width + dx, minWidth, canvasState.stageWidth - canvasState.startRect.left);
    nextRect.height = clampValue(
      canvasState.startRect.height + dy,
      minHeight,
      canvasState.stageHeight - canvasState.startRect.top
    );
  } else {
    nextRect.left = clampValue(canvasState.startRect.left + dx, 0, canvasState.stageWidth - canvasState.startRect.width);
    nextRect.top = clampValue(canvasState.startRect.top + dy, 0, canvasState.stageHeight - canvasState.startRect.height);
  }

  const snapEnabled = Boolean(editorDom.canvasSnapToggle?.checked) && !event.altKey;
  nextRect.left = snapPxByPercent(nextRect.left, canvasState.stageWidth, snapEnabled);
  nextRect.top = snapPxByPercent(nextRect.top, canvasState.stageHeight, snapEnabled);
  if (canvasState.mode === "resize") {
    nextRect.width = snapPxByPercent(nextRect.width, canvasState.stageWidth, snapEnabled);
    nextRect.height = snapPxByPercent(nextRect.height, canvasState.stageHeight, snapEnabled);
  }

  nextRect.left = clampValue(nextRect.left, 0, canvasState.stageWidth - nextRect.width);
  nextRect.top = clampValue(nextRect.top, 0, canvasState.stageHeight - nextRect.height);

  applyRectToElement(element, nextRect, canvasState.stageWidth, canvasState.stageHeight, canvasState.mode === "resize");

  if (!editorState.dirty) {
    setDirty(true);
  }

  if (canvasState.activeBox) {
    canvasState.activeBox.style.left = `${nextRect.left}px`;
    canvasState.activeBox.style.top = `${nextRect.top}px`;
    canvasState.activeBox.style.width = `${nextRect.width}px`;
    canvasState.activeBox.style.height = `${nextRect.height}px`;
  }

  updatePositionInputsFromElement(element);
  updateCanvasReadoutForElement(element, nextRect);
  renderPreview();
}

function handleCanvasPointerUp(event) {
  if (canvasState.activePointerId === null || event.pointerId !== canvasState.activePointerId) {
    return;
  }

  if (canvasState.activeBox && typeof canvasState.activeBox.releasePointerCapture === "function") {
    try {
      canvasState.activeBox.releasePointerCapture(event.pointerId);
    } catch {
      // Ignore release failures when capture was not set.
    }
  }

  canvasState.activePointerId = null;
  canvasState.mode = "";
  canvasState.elementIndex = -1;
  canvasState.stageWidth = 0;
  canvasState.stageHeight = 0;
  canvasState.startRect = null;
  canvasState.activeBox = null;

  renderAll();
}

function renderCanvas() {
  if (!editorDom.canvasStage || !editorDom.canvasElements) {
    return;
  }

  editorDom.canvasStage.classList.toggle("grid-on", Boolean(editorDom.canvasShowGrid?.checked));

  const template = getSelectedTemplate();
  editorDom.canvasElements.innerHTML = "";

  if (!template) {
    editorDom.canvasBackground.style.background = "linear-gradient(135deg, #18324a, #234a57)";
    editorDom.canvasOverlay.style.background = "transparent";
    editorDom.canvasReadout.textContent = "No template selected.";
    return;
  }

  applyCanvasBackground(template);

  const stageWidth = Math.max(1, editorDom.canvasStage.clientWidth);
  const stageHeight = Math.max(1, editorDom.canvasStage.clientHeight);
  const elements = Array.isArray(template.elements) ? template.elements : [];

  if (!elements.length) {
    editorDom.canvasReadout.textContent = "No elements in this template.";
    return;
  }

  let selectedRect = null;

  elements.forEach((element, index) => {
    const rect = getElementRectPx(element, stageWidth, stageHeight);

    const box = document.createElement("div");
    box.className = "canvas-element-box";
    if (index === editorState.selectedElementIndex) {
      box.classList.add("is-selected");
      selectedRect = rect;
    }
    box.style.left = `${rect.left}px`;
    box.style.top = `${rect.top}px`;
    box.style.width = `${rect.width}px`;
    box.style.height = `${rect.height}px`;

    const label = document.createElement("div");
    label.className = "canvas-element-label";
    label.textContent = elementLabel(element, index);

    const content = document.createElement("div");
    content.className = "canvas-element-content";
    content.textContent = elementPreviewText(element);

    const resize = document.createElement("button");
    resize.type = "button";
    resize.className = "canvas-resize-handle";
    resize.title = "Drag to resize";

    box.addEventListener("pointerdown", (event) => {
      beginCanvasInteraction(event, index, "move", box);
    });

    resize.addEventListener("pointerdown", (event) => {
      beginCanvasInteraction(event, index, "resize", box);
    });

    box.appendChild(label);
    box.appendChild(content);
    box.appendChild(resize);
    editorDom.canvasElements.appendChild(box);
  });

  const selectedElement = getSelectedElement();
  if (selectedElement && selectedRect) {
    updateCanvasReadoutForElement(selectedElement, selectedRect);
  } else {
    editorDom.canvasReadout.textContent = "Select an element to drag or resize.";
  }
}

function renderPreview() {
  editorDom.jsonPreview.value = JSON.stringify(
    {
      visualScenes: editorState.config,
      kioskTemplates: editorState.kioskTemplateConfig,
    },
    null,
    2
  );
}

function renderAll() {
  ensureSelections();
  renderGlobalForm();
  renderTemplateList();
  renderTemplateForm();
  renderPlayerBreakdownControls();
  renderElementList();
  renderElementForm();
  renderCanvas();
  renderRuntimePreview(false);
  renderKeyFinder();
  renderPreview();
}

function markDirtyAndRender() {
  setDirty(true);
  renderAll();
}

async function loadConfig() {
  setStatus("Loading templates...");
  const response = await fetch(API_URL, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Load failed (${response.status})`);
  }

  const payload = await response.json();
  editorState.config = normalizeConfig(payload.config || {});
  editorState.runtimeTemplateData = {};
  editorState.selectedTemplateKey = getTemplateKeys()[0] || "";
  editorState.selectedElementIndex = 0;
  setDirty(false);
  renderAll();
}

async function loadKioskTemplateConfig() {
  const response = await fetch(KIOSK_TEMPLATE_API_URL, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Kiosk template load failed (${response.status})`);
  }

  const payload = await response.json();
  editorState.kioskTemplateConfig = normalizeKioskTemplateConfig(payload.config || {});
  editorState.kioskMeta = {
    presets: isPlainObject(payload.presets) ? payload.presets : {},
    labelOverrides: isPlainObject(payload.labelOverrides) ? payload.labelOverrides : {},
  };
  ensurePlayerBreakdownSelection();
}

async function loadAllConfigs() {
  await Promise.all([loadConfig(), loadKioskTemplateConfig()]);
  setDirty(false);
  renderAll();
  setStatus("Templates loaded.");
}

async function saveConfig() {
  const response = await fetch(API_URL, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ config: editorState.config }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `Save failed (${response.status})`;
    throw new Error(detail);
  }

  editorState.config = normalizeConfig(payload.config || editorState.config);
}

async function saveKioskTemplateConfig() {
  const response = await fetch(KIOSK_TEMPLATE_API_URL, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ config: editorState.kioskTemplateConfig }),
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload.error || `Kiosk template save failed (${response.status})`;
    throw new Error(detail);
  }

  editorState.kioskTemplateConfig = normalizeKioskTemplateConfig(payload.config || editorState.kioskTemplateConfig);
}

async function saveAllConfigs() {
  setStatus("Saving templates...");
  await Promise.all([saveConfig(), saveKioskTemplateConfig()]);
  setDirty(false);
  renderAll();
  setStatus(`Saved at ${new Date().toLocaleTimeString()}.`);
}

function bindGlobalHandlers() {
  editorDom.globalEnabled.addEventListener("change", () => {
    editorState.config.enabled = editorDom.globalEnabled.checked;
    markDirtyAndRender();
  });

  editorDom.globalSlideTransitionMs.addEventListener("input", () => {
    editorState.config.slideTransitionMs = Math.max(200, Number(editorDom.globalSlideTransitionMs.value || 650));
    markDirtyAndRender();
  });

  editorDom.globalEnterEffect.addEventListener("change", () => {
    editorState.config.elementDefaults.enter.effect = editorDom.globalEnterEffect.value;
    markDirtyAndRender();
  });

  editorDom.globalEnterDurationMs.addEventListener("input", () => {
    editorState.config.elementDefaults.enter.durationMs = Math.max(120, Number(editorDom.globalEnterDurationMs.value || 700));
    markDirtyAndRender();
  });

  editorDom.globalEnterDelayMs.addEventListener("input", () => {
    editorState.config.elementDefaults.enter.delayMs = Math.max(0, Number(editorDom.globalEnterDelayMs.value || 0));
    markDirtyAndRender();
  });

  editorDom.globalExitEffect.addEventListener("change", () => {
    editorState.config.elementDefaults.exit.effect = editorDom.globalExitEffect.value;
    markDirtyAndRender();
  });

  editorDom.globalExitDurationMs.addEventListener("input", () => {
    editorState.config.elementDefaults.exit.durationMs = Math.max(120, Number(editorDom.globalExitDurationMs.value || 460));
    markDirtyAndRender();
  });

  editorDom.globalExitDelayMs.addEventListener("input", () => {
    editorState.config.elementDefaults.exit.delayMs = Math.max(0, Number(editorDom.globalExitDelayMs.value || 0));
    markDirtyAndRender();
  });
}

function bindTemplateHandlers() {
  editorDom.addTemplateBtn.addEventListener("click", () => {
    const newKeyRaw = window.prompt("Template key (example: schedule_overview)", "new_template");
    if (!newKeyRaw) {
      return;
    }

    const newKey = newKeyRaw.trim();
    if (!newKey) {
      return;
    }
    if (editorState.config.templates[newKey]) {
      window.alert("A template with that key already exists.");
      return;
    }

    const createdTemplate = defaultTemplate();
    createdTemplate.name = newKey;
    editorState.config.templates[newKey] = createdTemplate;
    editorState.selectedTemplateKey = newKey;
    editorState.selectedElementIndex = 0;
    markDirtyAndRender();
  });

  editorDom.duplicateTemplateBtn?.addEventListener("click", () => {
    const key = String(editorState.selectedTemplateKey || "").trim();
    const sourceTemplate = getSelectedTemplate();
    if (!key || !sourceTemplate) {
      return;
    }

    const defaultCopyKey = generateUniqueTemplateKey(`${key}_copy`);
    const newKeyRaw = window.prompt("Duplicate template key", defaultCopyKey);
    if (newKeyRaw === null) {
      return;
    }

    const newKey = newKeyRaw.trim();
    if (!newKey) {
      window.alert("Template key is required.");
      return;
    }

    if (editorState.config.templates[newKey]) {
      window.alert("A template with that key already exists.");
      return;
    }

    const duplicateTemplate = deepClone(sourceTemplate);
    const sourceName = String(sourceTemplate.name || key).trim();
    if (sourceName) {
      duplicateTemplate.name = `${sourceName} Copy`;
    }

    editorState.config.templates[newKey] = duplicateTemplate;
    clearRuntimeTemplateDataForKey(newKey);
    editorState.selectedTemplateKey = newKey;
    editorState.selectedElementIndex = 0;
    markDirtyAndRender();

    if (editorState.previewState) {
      refreshSelectedTemplateRuntimeData().then(() => {
        renderRuntimePreview(false);
        renderKeyFinder();
      });
    }
  });

  editorDom.removeTemplateBtn.addEventListener("click", () => {
    const key = editorState.selectedTemplateKey;
    if (!key) {
      return;
    }

    const confirmed = window.confirm(`Remove template '${key}'?`);
    if (!confirmed) {
      return;
    }

    clearRuntimeTemplateDataForKey(key);
    delete editorState.config.templates[key];
    editorState.selectedTemplateKey = "";
    editorState.selectedElementIndex = -1;
    markDirtyAndRender();
  });

  const updateTemplate = (mutator) => {
    const template = getSelectedTemplate();
    if (!template) {
      return;
    }
    mutator(template);
    markDirtyAndRender();
  };

  const updatePlayerBreakdownTemplate = (mutator) => {
    const template = getSelectedPlayerBreakdownTemplate();
    if (!template) {
      return;
    }
    mutator(template);
    markDirtyAndRender();
  };

  editorDom.templateTransitionInEffect.addEventListener("change", () => {
    updateTemplate((template) => {
      template.transitionIn = template.transitionIn || {};
      template.transitionIn.effect = editorDom.templateTransitionInEffect.value;
    });
  });

  editorDom.templateTransitionInDuration.addEventListener("input", () => {
    updateTemplate((template) => {
      template.transitionIn = template.transitionIn || {};
      template.transitionIn.durationMs = Math.max(120, Number(editorDom.templateTransitionInDuration.value || 760));
    });
  });

  editorDom.templateTransitionOutEffect.addEventListener("change", () => {
    updateTemplate((template) => {
      template.transitionOut = template.transitionOut || {};
      template.transitionOut.effect = editorDom.templateTransitionOutEffect.value;
    });
  });

  editorDom.templateTransitionOutDuration.addEventListener("input", () => {
    updateTemplate((template) => {
      template.transitionOut = template.transitionOut || {};
      template.transitionOut.durationMs = Math.max(120, Number(editorDom.templateTransitionOutDuration.value || 520));
    });
  });

  editorDom.templateName.addEventListener("input", () => {
    updateTemplate((template) => {
      setMaybeStringField(template, "name", editorDom.templateName.value);
    });
  });

  editorDom.templateDurationSeconds.addEventListener("input", () => {
    const linkedTemplates = getLinkedKioskTemplatesForSelectedVisualTemplate();
    if (!linkedTemplates.length) {
      return;
    }

    const rawValue = String(editorDom.templateDurationSeconds.value || "").trim();
    if (!rawValue) {
      linkedTemplates.forEach((linkedTemplate) => {
        delete linkedTemplate.durationSeconds;
      });
      markDirtyAndRender();
      return;
    }

    const numeric = Number(rawValue);
    if (Number.isNaN(numeric)) {
      return;
    }

    const durationSeconds = Math.max(5, Math.round(numeric));
    linkedTemplates.forEach((linkedTemplate) => {
      linkedTemplate.durationSeconds = durationSeconds;
    });
    markDirtyAndRender();
  });

  const backgroundMap = [
    [editorDom.backgroundColor, "color"],
    [editorDom.backgroundImage, "image"],
    [editorDom.backgroundSize, "size"],
    [editorDom.backgroundPosition, "position"],
    [editorDom.backgroundRepeat, "repeat"],
    [editorDom.backgroundBlendMode, "blendMode"],
    [editorDom.backgroundOverlay, "overlay"],
  ];

  backgroundMap.forEach(([inputNode, fieldName]) => {
    inputNode.addEventListener("input", () => {
      updateTemplate((template) => {
        template.background = template.background || {};
        setMaybeStringField(template.background, fieldName, inputNode.value);
      });
    });
  });

  editorDom.templateApiEndpoint.addEventListener("input", () => {
    updateTemplate((template) => {
      setMaybeStringField(template, "apiEndpoint", editorDom.templateApiEndpoint.value);
      syncTemplateApiVariablesWithEndpoint(template);
      clearRuntimeTemplateDataForKey(editorState.selectedTemplateKey);
    });
  });

  editorDom.templateApiVariableFields?.addEventListener("input", (event) => {
    const inputNode = event.target;
    if (!(inputNode instanceof HTMLInputElement)) {
      return;
    }

    const variableKey = normalizeEndpointVariableKey(inputNode.dataset.apiVariableKey || "");
    if (!variableKey) {
      return;
    }

    const template = getSelectedTemplate();
    if (!template) {
      return;
    }

    syncTemplateApiVariablesWithEndpoint(template);
    if (!isPlainObject(template.apiVariables)) {
      template.apiVariables = {};
    }
    template.apiVariables[variableKey] = String(inputNode.value ?? "");

    clearRuntimeTemplateDataForKey(editorState.selectedTemplateKey);
    setDirty(true);
    renderPreview();
  });

  editorDom.playerBreakdownTemplateSelect?.addEventListener("change", () => {
    editorState.selectedPlayerBreakdownTemplateId = String(editorDom.playerBreakdownTemplateSelect.value || "");
    renderAll();
  });

  editorDom.playerStatPreset?.addEventListener("change", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeStringField(template, "statPreset", editorDom.playerStatPreset.value);
    });
  });

  editorDom.playerHitterStatPreset?.addEventListener("change", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeStringField(template, "hitterStatPreset", editorDom.playerHitterStatPreset.value);
    });
  });

  editorDom.playerPitcherStatPreset?.addEventListener("change", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeStringField(template, "pitcherStatPreset", editorDom.playerPitcherStatPreset.value);
    });
  });

  editorDom.playerMissingStatValue?.addEventListener("input", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeStringField(template, "missingStatValue", editorDom.playerMissingStatValue.value);
    });
  });

  editorDom.playerStatSeparator?.addEventListener("input", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeRawStringField(template, "statSeparator", editorDom.playerStatSeparator.value);
    });
  });

  editorDom.playerLabelValueSeparator?.addEventListener("input", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeRawStringField(template, "statLabelValueSeparator", editorDom.playerLabelValueSeparator.value);
    });
  });

  editorDom.playerStatKeys?.addEventListener("input", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeKeyArrayField(template, "statKeys", editorDom.playerStatKeys.value);
    });
  });

  editorDom.playerHitterStatKeys?.addEventListener("input", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeKeyArrayField(template, "hitterStatKeys", editorDom.playerHitterStatKeys.value);
    });
  });

  editorDom.playerPitcherStatKeys?.addEventListener("input", () => {
    updatePlayerBreakdownTemplate((template) => {
      setMaybeKeyArrayField(template, "pitcherStatKeys", editorDom.playerPitcherStatKeys.value);
    });
  });

  editorDom.playerStatLabelsJson?.addEventListener("blur", () => {
    const template = getSelectedPlayerBreakdownTemplate();
    if (!template) {
      return;
    }

    const rawText = String(editorDom.playerStatLabelsJson.value || "").trim();
    if (!rawText) {
      delete template.statLabels;
      markDirtyAndRender();
      return;
    }

    try {
      const parsed = JSON.parse(rawText);
      if (!isPlainObject(parsed)) {
        throw new Error("statLabels must be a JSON object.");
      }
      template.statLabels = parsed;
      markDirtyAndRender();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Invalid statLabels JSON.", true);
    }
  });
}

function bindElementHandlers() {
  const mutateElement = (mutator) => {
    const element = getSelectedElement();
    if (!element) {
      return;
    }
    mutator(element);
    markDirtyAndRender();
  };

  editorDom.addElementBtn.addEventListener("click", () => {
    const template = getSelectedTemplate();
    if (!template) {
      window.alert("Select a template first.");
      return;
    }

    const kind = editorDom.newElementKind.value || "text";
    template.elements.push(defaultElement(kind));
    editorState.selectedElementIndex = template.elements.length - 1;
    markDirtyAndRender();
  });

  editorDom.duplicateElementBtn?.addEventListener("click", () => {
    const template = getSelectedTemplate();
    if (!template) {
      return;
    }

    const index = editorState.selectedElementIndex;
    if (index < 0 || index >= template.elements.length) {
      return;
    }

    const duplicate = deepClone(template.elements[index]);
    template.elements.splice(index + 1, 0, duplicate);
    editorState.selectedElementIndex = index + 1;
    markDirtyAndRender();
  });

  editorDom.removeElementBtn.addEventListener("click", () => {
    const template = getSelectedTemplate();
    if (!template) {
      return;
    }

    const index = editorState.selectedElementIndex;
    if (index < 0 || index >= template.elements.length) {
      return;
    }

    template.elements.splice(index, 1);
    if (template.elements.length === 0) {
      editorState.selectedElementIndex = -1;
    } else if (index >= template.elements.length) {
      editorState.selectedElementIndex = template.elements.length - 1;
    }

    markDirtyAndRender();
  });

  editorDom.moveElementUpBtn.addEventListener("click", () => {
    const template = getSelectedTemplate();
    if (!template) {
      return;
    }

    const index = editorState.selectedElementIndex;
    if (index <= 0 || index >= template.elements.length) {
      return;
    }

    const previous = template.elements[index - 1];
    template.elements[index - 1] = template.elements[index];
    template.elements[index] = previous;
    editorState.selectedElementIndex = index - 1;
    markDirtyAndRender();
  });

  editorDom.moveElementDownBtn.addEventListener("click", () => {
    const template = getSelectedTemplate();
    if (!template) {
      return;
    }

    const index = editorState.selectedElementIndex;
    if (index < 0 || index >= template.elements.length - 1) {
      return;
    }

    const next = template.elements[index + 1];
    template.elements[index + 1] = template.elements[index];
    template.elements[index] = next;
    editorState.selectedElementIndex = index + 1;
    markDirtyAndRender();
  });

  editorDom.elementKind.addEventListener("change", () => {
    mutateElement((element) => {
      element.kind = editorDom.elementKind.value;
    });
  });

  const textInputs = [
    [editorDom.elementClassName, "className"],
    [editorDom.elementX, "x"],
    [editorDom.elementY, "y"],
    [editorDom.elementW, "w"],
    [editorDom.elementH, "h"],
    [editorDom.elementRight, "right"],
    [editorDom.elementBottom, "bottom"],
  ];

  textInputs.forEach(([inputNode, fieldName]) => {
    inputNode.addEventListener("input", () => {
      mutateElement((element) => {
        setMaybeStringField(element, fieldName, inputNode.value);
      });
    });
  });

  editorDom.elementEnterEffect.addEventListener("change", () => {
    mutateElement((element) => {
      if (!editorDom.elementEnterEffect.value) {
        delete element.enter;
        return;
      }
      element.enter = element.enter || {};
      element.enter.effect = editorDom.elementEnterEffect.value;
    });
  });

  editorDom.elementEnterDuration.addEventListener("input", () => {
    mutateElement((element) => {
      if (!editorDom.elementEnterDuration.value.trim()) {
        if (element.enter) {
          delete element.enter.durationMs;
        }
        return;
      }
      element.enter = element.enter || {};
      element.enter.durationMs = Math.max(120, Number(editorDom.elementEnterDuration.value));
    });
  });

  editorDom.elementEnterDelay.addEventListener("input", () => {
    mutateElement((element) => {
      if (!editorDom.elementEnterDelay.value.trim()) {
        if (element.enter) {
          delete element.enter.delayMs;
        }
        return;
      }
      element.enter = element.enter || {};
      element.enter.delayMs = Math.max(0, Number(editorDom.elementEnterDelay.value));
    });
  });

  editorDom.elementExitEffect.addEventListener("change", () => {
    mutateElement((element) => {
      if (!editorDom.elementExitEffect.value) {
        delete element.exit;
        return;
      }
      element.exit = element.exit || {};
      element.exit.effect = editorDom.elementExitEffect.value;
    });
  });

  editorDom.elementExitDuration.addEventListener("input", () => {
    mutateElement((element) => {
      if (!editorDom.elementExitDuration.value.trim()) {
        if (element.exit) {
          delete element.exit.durationMs;
        }
        return;
      }
      element.exit = element.exit || {};
      element.exit.durationMs = Math.max(120, Number(editorDom.elementExitDuration.value));
    });
  });

  editorDom.elementExitDelay.addEventListener("input", () => {
    mutateElement((element) => {
      if (!editorDom.elementExitDelay.value.trim()) {
        if (element.exit) {
          delete element.exit.delayMs;
        }
        return;
      }
      element.exit = element.exit || {};
      element.exit.delayMs = Math.max(0, Number(editorDom.elementExitDelay.value));
    });
  });

  editorDom.elementExitBeforeEnd.addEventListener("input", () => {
    mutateElement((element) => {
      if (!editorDom.elementExitBeforeEnd.value.trim()) {
        delete element.exitBeforeSlideEndMs;
        delete element.exitLeadMs;
        return;
      }

      const numeric = Number(editorDom.elementExitBeforeEnd.value);
      if (!Number.isFinite(numeric)) {
        return;
      }

      element.exitBeforeSlideEndMs = Math.max(0, numeric);
      delete element.exitLeadMs;
    });
  });

  editorDom.textTag.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "tag", editorDom.textTag.value));
  });

  editorDom.textValue.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "text", editorDom.textValue.value));
  });

  editorDom.textPath.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "textPath", editorDom.textPath.value));
  });

  editorDom.textFontSize.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "textFontSize", editorDom.textFontSize.value));
  });

  editorDom.textColor.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "textColor", editorDom.textColor.value));
  });

  editorDom.textFontWeight.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "textFontWeight", editorDom.textFontWeight.value));
  });

  editorDom.imageSrc.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "src", editorDom.imageSrc.value));
  });

  editorDom.imageSrcPath.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "srcPath", editorDom.imageSrcPath.value));
  });

  editorDom.imageAlt.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "alt", editorDom.imageAlt.value));
  });

  editorDom.listItemsPath.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemsPath", editorDom.listItemsPath.value));
  });

  editorDom.listTitleTemplate.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "titleTemplate", editorDom.listTitleTemplate.value));
  });

  editorDom.listTitleFontSize.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "titleFontSize", editorDom.listTitleFontSize.value));
  });

  editorDom.listTitleColor.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "titleColor", editorDom.listTitleColor.value));
  });

  editorDom.listContainerPanel.addEventListener("change", () => {
    mutateElement((element) => {
      if (editorDom.listContainerPanel.checked) {
        element.containerPanel = true;
      } else {
        delete element.containerPanel;
      }
    });
  });

  editorDom.listColumns.addEventListener("input", () => {
    mutateElement((element) => setMaybeNumberField(element, "columns", editorDom.listColumns.value, 1));
  });

  editorDom.listGridGap.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "gridGap", editorDom.listGridGap.value));
  });

  editorDom.listGridAlignX.addEventListener("change", () => {
    mutateElement((element) => setMaybeStringField(element, "gridAlignX", editorDom.listGridAlignX.value));
  });

  editorDom.listGridAlignY.addEventListener("change", () => {
    mutateElement((element) => setMaybeStringField(element, "gridAlignY", editorDom.listGridAlignY.value));
  });

  editorDom.listItemsJson.addEventListener("blur", () => {
    const element = getSelectedElement();
    if (!element) {
      return;
    }

    try {
      const parsed = parseListItemsJson(editorDom.listItemsJson.value);
      if (parsed.length) {
        element.items = parsed;
      } else {
        delete element.items;
      }
      markDirtyAndRender();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Invalid list items JSON.", true);
    }
  });

  editorDom.listItemsAddRowBtn.addEventListener("click", () => {
    const element = getSelectedElement();
    const kind = String(element?.kind || "");
    if (!element || (kind !== "list" && kind !== "grid")) {
      return;
    }

    try {
      const rows = getEditableListItems(element);
      const rowNumber = rows.length + 1;
      rows.push({
        title: `Row ${rowNumber}`,
        subtitleTemplate: "",
      });

      element.items = rows;
      setInputValue(editorDom.listItemsJson, JSON.stringify(rows, null, 2));
      markDirtyAndRender();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Invalid list items JSON.", true);
    }
  });

  editorDom.listItemsRemoveRowBtn.addEventListener("click", () => {
    const element = getSelectedElement();
    const kind = String(element?.kind || "");
    if (!element || (kind !== "list" && kind !== "grid")) {
      return;
    }

    try {
      const rows = getEditableListItems(element);
      if (!rows.length) {
        setStatus("No inline list rows to remove.");
        return;
      }

      rows.pop();
      if (rows.length) {
        element.items = rows;
      } else {
        delete element.items;
      }

      setInputValue(editorDom.listItemsJson, rows.length ? JSON.stringify(rows, null, 2) : "");
      markDirtyAndRender();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Invalid list items JSON.", true);
    }
  });

  editorDom.listMaxItems.addEventListener("input", () => {
    mutateElement((element) => setMaybeNumberField(element, "maxItems", editorDom.listMaxItems.value, 1));
  });

  editorDom.listItemImagePath.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemImagePath", editorDom.listItemImagePath.value));
  });

  editorDom.listItemImageAltTemplate.addEventListener("input", () => {
    mutateElement((element) =>
      setMaybeStringField(element, "itemImageAltTemplate", editorDom.listItemImageAltTemplate.value)
    );
  });

  editorDom.listItemImageWidth.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemImageWidth", editorDom.listItemImageWidth.value));
  });

  editorDom.listItemImageHeight.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemImageHeight", editorDom.listItemImageHeight.value));
  });

  editorDom.listItemTitleTemplate.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemTitleTemplate", editorDom.listItemTitleTemplate.value));
  });

  editorDom.listItemSubtitleTemplate.addEventListener("input", () => {
    mutateElement((element) =>
      setMaybeStringField(element, "itemSubtitleTemplate", editorDom.listItemSubtitleTemplate.value)
    );
  });

  editorDom.listItemTitleFontSize.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemTitleFontSize", editorDom.listItemTitleFontSize.value));
  });

  editorDom.listItemTitleColor.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "itemTitleColor", editorDom.listItemTitleColor.value));
  });

  editorDom.listItemTitleAlign.addEventListener("change", () => {
    mutateElement((element) => setMaybeStringField(element, "itemTitleAlign", editorDom.listItemTitleAlign.value));
  });

  editorDom.listItemSubtitleFontSize.addEventListener("input", () => {
    mutateElement((element) =>
      setMaybeStringField(element, "itemSubtitleFontSize", editorDom.listItemSubtitleFontSize.value)
    );
  });

  editorDom.listItemSubtitleColor.addEventListener("input", () => {
    mutateElement((element) =>
      setMaybeStringField(element, "itemSubtitleColor", editorDom.listItemSubtitleColor.value)
    );
  });

  editorDom.listItemSubtitleAlign.addEventListener("change", () => {
    mutateElement((element) =>
      setMaybeStringField(element, "itemSubtitleAlign", editorDom.listItemSubtitleAlign.value)
    );
  });

  editorDom.listEmptyText.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "emptyText", editorDom.listEmptyText.value));
  });

  editorDom.listStaggerMs.addEventListener("input", () => {
    mutateElement((element) => {
      setMaybeNumberField(element, "staggerMs", editorDom.listStaggerMs.value, 0);
      if (isTruthyTemplateValue(element?.continuousReveal ?? element?.sequentialReveal ?? element?.revealSequential)) {
        setMaybeNumberField(element, "revealIntervalMs", editorDom.listStaggerMs.value, 0);
      }
    });
  });

  editorDom.barValue.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "value", editorDom.barValue.value));
  });

  editorDom.barValuePath.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "valuePath", editorDom.barValuePath.value));
  });

  editorDom.barMaxValue.addEventListener("input", () => {
    mutateElement((element) => setMaybeNumberField(element, "maxValue", editorDom.barMaxValue.value, 1));
  });

  editorDom.barLabelTemplate.addEventListener("input", () => {
    mutateElement((element) => setMaybeStringField(element, "labelTemplate", editorDom.barLabelTemplate.value));
  });

  editorDom.elementStyleJson.addEventListener("blur", () => {
    const element = getSelectedElement();
    if (!element) {
      return;
    }

    const rawText = editorDom.elementStyleJson.value.trim();
    if (!rawText) {
      delete element.style;
      markDirtyAndRender();
      return;
    }

    try {
      const parsed = JSON.parse(rawText);
      if (!isPlainObject(parsed)) {
        throw new Error("Style must be a JSON object.");
      }
      element.style = parsed;
      markDirtyAndRender();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Invalid style JSON.", true);
    }
  });
}

function bindCanvasHandlers() {
  if (!editorDom.canvasStage) {
    return;
  }

  editorDom.previewLargeMode?.addEventListener("change", () => {
    const isLarge = Boolean(editorDom.previewLargeMode.checked);
    applyPreviewLargeMode(isLarge, true);
    try {
      window.localStorage.setItem(PREVIEW_LARGE_MODE_STORAGE_KEY, isLarge ? "1" : "0");
    } catch {
      // Ignore storage failures (private mode / restricted storage)
    }
  });

  editorDom.canvasShowGrid?.addEventListener("change", () => {
    renderCanvas();
  });

  editorDom.canvasSnapToggle?.addEventListener("change", () => {
    renderCanvas();
  });

  editorDom.canvasSnapStep?.addEventListener("change", () => {
    renderCanvas();
  });

  window.addEventListener("pointermove", handleCanvasPointerMove);
  window.addEventListener("pointerup", handleCanvasPointerUp);
  window.addEventListener("pointercancel", handleCanvasPointerUp);

  window.addEventListener("resize", () => {
    renderCanvas();
    renderRuntimePreview(false);
  });
}

function bindRuntimeHandlers() {
  editorState.keySource = String(editorDom.keySourceSelect?.value || "payload");
  editorState.keyFilterText = String(editorDom.keySearchInput?.value || "");
  resetKeyTreeExpansion((KEY_FINDER_SOURCE_MAP[editorState.keySource] || KEY_FINDER_SOURCE_MAP.payload).rootPath);
  setRuntimeScrubUnavailable();

  editorDom.keySourceSelect?.addEventListener("change", () => {
    editorState.keySource = String(editorDom.keySourceSelect.value || "payload");
    resetKeyTreeExpansion((KEY_FINDER_SOURCE_MAP[editorState.keySource] || KEY_FINDER_SOURCE_MAP.payload).rootPath);
    renderKeyFinder();
  });

  editorDom.keySearchInput?.addEventListener("input", () => {
    editorState.keyFilterText = String(editorDom.keySearchInput.value || "");
    renderKeyFinder();
  });

  editorDom.runtimeScrubSlider?.addEventListener("input", () => {
    if (!editorState.runtimePreviewModel) {
      return;
    }
    const value = Number(editorDom.runtimeScrubSlider.value || 0);
    applyRuntimePreviewAtSeconds(value);
  });

  editorDom.refreshRuntimeDataBtn?.addEventListener("click", async () => {
    editorDom.runtimeSlideLabel.textContent = "Refreshing runtime data...";
    try {
      await refreshRuntimeData();
      renderRuntimePreview(false);
      renderKeyFinder();
      setStatus("Runtime data refreshed.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to refresh runtime data.";
      editorDom.runtimeSlideLabel.textContent = message;
      setStatus(message, true);
    }
  });

  editorDom.playRuntimePreviewBtn?.addEventListener("click", async () => {
    if (!editorState.previewState) {
      try {
        await refreshRuntimeData();
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unable to load runtime data for playback.";
        editorDom.runtimeSlideLabel.textContent = message;
        setStatus(message, true);
        return;
      }
    }

    await refreshSelectedTemplateRuntimeData();

    renderRuntimePreview(true);
  });
}

function bindPageActions() {
  editorDom.reloadBtn.addEventListener("click", async () => {
    try {
      await loadAllConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Reload failed.", true);
    }
  });

  editorDom.saveBtn.addEventListener("click", async () => {
    try {
      await saveAllConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save failed.", true);
    }
  });

  window.addEventListener("beforeunload", (event) => {
    if (!editorState.dirty) {
      return;
    }
    event.preventDefault();
    event.returnValue = "";
  });

  window.addEventListener("keydown", async (event) => {
    const isSaveShortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s";
    if (!isSaveShortcut) {
      return;
    }

    event.preventDefault();
    try {
      await saveAllConfigs();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save failed.", true);
    }
  });
}

async function initializeEditor() {
  initializePreviewLargeMode();
  initializeEffectSelects();
  bindGlobalHandlers();
  bindTemplateHandlers();
  bindElementHandlers();
  bindCanvasHandlers();
  bindRuntimeHandlers();
  bindPageActions();

  try {
    await loadAllConfigs();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Unable to load templates.", true);
    return;
  }

  try {
    await refreshRuntimeData();
    renderRuntimePreview(false);
    renderKeyFinder();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to load runtime data.";
    editorDom.runtimeSlideLabel.textContent = message;
    renderRuntimePreviewEmpty("Runtime data unavailable. Click Refresh Data to retry.");
  }
}

initializeEditor();
