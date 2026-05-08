// FILE: web/js/banana_triple_view_ui.js
(() => {
  "use strict";

  const EDITOR_ROUTE = "/hrio-design/editor";
  const AUTOMATION_SELECT_FOLDER_ROUTE = "/hrio-design/automation/select-folder";
  const AUTOMATION_PREVIEW_ROUTE = "/hrio-design/automation/preview";
  const AUTOMATION_HISTORY_ROUTE = "/hrio-design/automation/history";
  const AUTOMATION_HISTORY_CLEAR_ROUTE = "/hrio-design/automation/history-clear";
  const CONFIG_ROUTE = "/hrio-design/config";
  const OLD_EDITOR_ROUTES = [];
  const EDITOR_ROUTE_CANDIDATES = [EDITOR_ROUTE, ...OLD_EDITOR_ROUTES];

  const PANEL_ID = "hrio-design-image-launcher";
  const STYLE_ID = "hrio-design-image-style";
  const MODAL_ID = "hrio-design-automation-modal";
  const EDITOR_MODAL_ID = "hrio-design-editor-modal";
  const EXTENSION_NAME = "hrio.design.bridge.v8_1_0";

  const COMMAND_CHANNEL = "hrio_design_three_view_bridge";
  const DESIGNER_COMMAND_CHANNEL = "hrio_design_template_bridge";
  const COMMAND_STORAGE_KEY = "hrio_design_three_view_command";
  const DESIGNER_COMMAND_STORAGE_KEY = "hrio_design_template_command";
  const LIVE_CONFIG_KEY = "hrio_design_three_view_live_config";
  const DESIGNER_LIVE_CONFIG_KEY = "hrio_design_template_live_config";
  const AUTOMATION_STORAGE_KEY = "hrio_design_automation_payload_v810";
  const OLD_AUTOMATION_STORAGE_KEYS = [
    "banana_three_view_automation_payload",
    "banana_three_view_automation_payload_v710",
    "banana_three_view_automation_payload_v712",
    "banana_three_view_automation_payload_v713",
  ];
  const AUTOMATION_CLEAR_FLAG_KEY = "hrio_design_automation_clear_flag_v810";
  const FLOAT_POSITION_STORAGE_KEY = "hrio_design_float_position";

  const PANEL_NODE_KEY = "Hrio_Design_Template_Node";
  const PANEL_NODE_ALIAS_KEY = "Hrio_Design_Template_Node";
  const NORMAL_NODE_KEY = "Hrio_Design_Three_View_Node";
  const NORMAL_SINGLE_IMAGE_NODE_KEY = "Hrio_Design_Single_Image_Node";
  const NORMAL_SINGLE_IMAGE_CLASS = "HrioBananaNormalSingleImageNode";
  const NORMAL_SINGLE_VIDEO_NODE_KEY = "Hrio_Design_Single_Video_Node";
  const NORMAL_SINGLE_VIDEO_CLASS = "HrioBananaNormalVideoSingleOutputNode";
  const VIDEO_NODE_KEY = "Hrio_Design_Video_Node";
  const VIDEO_NODE_ALIAS_KEY = "Hrio_Design_Video_Node";

  const VIEW_SCOPE_MAP = {
    front: "仅重新生成正面",
    side: "仅重新生成侧面",
    back: "仅重新生成背面",
    variant_a: "仅重新生成正面",
    variant_b: "仅重新生成侧面",
    variant_c: "仅重新生成背面",
    all: "全部并发生成",
  };

  const LEGACY_IDS = [
    "banana-three-view-config-launcher",
    "banana-three-view-floating-modal",
    "ai-ecommerce-three-view-launcher",
    "ai-ecommerce-three-view-launcher-v510",
    "ai-ecommerce-three-view-launcher-v520",
    "ai-ecommerce-three-view-launcher-v530",
    "ai-ecommerce-simple-launcher-v540",
    "ai-ecommerce-one-click-launcher",
    "banana-prompt-template-launcher-v600",
    "banana-winter-rhyme-launcher",
    "banana-winter-rhyme-image-launcher",
  ];

  const LEGACY_STYLE_IDS = [
    "banana-three-view-config-launcher-style",
    "ai-ecommerce-three-view-launcher-style",
    "ai-ecommerce-three-view-style-v510",
    "ai-ecommerce-three-view-style-v520",
    "ai-ecommerce-three-view-style-v530",
    "ai-ecommerce-simple-launcher-style-v540",
    "ai-ecommerce-one-click-style",
    "banana-prompt-template-style-v600",
    "banana-winter-rhyme-style",
    "banana-winter-rhyme-image-style",
  ];

  const state = {
    lastCommandId: "",
    lastConfig: null,
    lastRuntime: null,
    queueTimer: null,
    pollTimer: null,
    beautifyTimer: null,
    automation: {
      inputRoots: [],
      outputRoot: "",
      groupConcurrency: 3,
      maxImagesPerGroup: 10,
      saveImages: true,
      saveVideo: false,
      previewGroups: [],
      lastPreview: null,
      historyItems: [],
      historyLoadedAt: 0,
      clearedAt: 0,
      clearGuardUntil: 0,
    },
    drag: {
      active: false,
      startX: 0,
      startY: 0,
      startLeft: 0,
      startTop: 0,
      moved: false,
    },
  };

  function isEditorPage() {
    const path = String(location.pathname || "");
    if (path.includes(EDITOR_ROUTE)) return true;
    return OLD_EDITOR_ROUTES.some((route) => path.includes(route));
  }

  function removeLegacy() {
    for (const id of LEGACY_IDS) {
      const el = document.getElementById(id);
      if (el && id !== PANEL_ID) el.remove();
    }

    for (const id of LEGACY_STYLE_IDS) {
      const el = document.getElementById(id);
      if (el && id !== STYLE_ID) el.remove();
    }
  }

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${PANEL_ID} {
        position: fixed;
        right: 20px;
        bottom: 20px;
        z-index: 999999;
        width: 318px;
        padding: 13px;
        border-radius: 26px;
        color: #24496f;
        background:
          radial-gradient(circle at 12% 5%, rgba(255,255,255,.98), rgba(255,255,255,.50) 34%, transparent 62%),
          radial-gradient(circle at 88% 16%, rgba(143,199,255,.34), transparent 42%),
          linear-gradient(135deg, rgba(239,248,255,.94), rgba(247,251,255,.88) 50%, rgba(255,247,251,.84));
        border: 1px solid rgba(255,255,255,.94);
        box-shadow:
          0 22px 66px rgba(42, 92, 145, .24),
          inset 0 1px 0 rgba(255,255,255,.92);
        backdrop-filter: blur(22px) saturate(148%);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
        overflow: hidden;
        user-select: none;
      }

      #${PANEL_ID}.dragging {
        opacity: .94;
        cursor: grabbing;
        transition: none !important;
      }

      #${PANEL_ID}::before {
        content: "";
        position: absolute;
        inset: -42px -34px auto auto;
        width: 132px;
        height: 132px;
        border-radius: 999px;
        background: radial-gradient(circle, rgba(143,199,255,.46), transparent 68%);
        pointer-events: none;
      }

      #${PANEL_ID}::after {
        content: "❄";
        position: absolute;
        right: 18px;
        top: 9px;
        font-size: 44px;
        line-height: 1;
        color: rgba(101,161,226,.20);
        pointer-events: none;
      }

      #${PANEL_ID} .wr-head {
        position: relative;
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
        cursor: grab;
      }

      #${PANEL_ID}.dragging .wr-head {
        cursor: grabbing;
      }

      #${PANEL_ID} .wr-logo {
        width: 44px;
        height: 44px;
        border-radius: 17px;
        display: grid;
        place-items: center;
        color: #fff;
        background: linear-gradient(135deg, #7fbfff, #a8d7ff 52%, #d9ecff);
        box-shadow: 0 12px 30px rgba(83, 150, 222, .30);
        font-size: 20px;
        font-weight: 950;
        flex: 0 0 auto;
      }

      #${PANEL_ID} .wr-title {
        min-width: 0;
        flex: 1;
      }

      #${PANEL_ID} .wr-title strong {
        display: block;
        font-size: 14px;
        color: #24496f;
        letter-spacing: .01em;
      }

      #${PANEL_ID} .wr-title span {
        display: block;
        margin-top: 2px;
        font-size: 11px;
        color: rgba(36,73,111,.68);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      #${PANEL_ID} .wr-state {
        position: relative;
        display: flex;
        align-items: center;
        gap: 8px;
        min-height: 34px;
        padding: 8px 10px;
        border-radius: 16px;
        background: rgba(255,255,255,.64);
        border: 1px solid rgba(113,159,210,.17);
        color: #426b95;
        font-size: 12px;
        font-weight: 850;
        box-shadow: inset 0 1px 0 rgba(255,255,255,.76);
        margin-bottom: 10px;
      }

      #${PANEL_ID} .wr-dot {
        width: 9px;
        height: 9px;
        border-radius: 999px;
        background: #65b7ff;
        box-shadow: 0 0 0 5px rgba(101,183,255,.16);
        flex: 0 0 auto;
      }

      #${PANEL_ID}.ok .wr-dot {
        background: #18b789;
        box-shadow: 0 0 0 5px rgba(24,183,137,.14);
      }

      #${PANEL_ID}.syncing .wr-dot {
        background: #569fff;
        box-shadow: 0 0 0 5px rgba(86,159,255,.16);
      }

      #${PANEL_ID}.error .wr-dot {
        background: #ec5f75;
        box-shadow: 0 0 0 5px rgba(236,95,117,.16);
      }

      #${PANEL_ID} .wr-grid {
        position: relative;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
      }

      #${PANEL_ID} .wr-btn {
        height: 38px;
        border: 0;
        border-radius: 15px;
        padding: 0 11px;
        cursor: pointer;
        color: #fff;
        background: linear-gradient(135deg, #5b9fff, #92caff);
        box-shadow: 0 12px 24px rgba(74, 144, 226, .22);
        font-size: 12px;
        font-weight: 950;
        white-space: nowrap;
        transition: transform .14s ease, box-shadow .14s ease, filter .14s ease;
        user-select: none;
      }

      #${PANEL_ID} .wr-btn:hover {
        transform: translateY(-1px);
        filter: saturate(1.08);
        box-shadow: 0 15px 28px rgba(74, 144, 226, .28);
      }

      #${PANEL_ID} .wr-btn.secondary {
        color: #315d8f;
        background: rgba(255,255,255,.72);
        border: 1px solid rgba(113,159,210,.20);
        box-shadow: inset 0 1px 0 rgba(255,255,255,.74);
      }

      #${PANEL_ID} .wr-btn.full {
        grid-column: 1 / -1;
      }

      #${PANEL_ID} .wr-grid.compact {
        grid-template-columns: 1fr 1fr;
        gap: 8px;
      }

      #${PANEL_ID} .wr-grid.compact .wr-btn.full {
        grid-column: 1 / -1;
      }

      #${PANEL_ID} .wr-foot.compact {
        margin-top: 8px;
        padding-top: 8px;
        font-size: 10.5px;
        line-height: 1.42;
      }

      #${PANEL_ID} .wr-foot {
        position: relative;
        margin-top: 9px;
        padding: 8px 10px 0;
        border-top: 1px dashed rgba(113,159,210,.22);
        color: rgba(49,93,143,.64);
        font-size: 11px;
        line-height: 1.45;
      }

      #${EDITOR_MODAL_ID} {
        position: fixed;
        inset: 0;
        z-index: 1000001;
        display: none;
        place-items: center;
        background: rgba(10, 22, 36, .46);
        backdrop-filter: blur(8px);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      }

      #${EDITOR_MODAL_ID}.show {
        display: grid;
      }

      #${EDITOR_MODAL_ID} .editor-card {
        width: min(1180px, calc(100vw - 36px));
        height: min(820px, calc(100vh - 36px));
        border-radius: 24px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,.92);
        background: #f4f9ff;
        box-shadow: 0 28px 82px rgba(31,73,118,.34);
        display: grid;
        grid-template-rows: 48px 1fr;
      }

      #${EDITOR_MODAL_ID} .editor-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 0 12px 0 18px;
        color: #24496f;
        background: linear-gradient(135deg, rgba(239,248,255,.98), rgba(255,248,252,.96));
        border-bottom: 1px solid rgba(113,159,210,.18);
      }

      #${EDITOR_MODAL_ID} .editor-head strong {
        font-size: 14px;
        font-weight: 950;
      }

      #${EDITOR_MODAL_ID} .editor-head span {
        margin-left: 8px;
        font-size: 11px;
        color: rgba(49,93,143,.62);
      }

      #${EDITOR_MODAL_ID} .editor-actions {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      #${EDITOR_MODAL_ID} .editor-btn {
        height: 31px;
        border: 0;
        border-radius: 12px;
        padding: 0 12px;
        color: #315d8f;
        background: rgba(255,255,255,.74);
        border: 1px solid rgba(113,159,210,.20);
        cursor: pointer;
        font-size: 12px;
        font-weight: 850;
      }

      #${EDITOR_MODAL_ID} .editor-close {
        width: 32px;
        height: 32px;
        border-radius: 13px;
        border: 1px solid rgba(113,159,210,.20);
        background: rgba(255,255,255,.78);
        color: #315d8f;
        cursor: pointer;
        font-size: 18px;
        font-weight: 950;
      }

      #${EDITOR_MODAL_ID} iframe {
        width: 100%;
        height: 100%;
        border: 0;
        background: #f4f9ff;
      }

      #${MODAL_ID} {
        position: fixed;
        inset: 0;
        z-index: 1000000;
        display: none;
        place-items: center;
        background: rgba(12, 28, 44, .40);
        backdrop-filter: blur(8px);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      }

      #${MODAL_ID}.show {
        display: grid;
      }

      #${MODAL_ID} .auto-card {
        width: min(820px, calc(100vw - 36px));
        max-height: calc(100vh - 48px);
        overflow: auto;
        border-radius: 26px;
        border: 1px solid rgba(255,255,255,.94);
        background:
          radial-gradient(circle at 10% 0%, rgba(255,255,255,.98), rgba(255,255,255,.66) 36%, transparent 60%),
          linear-gradient(135deg, rgba(241,248,255,.96), rgba(248,252,255,.94) 52%, rgba(255,248,252,.92));
        box-shadow: 0 28px 82px rgba(31, 73, 118, .32);
        color: #24496f;
      }

      #${MODAL_ID} .auto-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        padding: 18px 20px;
        border-bottom: 1px solid rgba(113,159,210,.18);
      }

      #${MODAL_ID} .auto-head strong {
        display: block;
        font-size: 18px;
      }

      #${MODAL_ID} .auto-head span {
        display: block;
        margin-top: 4px;
        font-size: 12px;
        color: rgba(49,93,143,.68);
      }

      #${MODAL_ID} .auto-close {
        width: 34px;
        height: 34px;
        border-radius: 14px;
        border: 1px solid rgba(113,159,210,.20);
        background: rgba(255,255,255,.70);
        color: #315d8f;
        cursor: pointer;
        font-size: 18px;
        font-weight: 900;
      }

      #${MODAL_ID} .auto-body {
        padding: 18px 20px 20px;
        display: grid;
        gap: 14px;
      }

      #${MODAL_ID} .auto-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 14px;
      }

      #${MODAL_ID} .auto-box {
        border: 1px solid rgba(113,159,210,.18);
        border-radius: 20px;
        background: rgba(255,255,255,.62);
        padding: 14px;
      }

      #${MODAL_ID} .auto-box h3 {
        margin: 0 0 10px;
        font-size: 14px;
      }

      #${MODAL_ID} .auto-muted {
        font-size: 12px;
        color: rgba(49,93,143,.66);
        line-height: 1.6;
      }

      #${MODAL_ID} .auto-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
      }

      #${MODAL_ID} .auto-btn {
        height: 34px;
        border: 0;
        border-radius: 13px;
        padding: 0 12px;
        cursor: pointer;
        color: #fff;
        background: linear-gradient(135deg, #5b9fff, #92caff);
        box-shadow: 0 10px 20px rgba(74, 144, 226, .18);
        font-size: 12px;
        font-weight: 900;
      }

      #${MODAL_ID} .auto-btn.secondary {
        color: #315d8f;
        background: rgba(255,255,255,.74);
        border: 1px solid rgba(113,159,210,.20);
        box-shadow: none;
      }

      #${MODAL_ID} .auto-btn.danger {
        color: #9b1c1c;
        background: rgba(255,255,255,.78);
        border: 1px solid rgba(220, 80, 80, .28);
        box-shadow: none;
      }

      #${MODAL_ID} textarea,
      #${MODAL_ID} input {
        width: 100%;
        border: 1px solid rgba(113,159,210,.22);
        border-radius: 14px;
        background: rgba(255,255,255,.72);
        color: #24496f;
        outline: none;
        padding: 10px 12px;
        font-size: 12px;
        line-height: 1.5;
      }

      #${MODAL_ID} textarea {
        min-height: 132px;
        resize: vertical;
      }

      #${MODAL_ID} .auto-list {
        display: grid;
        gap: 6px;
        margin-top: 10px;
        max-height: 180px;
        overflow: auto;
      }

      #${MODAL_ID} .auto-item {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        padding: 8px 9px;
        border-radius: 12px;
        background: rgba(255,255,255,.70);
        border: 1px solid rgba(113,159,210,.14);
        font-size: 12px;
      }

      #${MODAL_ID} .auto-item code {
        color: #315d8f;
        font-weight: 900;
      }

      #${MODAL_ID} .auto-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
      }

      #${MODAL_ID} .auto-table th,
      #${MODAL_ID} .auto-table td {
        text-align: left;
        padding: 8px;
        border-bottom: 1px dashed rgba(113,159,210,.20);
        vertical-align: top;
      }

      #${MODAL_ID} .auto-table th {
        color: #315d8f;
        font-weight: 950;
      }

      #${MODAL_ID} .auto-bottom {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        border-top: 1px solid rgba(113,159,210,.18);
        padding-top: 14px;
        flex-wrap: wrap;
      }

      #${MODAL_ID} .auto-card,
      #${MODAL_ID} .auto-head,
      #${MODAL_ID} .auto-body,
      #${MODAL_ID} .auto-row,
      #${MODAL_ID} .auto-box,
      #${MODAL_ID} .auto-item,
      #${MODAL_ID} .auto-table,
      #${MODAL_ID} .auto-table th,
      #${MODAL_ID} .auto-table td {
        box-sizing: border-box;
        min-width: 0;
      }

      #${MODAL_ID} .auto-card {
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }

      #${MODAL_ID} .auto-body {
        overflow: auto;
      }

      #${MODAL_ID} .auto-row {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      }

      #${MODAL_ID} .auto-item {
        align-items: center;
      }

      #${MODAL_ID} .auto-path,
      #${MODAL_ID} .auto-ellipsis {
        display: block;
        min-width: 0;
        max-width: 100%;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }

      #${MODAL_ID} .auto-item-actions {
        flex: 0 0 auto;
        display: flex;
        gap: 8px;
        align-items: center;
      }

      #${MODAL_ID} .auto-table {
        table-layout: fixed;
      }

      #${MODAL_ID} .auto-table th:nth-child(1),
      #${MODAL_ID} .auto-table td:nth-child(1) { width: 86px; }
      #${MODAL_ID} .auto-table th:nth-child(4),
      #${MODAL_ID} .auto-table td:nth-child(4) { width: 90px; }

      #${MODAL_ID} .auto-cell-main {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        min-width: 0;
        max-width: 100%;
        overflow: hidden;
        word-break: break-all;
        line-height: 1.45;
      }

      #${MODAL_ID} .auto-preview-scroll {
        overflow: auto;
        margin-top: 10px;
        max-height: 280px;
        border-radius: 14px;
      }

      @media (max-width: 720px) {
        #${MODAL_ID} .auto-row {
          grid-template-columns: 1fr;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function saveFloatPosition(left, top) {
    try {
      localStorage.setItem(
        FLOAT_POSITION_STORAGE_KEY,
        JSON.stringify({
          left: Math.round(left),
          top: Math.round(top),
          saved_at: Date.now(),
        })
      );
    } catch {}
  }

  function readFloatPosition() {
    try {
      const raw = localStorage.getItem(FLOAT_POSITION_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (typeof parsed.left !== "number" || typeof parsed.top !== "number") return null;
      return parsed;
    } catch {
      return null;
    }
  }

  function applySavedFloatPosition(panel) {
    const pos = readFloatPosition();
    if (!pos) return;

    const rect = panel.getBoundingClientRect();
    const margin = 8;
    const left = clamp(pos.left, margin, window.innerWidth - rect.width - margin);
    const top = clamp(pos.top, margin, window.innerHeight - rect.height - margin);

    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.right = "auto";
    panel.style.bottom = "auto";
  }

  function makeLauncherDraggable(panel) {
    const handle = panel.querySelector(".wr-head");
    if (!handle) return;

    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;

      const target = event.target;
      if (target && target.closest && target.closest("button,input,textarea,select,a")) {
        return;
      }

      const rect = panel.getBoundingClientRect();

      state.drag.active = true;
      state.drag.moved = false;
      state.drag.startX = event.clientX;
      state.drag.startY = event.clientY;
      state.drag.startLeft = rect.left;
      state.drag.startTop = rect.top;

      panel.classList.add("dragging");
      panel.style.left = `${rect.left}px`;
      panel.style.top = `${rect.top}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";

      try {
        handle.setPointerCapture(event.pointerId);
      } catch {}

      event.preventDefault();
    });

    window.addEventListener("pointermove", (event) => {
      if (!state.drag.active) return;

      const rect = panel.getBoundingClientRect();
      const dx = event.clientX - state.drag.startX;
      const dy = event.clientY - state.drag.startY;

      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
        state.drag.moved = true;
      }

      const margin = 8;
      const nextLeft = clamp(
        state.drag.startLeft + dx,
        margin,
        window.innerWidth - rect.width - margin
      );
      const nextTop = clamp(
        state.drag.startTop + dy,
        margin,
        window.innerHeight - rect.height - margin
      );

      panel.style.left = `${nextLeft}px`;
      panel.style.top = `${nextTop}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";

      event.preventDefault();
    }, { passive: false });

    window.addEventListener("pointerup", () => {
      if (!state.drag.active) return;

      state.drag.active = false;
      panel.classList.remove("dragging");

      const rect = panel.getBoundingClientRect();
      saveFloatPosition(rect.left, rect.top);
    });

    window.addEventListener("resize", () => {
      const rect = panel.getBoundingClientRect();
      const margin = 8;

      const nextLeft = clamp(rect.left, margin, window.innerWidth - rect.width - margin);
      const nextTop = clamp(rect.top, margin, window.innerHeight - rect.height - margin);

      panel.style.left = `${nextLeft}px`;
      panel.style.top = `${nextTop}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";

      saveFloatPosition(nextLeft, nextTop);
    });
  }

  function createTemplateEditorModal() {
    injectStyle();

    let modal = document.getElementById(EDITOR_MODAL_ID);
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = EDITOR_MODAL_ID;
    modal.innerHTML =       '<div class="editor-card">' +
      '  <div class="editor-head">' +
      '    <div><strong>🎨 Hrio Design｜设计师模板面板</strong><span>嵌入当前 ComfyUI 页面；编辑内容会实时自动同步到节点。</span></div>' +
      '    <div class="editor-actions"><button class="editor-btn" data-editor-refresh type="button">刷新面板</button><button class="editor-close" data-editor-close type="button">×</button></div>' +
      '  </div>' +
      '  <iframe data-editor-frame title="Hrio Design模板面板"></iframe>' +
      '</div>';

    const close = () => modal.classList.remove("show");
    modal.querySelector("[data-editor-close]").onclick = close;
    modal.addEventListener("click", (event) => {
      if (event.target === modal) close();
    });
    modal.querySelector("[data-editor-refresh]").onclick = async () => {
      const frame = modal.querySelector("[data-editor-frame]");
      if (frame) frame.src = await resolveEditorUrl();
    };

    document.body.appendChild(modal);
    return modal;
  }

  async function resolveEditorUrl() {
    const errors = [];
    for (const route of EDITOR_ROUTE_CANDIDATES) {
      const url = new URL(route + "?embedded=1&t=" + Date.now(), window.location.origin).href;
      try {
        const res = await fetch(url, { method: "GET", cache: "no-store" });
        const contentType = String(res.headers.get("content-type") || "");
        if (res.ok && (contentType.includes("text/html") || contentType.includes("text/plain") || !contentType)) {
          return url;
        }
        errors.push(route + " -> HTTP " + res.status);
      } catch (error) {
        errors.push(route + " -> " + (error && error.message ? error.message : String(error)));
      }
    }
    console.warn("[Hrio Design] editor route detection failed, fallback to main route:", errors);
    return new URL(EDITOR_ROUTE + "?embedded=1&t=" + Date.now(), window.location.origin).href;
  }

  async function openTemplateEditor() {
    setLauncherState("正在打开Hrio Design模板面板...", "syncing");

    const modal = createTemplateEditorModal();
    const frame = modal.querySelector("[data-editor-frame]");

    modal.classList.add("show");

    if (frame) {
      try {
        frame.removeAttribute("srcdoc");
        frame.src = await resolveEditorUrl();
      } catch (error) {
        console.warn("[Hrio Design] open editor iframe failed:", error);
        frame.src = new URL(EDITOR_ROUTE + "?embedded=1&t=" + Date.now(), window.location.origin).href;
      }
    }

    setTimeout(() => {
      autoSyncConfigFromBackend("editor_open");
      setLauncherState("模板面板已在当前页面打开，节点自动同步已启用", "ok");
    }, 300);
  }

  function createLauncher() {
    if (isEditorPage()) return;

    removeLegacy();
    injectStyle();

    let panel = document.getElementById(PANEL_ID);
    if (panel) return;

    panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = "ok";
    panel.innerHTML = `
      <div class="wr-head" title="按住这里可以拖动浮窗">
        <div class="wr-logo">🎨</div>
        <div class="wr-title">
          <strong>Hrio Design｜设计师生成</strong>
          <span>平面设计 · 室内设计 · 模板同步</span>
        </div>
      </div>

      <div class="wr-state" title="节点同步状态">
        <span class="wr-dot"></span>
        <span data-state-text>自动同步已启用</span>
      </div>

      <div class="wr-grid compact">
        <button class="wr-btn full" data-open-editor type="button">打开Hrio Design模板面板</button>
        <button class="wr-btn secondary" data-automation type="button">自动化</button>
        <button class="wr-btn secondary" data-clear-automation type="button">清除自动化</button>
        <button class="wr-btn secondary" data-history type="button">历史记录</button>
      </div>

      <div class="wr-foot compact">
        节点自动同步已默认启用；会同步模板提示词到设计师模板、普通单图、普通三方案、生视频节点。
      </div>
    `;

    panel.querySelector("[data-open-editor]").onclick = () => {
      if (state.drag.moved) return;
      openTemplateEditor();
    };

    panel.querySelector("[data-automation]").onclick = () => {
      openAutomationModal();
    };

    panel.querySelector("[data-clear-automation]").onclick = () => {
      clearAutomationPayloadFromNodes(true);
    };

    panel.querySelector("[data-history]").onclick = () => {
      openAutomationModal();
      fetchAutomationHistory(true);
    };

    document.body.appendChild(panel);
    applySavedFloatPosition(panel);
    makeLauncherDraggable(panel);
  }

  function setLauncherState(text, kind = "ok") {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;

    panel.classList.toggle("ok", kind === "ok" || kind === "normal");
    panel.classList.toggle("syncing", kind === "syncing");
    panel.classList.toggle("error", kind === "error");

    const el = panel.querySelector("[data-state-text]");
    if (el) el.textContent = text;
  }

  function getGraph() {
    return (
      window.app?.graph ||
      window.comfyApp?.graph ||
      window.ComfyApp?.graph ||
      window.LiteGraph?.LGraphCanvas?.active_canvas?.graph ||
      window.graph ||
      null
    );
  }

  function getApp() {
    return window.app || window.comfyApp || window.ComfyApp || null;
  }

  function getCanvas() {
    return (
      window.app?.canvas ||
      window.comfyApp?.canvas ||
      window.ComfyApp?.canvas ||
      window.LiteGraph?.LGraphCanvas?.active_canvas ||
      null
    );
  }

  function allNodes() {
    const graph = getGraph();
    if (!graph) return [];
    if (Array.isArray(graph._nodes)) return graph._nodes;
    if (Array.isArray(graph.nodes)) return graph.nodes;
    return [];
  }

  function nodeText(node) {
    return [
      node?.type,
      node?.comfyClass,
      node?.constructor?.name,
      node?.title,
      node?.name,
      node?.properties?.NodeName,
      node?.properties?.cnr_id,
    ].filter(Boolean).join(" ");
  }

  function normalizeWidgetName(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[\s\-]+/g, "_");
  }

  function findWidget(node, names) {
    const widgets = node?.widgets || [];
    const targetNames = names.map(normalizeWidgetName);

    let found = widgets.find((widget) => {
      const name = normalizeWidgetName(widget?.name);
      return targetNames.includes(name);
    });

    if (found) return found;

    found = widgets.find((widget) => {
      const label = normalizeWidgetName(widget?.label || widget?.displayName || widget?.localized_name);
      return label && targetNames.includes(label);
    });

    return found || null;
  }

  function hasWidget(node, names) {
    return !!findWidget(node, names);
  }

  function bananaNodeKind(node) {
    if (!node) return "";

    const text = nodeText(node);
    const hasPrompt = hasWidget(node, ["prompt", "提示词"]);
    const hasVideoModel = hasWidget(node, ["video_model", "视频模型"]);
    const hasImageModel = hasWidget(node, ["model", "大模型"]);

    if (
      text.includes(NORMAL_SINGLE_VIDEO_NODE_KEY) ||
      text.includes(NORMAL_SINGLE_VIDEO_CLASS) ||
      text.includes("🎨 Hrio｜普通生视频") ||
      text.includes("普通生视频")
    ) {
      return "normal_video";
    }

    if (
      text.includes(VIDEO_NODE_KEY) ||
      text.includes(VIDEO_NODE_ALIAS_KEY) ||
      text.includes("🎨 Hrio｜生视频") ||
      text.includes("Hrio｜生视频") ||
      text.includes("🎨 Hrio Design｜视频生成") ||
      text.includes("Hrio Design｜视频生成") ||
      (hasVideoModel && hasWidget(node, ["automation_payload", "自动化映射"]))
    ) {
      return "video";
    }

    if (
      text.includes(NORMAL_SINGLE_IMAGE_NODE_KEY) ||
      text.includes(NORMAL_SINGLE_IMAGE_CLASS) ||
      text.includes("🎨 Hrio｜普通单图生成") ||
      text.includes("普通单图生成") ||
      (hasPrompt && hasImageModel && hasWidget(node, ["negative_prompt", "负面提示词"]) && !hasWidget(node, ["front_prompt", "方案A提示词"]))
    ) {
      return "normal_single";
    }

    if (
      text.includes(NORMAL_NODE_KEY) ||
      text.includes("🎨 Hrio｜普通三方案并发") ||
      text.includes("普通三方案") ||
      text.includes("🍌 普通三视图并发节点") ||
      text.includes("🎨 Hrio Design｜三方案并发") ||
      text.includes("普通三视图") ||
      text.includes("Normal_Banano") ||
      hasWidget(node, ["front_prompt", "正面图提示词", "方案A提示词"])
    ) {
      return "normal";
    }

    if (
      text.includes(PANEL_NODE_KEY) ||
      text.includes(PANEL_NODE_ALIAS_KEY) ||
      text.includes("BananaPanelThreeViewNode") ||
      text.includes("🎨 Hrio｜设计师模板生成") ||
      text.includes("Hrio｜设计师模板生成") ||
      text.includes("🎨 Hrio Design｜设计师模板面板") ||
      text.includes("Hrio Design｜设计师模板面板")
    ) {
      return "panel";
    }

    if (hasWidget(node, ["automation_payload", "自动化映射"])) {
      return "automation";
    }

    return "";
  }

  function isTemplateNode(node) {
    return !!bananaNodeKind(node);
  }

  function targetNodes() {
    return allNodes().filter(isTemplateNode);
  }

  function setWidgetValue(node, names, value) {
    if (!node || value === undefined || value === null) return false;

    const widget = findWidget(node, names);
    if (!widget) return false;

    try {
      if (widget.options && Array.isArray(widget.options.values)) {
        if (!widget.options.values.includes(value)) {
          widget.options.values.push(value);
        }
      }

      widget.value = value;

      // ComfyUI 某些版本在加入队列时读取 node.widgets_values，而不是实时读取 widget.value。
      // 这里同步写入 widgets_values，避免“跑本组”刚写入 run_sequences 后，实际队列仍使用旧的全量 payload。
      try {
        const widgets = Array.isArray(node.widgets) ? node.widgets : [];
        const index = widgets.indexOf(widget);
        if (index >= 0) {
          if (!Array.isArray(node.widgets_values)) node.widgets_values = [];
          node.widgets_values[index] = value;
        }
      } catch {}

      if (typeof widget.callback === "function") {
        widget.callback(value, null, node, null);
      }

      markCanvasDirty(node);
      return true;
    } catch (error) {
      console.warn("[Hrio Design] set widget failed:", error);
      return false;
    }
  }

  function markCanvasDirty(node) {
    try {
      if (node && typeof node.setDirtyCanvas === "function") {
        node.setDirtyCanvas(true, true);
      }

      const graph = getGraph();
      if (graph && typeof graph.setDirtyCanvas === "function") {
        graph.setDirtyCanvas(true, true);
      }

      const canvas = getCanvas();
      if (canvas && typeof canvas.setDirty === "function") {
        canvas.setDirty(true, true);
      }
    } catch {}
  }

  function hideWidgetOnNode(node, widget) {
    if (!node || !widget) return;

    try {
      widget.hidden = true;
      widget.disabled = true;
      widget.serialize = true;
      widget.label = "";
      widget.type = "hidden";
      widget.computeSize = () => [0, 0];
      widget.draw = () => {};

      const el = widget.inputEl || widget.element || widget.domElement || widget.textElement;
      if (el && el.style) {
        el.style.display = "none";
        el.style.visibility = "hidden";
        el.style.height = "0px";
        el.style.minHeight = "0px";
        el.style.maxHeight = "0px";
        el.style.opacity = "0";
        el.style.pointerEvents = "none";
      }
    } catch {}
  }
  function shouldHideWidgetForKind(kind, widgetName) {
    const n = normalizeWidgetName(widgetName);
    if (n === "automation_payload") return true;
    return false;
  }

  function updateModeWidgetOptions(node, modeOptions = {}) {
    const widget = findWidget(node, ["mode", "模式", "生成模式", "提示词模板"]);
    if (!widget) return;

    const values = Object.keys(modeOptions || {});
    if (!values.length) return;

    try {
      widget.options = widget.options || {};
      widget.options.values = values.slice();

      if (!values.includes(widget.value)) {
        widget.value = values[0];
      }

      if (typeof widget.callback === "function") {
        widget.callback(widget.value, null, node, null);
      }
    } catch (error) {
      console.warn("[Hrio Design] update mode options failed:", error);
    }
  }

  function firstTitleByKey(modeOptions, key) {
    const found = Object.entries(modeOptions || {}).find(([, value]) => value === key);
    return found ? found[0] : "";
  }

  function beautifyTargetNodes() {
    const nodes = targetNodes();

    nodes.forEach((node) => {
      try {
        if (!isTemplateNode(node)) return;

        const kind = bananaNodeKind(node);
        if (kind === "video") {
          node.title = "🎨 Hrio｜生视频";
        } else if (kind === "normal_video") {
          node.title = "🎨 Hrio｜普通生视频（单输出）";
        } else if (kind === "normal_single") {
          node.title = "🎨 Hrio｜普通单图生成";
        } else if (kind === "normal") {
          node.title = "🎨 Hrio｜普通三方案并发";
        } else if (kind === "panel") {
          node.title = "🎨 Hrio｜设计师模板生成";
        } else if (!node.title || String(node.title).includes("Hrio")) {
          node.title = node.title || "🎨 Hrio｜设计自动化节点";
        }

        node.color = kind === "video" ? "#a7d8ff" : "#8fc7ff";
        node.bgcolor = kind === "video" ? "#f1fbff" : "#f4f9ff";
        node.boxcolor = "#6baeea";
        node.title_color = "#315d8f";
        node.title_text_color = "#ffffff";

        node.properties = node.properties || {};
        node.properties["theme"] = "Hrio Design";
        node.properties["theme_en"] = "Winter Rhyme";
        node.properties["category"] = (kind === "video" || kind === "normal_video") ? "HRIO设计/视频生成" : ((kind === "normal" || kind === "normal_single") ? "HRIO设计/普通" : "HRIO设计/模板面板");
        node.properties["banana_node_kind"] = kind;
        node.properties["banana_beautified"] = true;

        if (Array.isArray(node.widgets)) {
          node.widgets.forEach((widget) => {
            if (!widget || !widget.name) return;

            const n = normalizeWidgetName(widget.name);

            if (n === "model") {
              widget.label = widget.label || "大模型 model";
            }

            if (n === "mode") {
              widget.label = widget.label || "提示词模板 mode";
            }

            if (n === "api_key") {
              widget.label = widget.label || "API Key";
            }

            if (n === "video_resolution") {
              widget.label = widget.label || "视频分辨率";
            }

            if (n === "aspect_ratio" && (kind === "video" || kind === "normal_video")) {
              widget.label = widget.label || "视频比例";
            }

            if (n === "image_size") {
              widget.label = widget.label || "图片分辨率";
            }

            if (n === "aspect_ratio" && kind !== "video" && kind !== "normal_video") {
              widget.label = widget.label || "图片比例";
            }

            if (n === "generate_scope") {
              widget.label = widget.label || "重跑范围";
            }

            if (n === "auto_retry_until_success") {
              widget.label = widget.label || "报错自动重抽";
            }

            if (n === "max_retry_per_view") {
              widget.label = widget.label || "单图最大重试";
            }

            if (n === "retry_interval_sec") {
              widget.label = widget.label || "重试间隔秒";
            }

            if (n === "automation_payload") {
              widget.label = widget.label || "自动化映射";
            }

            if (shouldHideWidgetForKind(kind, n)) {
              hideWidgetOnNode(node, widget);
            }
          });
          autoClearStaleAutomationPayloadOnNode(node);
        }

        const targetWidth = (kind === "video" || kind === "normal_video") ? 360 : (kind === "normal_single" ? 420 : 430);
        const targetHeight = (kind === "video" || kind === "normal_video") ? 620 : (kind === "normal_single" ? 520 : 540);
        if (typeof node.setSize === "function" && node.size) {
          const w = Math.max(Number(node.size[0] || 0), targetWidth);
          const h = (kind === "video" || kind === "normal_video") ? targetHeight : Math.max(Number(node.size[1] || 0), targetHeight);
          node.setSize([w, h]);
        } else if (Array.isArray(node.size)) {
          node.size[0] = Math.max(Number(node.size[0] || 0), targetWidth);
          node.size[1] = (kind === "video" || kind === "normal_video") ? targetHeight : Math.max(Number(node.size[1] || 0), targetHeight);
        }

        markCanvasDirty(node);
      } catch (error) {
        console.warn("[Hrio Design] beautify node failed:", error);
      }
    });
  }

  function cleanPromptPart(value) {
    return String(value || "").trim();
  }

  function joinPromptParts(parts) {
    return (parts || []).map(cleanPromptPart).filter(Boolean).join("\n\n");
  }

  function currentModeConfigFromCommand(command, config, modeKey) {
    if (command.current_mode_config && typeof command.current_mode_config === "object") return command.current_mode_config;
    const modes = config?.modes || command.prompts || {};
    if (modeKey && modes && modes[modeKey]) return modes[modeKey];
    return {};
  }

  function buildDesignerNodePrompts(command, config, modeKey, modeTitle) {
    const mode = currentModeConfigFromCommand(command, config, modeKey) || {};
    const globalPrompt = cleanPromptPart(mode.global_prompt || config.global_prompt || "");
    const imageRoles = cleanPromptPart(mode.image_roles || "");
    const consistencyPrompt = cleanPromptPart(mode.consistency_prompt || config.consistency_prompt || "");
    const negativePrompt = cleanPromptPart(mode.negative_prompt || config.global_negative_prompt || "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格标签，不要促销元素，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要错误透视，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。");
    const title = cleanPromptPart(modeTitle || command.current_mode_title || modeKey || "设计师模板");
    const designerDisplay = cleanPromptPart(command.designer_display || (mode.designer_type === "interior_design" ? "室内设计" : "平面设计"));

    const header = `当前设计方向：${designerDisplay}。当前模板：${title}。`;
    const outputRule = "输出要求：生成专业设计提案级画面，画面高级、干净、真实、可落地；不要生成真实文字、乱码、水印或二维码。";

    const variantA = cleanPromptPart(mode.variant_a_prompt || "方案 A：主方案。构图稳定、层级清晰、适合正式商业提案。");
    const variantB = cleanPromptPart(mode.variant_b_prompt || "方案 B：氛围强化方案。增强视觉吸引力、空间层次、材质和光影。");
    const variantC = cleanPromptPart(mode.variant_c_prompt || "方案 C：创意延展方案。更有设计张力，但仍保持高级可落地。");

    return {
      mode,
      negativePrompt,
      globalPrompt: joinPromptParts([header, imageRoles ? `参考图说明：${imageRoles}` : "", globalPrompt, consistencyPrompt, outputRule]),
      variantA: joinPromptParts([header, imageRoles ? `参考图说明：${imageRoles}` : "", globalPrompt, variantA, consistencyPrompt, outputRule]),
      variantB: joinPromptParts([header, imageRoles ? `参考图说明：${imageRoles}` : "", globalPrompt, variantB, consistencyPrompt, outputRule]),
      variantC: joinPromptParts([header, imageRoles ? `参考图说明：${imageRoles}` : "", globalPrompt, variantC, consistencyPrompt, outputRule]),
      single: joinPromptParts([header, imageRoles ? `参考图说明：${imageRoles}` : "", globalPrompt, variantA, consistencyPrompt, outputRule]),
      video: joinPromptParts([
        header,
        imageRoles ? `参考图说明：${imageRoles}` : "",
        globalPrompt,
        "视频任务：生成一段专业设计方案展示视频。镜头运动克制稳定，展示设计氛围、版式节奏、空间层次、材质细节、光影变化和整体高级感。不要生成文字、水印或二维码。",
        consistencyPrompt
      ]),
    };
  }

  function applyDesignerPromptsToNode(node, kind, promptPack) {
    if (!node || !promptPack) return;

    if (kind === "normal") {
      setWidgetValue(node, ["front_prompt", "正面图提示词", "方案A提示词", "方案 A"], promptPack.variantA);
      setWidgetValue(node, ["side_prompt", "侧面图提示词", "方案B提示词", "方案 B"], promptPack.variantB);
      setWidgetValue(node, ["back_prompt", "背面图提示词", "方案C提示词", "方案 C"], promptPack.variantC);
      setWidgetValue(node, ["global_prompt", "通用提示词", "全局提示词"], promptPack.globalPrompt);
      setWidgetValue(node, ["negative_prompt", "负面提示词"], promptPack.negativePrompt);
    } else if (kind === "normal_single") {
      setWidgetValue(node, ["prompt", "提示词"], promptPack.single);
      setWidgetValue(node, ["negative_prompt", "负面提示词"], promptPack.negativePrompt);
    } else if (kind === "normal_video" || kind === "video") {
      setWidgetValue(node, ["prompt", "提示词"], promptPack.video);
    }

    try {
      node.properties = node.properties || {};
      node.properties["hrio_design_prompt_synced"] = true;
      node.properties["hrio_design_prompt_synced_at"] = Date.now();
    } catch {}
  }

  function applyConfigToNodes(command) {
    const config = command.config || command.prompt_config || {};
    const modeOptions = command.mode_options || config.mode_options || {};
    const modeTitle = command.current_mode_title || firstTitleByKey(modeOptions, command.current_mode_key) || "";
    const modeKey = command.current_mode_key || modeOptions[modeTitle] || "";
    const nodes = targetNodes();
    const promptPack = buildDesignerNodePrompts(command, config, modeKey, modeTitle);

    if (!nodes.length) {
      setLauncherState("未找到 Hrio Design 相关节点，请先添加设计师模板 / 普通单图 / 普通三方案 / 生视频节点", "error");
      return;
    }

    nodes.forEach((node) => {
      if (!isTemplateNode(node)) return;

      const kind = bananaNodeKind(node);
      updateModeWidgetOptions(node, modeOptions);

      if (kind === "panel") {
        if (modeTitle) {
          setWidgetValue(node, ["mode", "模式", "生成模式", "提示词模板"], modeTitle);
        }

        if (modeKey) {
          setWidgetValue(node, ["mode_actual", "mode_key", "模式key"], modeKey);
        }

        setWidgetValue(node, ["labels_prefix", "label_prefix", "标题前缀"], modeTitle || modeKey);
      }

      applyDesignerPromptsToNode(node, kind, promptPack);
    });

    beautifyTargetNodes();

    state.lastConfig = config;
    setLauncherState(`已同步设计师提示词：${modeTitle || modeKey || "配置"}`, "syncing");
    setTimeout(() => setLauncherState("Hrio Design 节点已自动同步", "ok"), 900);
  }

  function applyRetryToNodes(command) {
    const modeTitle = command.mode_title || command.current_mode_title || "";
    const modeKey = command.mode_key || command.current_mode_key || "";
    const view = command.view || command.variant_key || "all";
    const scope = VIEW_SCOPE_MAP[view] || VIEW_SCOPE_MAP.all;
    const nodes = targetNodes();
    const config = command.config || command.prompt_config || state.lastConfig || {};
    const promptPack = buildDesignerNodePrompts(command, config, modeKey, modeTitle);

    if (!nodes.length) {
      setLauncherState("未找到 Hrio Design 相关节点", "error");
      return;
    }

    nodes.forEach((node) => {
      if (!isTemplateNode(node)) return;

      if (modeTitle) {
        setWidgetValue(node, ["mode", "模式", "生成模式", "提示词模板"], modeTitle);
      }

      if (modeKey) {
        setWidgetValue(node, ["mode_actual", "mode_key", "模式key"], modeKey);
      }

      setWidgetValue(node, ["generate_scope", "生成范围", "重跑范围"], scope);

      const automationPayload = parseAutomationPayloadFromNode(node);
      const automationEnabled = automationPayload && automationPayload.enabled !== false && Array.isArray(automationPayload.input_roots);
      if (automationEnabled) {
        const nextAutomationPayload = automationPayloadForRetry(automationPayload, command, view);
        setWidgetValue(node, ["automation_payload", "自动化映射"], JSON.stringify(nextAutomationPayload, null, 2));
      } else {
        const cacheKey = command.group?.cache_key || command.cache_key || "";
        if (cacheKey) {
          setWidgetValue(node, ["cache_key", "缓存key"], cacheKey);
        }
      }

      setWidgetValue(node, ["labels_prefix", "label_prefix", "标题前缀"], modeTitle || modeKey);
      applyDesignerPromptsToNode(node, bananaNodeKind(node), promptPack);
    });

    beautifyTargetNodes();
    setLauncherState(`重跑：${scope}`, "syncing");

    if (
      command.action === "retry_all" ||
      command.action === "retry_group" ||
      command.action === "retry_one" ||
      command.action === "retry_failed"
    ) {
      queueGraphDebounced();
    }
  }

  function queueGraphDebounced(delayMs = 420) {
    clearTimeout(state.queueTimer);
    state.queueTimer = setTimeout(queueGraph, Math.max(120, Number(delayMs) || 420));
  }

  function queueGraph() {
    const app = getApp();

    try {
      if (app && typeof app.queuePrompt === "function") {
        app.queuePrompt(0, 1);
        setLauncherState("已加入队列", "syncing");
        return true;
      }

      const queueButton =
        document.querySelector("#queue-button") ||
        document.querySelector("[title='Queue Prompt']") ||
        document.querySelector("button.comfy-queue-button");

      if (queueButton) {
        queueButton.click();
        setLauncherState("已点击 Queue", "syncing");
        return true;
      }
    } catch (error) {
      console.warn("[Hrio Design] queue failed:", error);
      setLauncherState("队列失败", "error");
    }

    return false;
  }

  function normalizeCommand(raw) {
    if (!raw) return null;

    if (typeof raw === "string") {
      try {
        return JSON.parse(raw);
      } catch {
        return null;
      }
    }

    if (typeof raw !== "object") return null;

    if (raw.data && typeof raw.data === "object") {
      return raw.data;
    }

    return raw;
  }

  function handleCommand(raw) {
    const command = normalizeCommand(raw);
    if (!command) return;

    const action = String(command.action || command.type || "");
    const clearFlag = getAutomationClearFlag();
    const commandTime = Number(command.created_at || command.createdAt || 0) || 0;

    // 清除自动化后，旧窗口/旧 localStorage/旧 BroadcastChannel 里残留的 automation_apply
    // 可能会异步把 JSON 写回来。这里统一拦截清除时间之前的自动化写回。
    if (action.includes("automation_apply") || (command.type === "automation" && command.payload)) {
      if (Date.now() < state.automation.clearGuardUntil) return;
      if (clearFlag && commandTime && commandTime <= clearFlag) return;
      if (clearFlag && !commandTime) return;
    }

    const commandId = String(command.created_at || "") + ":" + String(command.action || command.type || "");
    if (commandId && commandId === state.lastCommandId) return;
    state.lastCommandId = commandId;

    if (command.type === "config_sync" || command.action === "config_sync") {
      applyConfigToNodes(command);
      return;
    }

    if (command.type === "retry" || String(command.action || "").startsWith("retry")) {
      applyRetryToNodes(command);
      return;
    }

    if (command.type === "runtime_update" || command.action === "runtime_update") {
      state.lastRuntime = command.runtime || command.payload || command;
      setLauncherState("收到运行结果", "syncing");
      setTimeout(() => setLauncherState("模板节点已自动美化", "ok"), 800);
      return;
    }

    if (command.type === "automation_clear" || command.action === "automation_clear") {
      clearAutomationPayloadFromNodes(false, false);
      return;
    }

    if (command.action === "automation_apply" || (command.type === "automation" && command.payload)) {
      applyAutomationPayload(command.payload || command.automation || command, true, { fromBridge: true });
    }
  }

  function readLastStoredCommand() {
    try {
      const raw = localStorage.getItem(COMMAND_STORAGE_KEY) || localStorage.getItem(DESIGNER_COMMAND_STORAGE_KEY);
      if (raw) {
        const command = normalizeCommand(raw);
        const action = String(command?.action || command?.type || "");
        const clearFlag = getAutomationClearFlag();
        const commandTime = Number(command?.created_at || command?.createdAt || 0) || 0;

        // 不再从 localStorage 自动回写 automation_apply，避免刷新页面后旧自动化 JSON 又写回节点。
        if (action.includes("automation_clear")) {
          clearAutomationPayloadFromNodes(false, false);
        } else if (action.includes("automation_apply") || action.includes("automation")) {
          if (clearFlag && commandTime && commandTime <= clearFlag) return;
          if (clearFlag && !commandTime) return;
        } else if (action) {
          handleCommand(command);
        }
      }
    } catch {}

    try {
      const raw = localStorage.getItem(LIVE_CONFIG_KEY) || localStorage.getItem(DESIGNER_LIVE_CONFIG_KEY);
      if (raw) handleCommand(raw);
    } catch {}
  }

  function setupCommandBridge() {
    try {
      const bc = new BroadcastChannel(COMMAND_CHANNEL);
      bc.onmessage = (event) => handleCommand(event.data);
    } catch (error) {
      console.warn("[Hrio Design] BroadcastChannel unavailable:", error);
    }

    try {
      const designerBc = new BroadcastChannel(DESIGNER_COMMAND_CHANNEL);
      designerBc.onmessage = (event) => handleCommand(event.data);
    } catch (error) {
      console.warn("[Hrio Design] Designer BroadcastChannel unavailable:", error);
    }

    window.addEventListener("storage", (event) => {
      if (event.key === COMMAND_STORAGE_KEY || event.key === LIVE_CONFIG_KEY || event.key === DESIGNER_COMMAND_STORAGE_KEY || event.key === DESIGNER_LIVE_CONFIG_KEY) {
        handleCommand(event.newValue);
        return;
      }
      if (event.key === AUTOMATION_CLEAR_FLAG_KEY) {
        clearAutomationPayloadFromNodes(false, false);
      }
    });

    window.addEventListener("message", (event) => {
      handleCommand(event.data);
    });

    readLastStoredCommand();

    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(readLastStoredCommand, 1200);
  }

  function setupNodeBeautifyLoop() {
    clearInterval(state.beautifyTimer);

    const run = () => {
      try {
        beautifyTargetNodes();
        if (isAutomationHardClearMode()) {
          automationWidgetNodes().forEach((node) => {
            forceSetAutomationWidgetValue(node, "");
          });
          clearAutomationDomFallback();
        }
      } catch {}
    };

    setTimeout(run, 500);
    setTimeout(run, 1200);
    setTimeout(run, 2500);

    state.beautifyTimer = setInterval(run, 3000);
  }

  function currentTemplateModeFromNodes(modeOptions) {
    const nodes = targetNodes().filter((node) => bananaNodeKind(node) === "panel");
    for (const node of nodes) {
      const widget = findWidget(node, ["mode", "模式", "生成模式", "提示词模板"]);
      const value = String(widget?.value || "").trim();
      if (value) return value;
    }
    const titles = Object.keys(modeOptions || {});
    return titles[0] || "";
  }

  async function autoSyncConfigFromBackend(reason = "startup") {
    if (isEditorPage()) return false;

    try {
      const res = await fetch(CONFIG_ROUTE, { method: "GET", cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const config = await res.json();
      if (!config || typeof config !== "object") return false;

      const modeOptions = config.mode_options || {};
      const modeTitle = currentTemplateModeFromNodes(modeOptions);
      const modeKey = modeOptions[modeTitle] || config.default_mode || config.default_prompt_template || "";

      applyConfigToNodes({
        type: "config_sync",
        action: "config_sync",
        reason,
        created_at: Date.now(),
        current_mode_title: modeTitle,
        current_mode_key: modeKey,
        mode_options: modeOptions,
        mode_meta: config.mode_meta || {},
        preview_urls: config.preview_urls || {},
        config,
        prompts: config.modes || {},
        current_mode_config: modeKey && config.modes ? config.modes[modeKey] : null,
      });

      setLauncherState("自动同步已启用", "ok");
      return true;
    } catch (error) {
      console.warn("[Hrio Design] auto sync config failed:", error);
      beautifyTargetNodes();
      return false;
    }
  }

  function registerComfyExtension() {
    const app = getApp();

    if (!app || typeof app.registerExtension !== "function") {
      return false;
    }

    try {
      app.registerExtension({
        name: EXTENSION_NAME,

        async nodeCreated(node) {
          if (!isTemplateNode(node)) return;
          setTimeout(() => {
            beautifyTargetNodes();
            if (isAutomationHardClearMode()) forceSetAutomationWidgetValue(node, "");
          }, 60);
        },

        async setup() {
          setTimeout(() => autoSyncConfigFromBackend("extension_setup"), 300);
          setTimeout(() => beautifyTargetNodes(), 900);
        },
      });

      return true;
    } catch (error) {
      console.warn("[Hrio Design] registerExtension failed:", error);
      return false;
    }
  }

  function extractSequenceGreedy(name) {
    const text = String(name || "");
    const matches = text.match(/\d+/g);
    if (!matches || !matches.length) return "";
    return matches.join("");
  }

  function clampInt(value, fallback, min, max) {
    const n = Number.parseInt(value, 10);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, n));
  }

  async function postJson(url, payload = {}) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `请求失败：${res.status}`);
    }
    return data;
  }

  async function getJson(url) {
    const res = await fetch(url, { method: "GET" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `请求失败：${res.status}`);
    }
    return data;
  }

  function createAutomationModal() {
    if (document.getElementById(MODAL_ID)) return;

    const modal = document.createElement("div");
    modal.id = MODAL_ID;
    modal.innerHTML = `
      <div class="auto-card">
        <div class="auto-head">
          <div>
            <strong>自动化分组批处理</strong>
            <span>选择最多 10 个输入根目录和 1 个输出根目录；后端只扫描根目录下的直接图片文件，按图片文件名数字序号横向聚合并发执行。</span>
          </div>
          <button class="auto-close" data-auto-close type="button">×</button>
        </div>

        <div class="auto-body">
          <div class="auto-row">
            <div class="auto-box">
              <h3>输入根目录</h3>
              <div class="auto-muted">每个根目录下直接放图片，例如 001.png、002.png、003.png；不再使用 001_截图/ 子文件夹。序号规则：提取图片文件名中的所有数字并拼接。</div>
              <div class="auto-actions">
                <button class="auto-btn" data-auto-add-input-root type="button">添加输入根目录</button>
                <button class="auto-btn secondary" data-auto-clear-input-root type="button">清空输入</button>
              </div>
              <div class="auto-list" data-auto-input-root-list></div>
            </div>

            <div class="auto-box">
              <h3>输出根目录</h3>
              <div class="auto-muted">每个序号组会输出到 output_序号/run_01/，例如 output_001/run_01/front.png。</div>
              <div style="margin-top:10px;">
                <input data-auto-output-root placeholder="D:/输出/hrio_design_runs" />
              </div>
              <div class="auto-actions">
                <button class="auto-btn" data-auto-pick-output-root type="button">选择输出根目录</button>
              </div>
            </div>
          </div>

          <div class="auto-row">
            <div class="auto-box">
              <h3>执行参数</h3>
              <div style="display:grid; gap:10px;">
                <label class="auto-muted">组间并发数 1~10
                  <input data-auto-concurrency type="number" min="1" max="10" step="1" />
                </label>
                <label class="auto-muted">每组最多参考图 1~10
                  <input data-auto-max-images type="number" min="1" max="10" step="1" />
                </label>
                <label class="auto-muted" style="display:flex; align-items:center; gap:8px;">
                  <input data-auto-save-images type="checkbox" style="width:auto;" /> 保存 front.png / side.png / back.png
                </label>
                <label class="auto-muted" style="display:flex; align-items:center; gap:8px;">
                  <input data-auto-save-video type="checkbox" style="width:auto;" /> 保存 result.mp4（生视频节点使用；图像节点会忽略）
                </label>
              </div>
            </div>

            <div class="auto-box">
              <h3>操作</h3>
              <div class="auto-muted">先预览分组，确认序号聚合正确后，再应用到当前工作流里的 Hrio Design 图像节点与生视频节点。普通图像节点会保存图片，生视频节点会读取最多 10 张参考图并保存 result.mp4。</div>
              <div class="auto-actions">
                <button class="auto-btn" data-auto-preview type="button">预览分组</button>
                <button class="auto-btn secondary" data-auto-copy type="button">复制 JSON</button>
                <button class="auto-btn" data-auto-apply type="button">应用到节点</button>
                <button class="auto-btn" data-auto-run-all type="button">应用并运行全部</button>
                <button class="auto-btn danger" data-auto-clear-applied type="button">清除自动化</button>
              </div>
            </div>
          </div>

          <div class="auto-box">
            <h3>分组预览</h3>
            <div class="auto-muted" data-auto-preview-summary>尚未预览。</div>
            <div class="auto-preview-scroll">
              <table class="auto-table">
                <thead>
                  <tr>
                    <th>序号</th>
                    <th>输入图片</th>
                    <th>输出目录</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody data-auto-preview-list></tbody>
              </table>
            </div>
          </div>

          <div class="auto-box">
            <h3>输出历史缓存</h3>
            <div class="auto-muted">每个自动化序号组执行完成后，会写入插件目录下的 banana_automation_history.json；也会在对应 output_序号/run_01/ 里写 run_info.json / error.txt。</div>
            <div class="auto-actions">
              <button class="auto-btn secondary" data-auto-history-refresh type="button">刷新历史</button>
              <button class="auto-btn danger" data-auto-history-clear type="button">清理历史</button>
            </div>
            <div class="auto-muted" data-auto-history-summary>尚未读取历史。</div>
            <div class="auto-history-list" data-auto-history-list></div>
          </div>

          <div class="auto-bottom">
            <button class="auto-btn secondary" data-auto-close type="button">关闭</button>
            <button class="auto-btn danger" data-auto-clear-applied type="button">清除自动化</button>
            <button class="auto-btn" data-auto-apply type="button">应用到所有支持节点</button>
            <button class="auto-btn" data-auto-run-all type="button">应用并运行全部</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    modal.querySelectorAll("[data-auto-close]").forEach((btn) => {
      btn.onclick = () => closeAutomationModal();
    });

    modal.querySelector("[data-auto-add-input-root]").onclick = () => addAutomationInputRoot();
    modal.querySelector("[data-auto-clear-input-root]").onclick = () => {
      clearAutomationPayloadFromNodes(true);
      renderAutomationModal();
    };

    modal.querySelector("[data-auto-pick-output-root]").onclick = () => pickAutomationOutputRoot();
    modal.querySelector("[data-auto-output-root]").oninput = (event) => {
      state.automation.outputRoot = event.target.value;
      state.automation.previewGroups = [];
      state.automation.lastPreview = null;
    };
    modal.querySelector("[data-auto-concurrency]").oninput = (event) => {
      state.automation.groupConcurrency = clampInt(event.target.value, 3, 1, 10);
    };
    modal.querySelector("[data-auto-max-images]").oninput = (event) => {
      state.automation.maxImagesPerGroup = clampInt(event.target.value, 10, 1, 10);
    };
    modal.querySelector("[data-auto-save-images]").onchange = (event) => {
      state.automation.saveImages = !!event.target.checked;
    };
    modal.querySelector("[data-auto-save-video]").onchange = (event) => {
      state.automation.saveVideo = !!event.target.checked;
    };
    modal.querySelector("[data-auto-preview]").onclick = () => previewAutomationGroups();
    modal.querySelector("[data-auto-history-refresh]").onclick = () => fetchAutomationHistory(true);
    modal.querySelector("[data-auto-history-clear]").onclick = () => clearAutomationHistory();

    modal.querySelectorAll("[data-auto-copy]").forEach((btn) => {
      btn.onclick = () => {
        const payload = buildAutomationPayload();
        navigator.clipboard?.writeText(JSON.stringify(payload, null, 2)).catch(() => {});
        setLauncherState("自动化 JSON 已复制", "syncing");
        setTimeout(() => setLauncherState("模板节点已自动美化", "ok"), 900);
      };
    });

    modal.querySelectorAll("[data-auto-apply]").forEach((btn) => {
      btn.onclick = () => {
        const payload = buildAutomationPayload();
        applyAutomationPayload(payload, true, { force: true, fromUser: true });
        closeAutomationModal();
      };
    });

    modal.querySelectorAll("[data-auto-run-all]").forEach((btn) => {
      btn.onclick = () => runAutomationGroupsFromModal(null);
    });

    modal.querySelectorAll("[data-auto-clear-applied]").forEach((btn) => {
      btn.onclick = () => {
        clearAutomationPayloadFromNodes(true);
        renderAutomationModal();
      };
    });

    modal.addEventListener("click", (event) => {
      const runBtn = event.target.closest("[data-auto-run-group]");
      if (runBtn) {
        event.preventDefault();
        event.stopPropagation();
        const seq = String(runBtn.getAttribute("data-auto-run-group") || "").trim();
        runAutomationGroupsFromModal(seq || null);
        return;
      }

      const btn = event.target.closest("[data-auto-remove-root]");
      if (!btn) return;
      const idx = Number(btn.getAttribute("data-auto-remove-root"));
      if (Number.isInteger(idx)) {
        state.automation.inputRoots.splice(idx, 1);
        state.automation.previewGroups = [];
        state.automation.lastPreview = null;
        renderAutomationModal();
      }
    });
  }

  function openAutomationModal() {
    createAutomationModal();
    loadAutomationFromStorage();
    renderAutomationModal();
    document.getElementById(MODAL_ID).classList.add("show");
    fetchAutomationHistory(false);
  }

  function closeAutomationModal() {
    const modal = document.getElementById(MODAL_ID);
    if (modal) modal.classList.remove("show");
  }

  function loadAutomationFromStorage() {
    if (isAutomationHardClearMode()) {
      resetAutomationState();
      removeAutomationStorageKeys();
      return;
    }
    try {
      let raw = localStorage.getItem(AUTOMATION_STORAGE_KEY);
      if (!raw) {
        for (const key of OLD_AUTOMATION_STORAGE_KEYS) {
          raw = localStorage.getItem(key);
          if (raw) break;
        }
      }
      if (!raw) return;
      const payload = JSON.parse(raw);
      if (!payload || !Array.isArray(payload.input_roots)) return;
      state.automation.inputRoots = payload.input_roots.slice(0, 10);
      state.automation.outputRoot = payload.output_root || "";
      state.automation.groupConcurrency = clampInt(payload.group_concurrency, 3, 1, 10);
      state.automation.maxImagesPerGroup = clampInt(payload.max_images_per_group, 10, 1, 10);
      state.automation.saveImages = payload.save_images !== false;
      state.automation.saveVideo = !!payload.save_video;
      state.automation.previewGroups = Array.isArray(payload.preview_groups) ? payload.preview_groups : [];
    } catch {}
  }

  async function addAutomationInputRoot() {
    try {
      setLauncherState("正在选择输入根目录...", "syncing");
      const data = await postJson(AUTOMATION_SELECT_FOLDER_ROUTE, {});
      const path = String(data.path || "").trim();
      if (!path) return;
      if (!state.automation.inputRoots.includes(path) && state.automation.inputRoots.length < 10) {
        state.automation.inputRoots.push(path);
      }
      state.automation.previewGroups = [];
      state.automation.lastPreview = null;
      renderAutomationModal();
      setLauncherState("已添加输入根目录", "ok");
    } catch (error) {
      console.warn("[Hrio Design] select input root failed:", error);
      setLauncherState(`选择失败：${error.message || error}`, "warn");
    }
  }

  async function pickAutomationOutputRoot() {
    try {
      setLauncherState("正在选择输出根目录...", "syncing");
      const data = await postJson(AUTOMATION_SELECT_FOLDER_ROUTE, {});
      const path = String(data.path || "").trim();
      if (!path) return;
      state.automation.outputRoot = path;
      state.automation.previewGroups = [];
      state.automation.lastPreview = null;
      renderAutomationModal();
      setLauncherState("已选择输出根目录", "ok");
    } catch (error) {
      console.warn("[Hrio Design] select output root failed:", error);
      setLauncherState(`选择失败：${error.message || error}`, "warn");
    }
  }

  async function previewAutomationGroups() {
    try {
      const payload = buildAutomationPayload();
      if (!payload.input_roots.length) throw new Error("请先添加输入根目录");
      if (!payload.output_root) throw new Error("请先选择输出根目录");
      setLauncherState("正在预览自动化分组...", "syncing");
      const data = await postJson(AUTOMATION_PREVIEW_ROUTE, payload);
      state.automation.previewGroups = data.groups || [];
      state.automation.lastPreview = data;
      renderAutomationModal(false);
      setLauncherState(`已预览 ${state.automation.previewGroups.length} 个序号组`, "ok");
    } catch (error) {
      console.warn("[Hrio Design] preview automation failed:", error);
      setLauncherState(`预览失败：${error.message || error}`, "warn");
    }
  }

  function renderAutomationModal(updateFields = true) {
    const modal = document.getElementById(MODAL_ID);
    if (!modal) return;

    if (updateFields) {
      const outputRoot = modal.querySelector("[data-auto-output-root]");
      const concurrency = modal.querySelector("[data-auto-concurrency]");
      const maxImages = modal.querySelector("[data-auto-max-images]");
      const saveImages = modal.querySelector("[data-auto-save-images]");
      const saveVideo = modal.querySelector("[data-auto-save-video]");
      if (outputRoot) outputRoot.value = state.automation.outputRoot || "";
      if (concurrency) concurrency.value = state.automation.groupConcurrency || 3;
      if (maxImages) maxImages.value = state.automation.maxImagesPerGroup || 10;
      if (saveImages) saveImages.checked = state.automation.saveImages !== false;
      if (saveVideo) saveVideo.checked = !!state.automation.saveVideo;
    }

    const inputList = modal.querySelector("[data-auto-input-root-list]");
    if (inputList) {
      if (!state.automation.inputRoots.length) {
        inputList.innerHTML = `<div class="auto-muted">还没有选择输入根目录。</div>`;
      } else {
        inputList.innerHTML = state.automation.inputRoots.map((path, idx) => {
          const name = String(path || "").split(/[\\/]+/).filter(Boolean).pop() || path;
          return `
            <div class="auto-item" title="${escapeHtml(path)}">
              <span class="auto-path">${idx + 1}. ${escapeHtml(path)}</span>
              <span class="auto-item-actions"><code>${escapeHtml(extractSequenceGreedy(name) || "根目录")}</code><button class="auto-btn secondary" style="height:26px;padding:0 8px;" data-auto-remove-root="${idx}" type="button">删除</button></span>
            </div>
          `;
        }).join("");
      }
    }

    const summary = modal.querySelector("[data-auto-preview-summary]");
    const groups = state.automation.previewGroups || [];
    if (summary) {
      summary.textContent = groups.length
        ? `已预览 ${groups.length} 个序号组。执行时每个组只跑一次，最多 ${state.automation.groupConcurrency || 3} 组并发。`
        : "尚未预览。";
    }

    const list = modal.querySelector("[data-auto-preview-list]");
    if (list) {
      if (!groups.length) {
        list.innerHTML = `<tr><td colspan="4" class="auto-muted">点击“预览分组”后显示扫描结果。</td></tr>`;
      } else {
        list.innerHTML = groups.map((g) => {
          const rawItems = (g.items || []).map((it) => `${Number(it.root_index) + 1}. ${it.file_name || it.image_path || ""}`);
          const items = rawItems.map((x) => escapeHtml(x)).join("<br>");
          const seq = String(g.sequence || "");
          const outDir = String(g.output_dir || "");
          return `
            <tr>
              <td><code>${escapeHtml(seq)}</code></td>
              <td title="${escapeHtml(rawItems.join("\n"))}"><div class="auto-cell-main">${items || "-"}</div></td>
              <td title="${escapeHtml(outDir)}"><div class="auto-cell-main">${escapeHtml(outDir)}</div></td>
              <td><button class="auto-btn secondary" style="height:28px;padding:0 8px;" data-auto-run-group="${escapeHtml(seq)}" type="button">跑本组</button></td>
            </tr>
          `;
        }).join("");
      }
    }
  }

  function buildAutomationPayload() {
    return {
      enabled: true,
      type: "banana_sequence_group_automation",
      version: "7.10.0",
      created_at: Date.now(),
      input_roots: (state.automation.inputRoots || []).slice(0, 10),
      output_root: String(state.automation.outputRoot || "").trim(),
      group_concurrency: clampInt(state.automation.groupConcurrency, 3, 1, 10),
      max_input_roots: 10,
      max_images_per_group: clampInt(state.automation.maxImagesPerGroup, 10, 1, 10),
      extract_rule: "greedy_digits_join_all",
      collect_images_mode: "root_images_group_by_filename_sequence",
      collect_mode: "root_images_group_by_filename_sequence",
      save_images: state.automation.saveImages !== false,
      save_video: !!state.automation.saveVideo,
      video_filename: "result.mp4",
      image_filenames: {
        front: "front.png",
        side: "side.png",
        back: "back.png",
      },
      preview_groups: state.automation.previewGroups || [],
    };
  }

  function runAutomationGroupsFromModal(sequence = null) {
    try {
      const payload = buildAutomationPayload();
      if (!payload.input_roots.length) throw new Error("请先添加输入根目录");
      if (!payload.output_root) throw new Error("请先选择输出根目录");

      const groups = state.automation.previewGroups || [];
      if (!groups.length) throw new Error("请先点击预览分组，确认序号后再运行");

      if (sequence) {
        const seq = String(sequence);
        const found = groups.some((g) => String(g.sequence || "") === seq);
        if (!found) throw new Error(`预览列表里没有序号 ${seq}`);
        payload.run_sequences = [seq];
        payload.target_sequences = [seq];
        payload.sequences = [seq];
        payload.run_sequence = seq;
        payload.runSequence = seq;
        payload.selected_sequence = seq;
        payload.sequence = seq;
        payload.group_concurrency = 1;
        payload.run_mode = "single_group";
      } else {
        delete payload.run_sequences;
        delete payload.target_sequences;
        delete payload.sequences;
        delete payload.run_sequence;
        delete payload.runSequence;
        delete payload.selected_sequence;
        delete payload.sequence;
        payload.run_mode = "all_groups";
      }

      payload.run_view = "all";
      payload.created_at = Date.now();
      payload.force_apply_token = `${payload.run_mode}:${sequence || "all"}:${payload.created_at}`;
      applyAutomationPayload(payload, true, { force: true, fromModal: true });
      closeAutomationModal();
      setLauncherState(sequence ? `已应用并运行序号 ${sequence}` : "已应用并运行全部组", "syncing");
      queueGraphDebounced(700);
    } catch (error) {
      setLauncherState(`运行失败：${error.message || error}`, "error");
    }
  }

  function parseAutomationPayloadFromNode(node) {
    const widget = findWidget(node, ["automation_payload", "自动化映射"]);
    if (!widget) return null;
    try {
      const data = typeof widget.value === "string" ? JSON.parse(widget.value) : widget.value;
      if (data && typeof data === "object") return data;
    } catch {}
    return null;
  }

  function sequenceFromRuntimeGroup(group) {
    if (!group || typeof group !== "object") return "";
    const direct = String(group.sequence || group.seq || group.group_sequence || "").trim();
    if (direct) return direct;

    const values = [group.cache_key, group.labels_prefix, group.label, group.output_dir, group.run_id]
      .filter(Boolean)
      .map((x) => String(x));

    for (const value of values) {
      const autoMatch = value.match(/自动化\s*(\d+)/);
      if (autoMatch) return autoMatch[1];
      const outMatch = value.match(/output[_-](\d+)/i);
      if (outMatch) return outMatch[1];
      const colonParts = value.split(":").filter(Boolean);
      const last = colonParts[colonParts.length - 1] || "";
      if (/^\d+$/.test(last)) return last;
    }
    return "";
  }

  function automationPayloadForRetry(basePayload, command, view) {
    const payload = { ...(basePayload || {}) };
    payload.enabled = payload.enabled !== false;
    payload.run_view = view || "all";
    payload.run_mode = command.action || command.type || "retry";

    if (command.action === "retry_all" || command.scope === "all") {
      delete payload.run_sequences;
      delete payload.target_sequences;
      delete payload.sequences;
      delete payload.run_sequence;
      delete payload.runSequence;
      delete payload.selected_sequence;
      delete payload.sequence;
      return payload;
    }

    const seq = sequenceFromRuntimeGroup(command.group);
    if (seq) {
      payload.run_sequences = [String(seq)];
      payload.target_sequences = [String(seq)];
      payload.sequences = [String(seq)];
      payload.run_sequence = String(seq);
      payload.runSequence = String(seq);
      payload.selected_sequence = String(seq);
      payload.sequence = String(seq);
      payload.group_concurrency = 1;
    }
    payload.created_at = Date.now();
    payload.force_apply_token = `${payload.run_mode || "retry"}:${seq || "all"}:${payload.created_at}`;
    return payload;
  }

  function getAutomationClearFlag() {
    try {
      return Number(localStorage.getItem(AUTOMATION_CLEAR_FLAG_KEY) || 0) || 0;
    } catch {
      return 0;
    }
  }

  function setAutomationClearFlag(ts = Date.now()) {
    state.automation.clearedAt = ts;
    // 清除后保持更长保护窗口，避免 ComfyUI 右侧属性面板或旧 BroadcastChannel 异步把 JSON 写回来。
    state.automation.clearGuardUntil = ts + 120000;
    try {
      localStorage.setItem(AUTOMATION_CLEAR_FLAG_KEY, String(ts));
    } catch {}
    return ts;
  }

  function removeAutomationClearFlag() {
    state.automation.clearedAt = 0;
    state.automation.clearGuardUntil = 0;
    try { localStorage.removeItem(AUTOMATION_CLEAR_FLAG_KEY); } catch {}
    // 兼容旧版本留下的清除标记。
    try { localStorage.removeItem("banana_three_view_automation_clear_flag_v711"); } catch {}
    try { localStorage.removeItem("banana_three_view_automation_clear_flag_v710"); } catch {}
  }

  function hasActiveAutomationStorage() {
    try {
      if (localStorage.getItem(AUTOMATION_STORAGE_KEY)) return true;
      for (const key of OLD_AUTOMATION_STORAGE_KEYS) {
        if (localStorage.getItem(key)) return true;
      }
    } catch {}
    return false;
  }

  function isAutomationHardClearMode() {
    const clearFlag = getAutomationClearFlag();
    return !!clearFlag && !hasActiveAutomationStorage();
  }

  function automationPayloadCreatedAt(raw) {
    try {
      const data = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!data || typeof data !== "object") return 0;
      return Number(data.created_at || data.createdAt || data.force_apply_created_at || 0) || 0;
    } catch {
      return 0;
    }
  }

  function shouldClearAutomationValue(raw) {
    const text = typeof raw === "string" ? raw.trim() : "";
    if (!text) return false;
    if (!text.includes("input_roots") && !text.includes("automation") && !text.includes("enabled")) return false;

    // 用户点击“清除自动化”后，在没有新的主动应用动作前，任何旧 workflow 里残留的 payload 都应被压掉。
    if (isAutomationHardClearMode()) return true;

    const clearFlag = getAutomationClearFlag();
    if (!clearFlag) return false;
    const createdAt = automationPayloadCreatedAt(text);
    return !createdAt || createdAt <= clearFlag;
  }

  function clearWidgetDomValue(widget, value = "") {
    const candidates = [
      widget?.inputEl,
      widget?.element,
      widget?.domElement,
      widget?.textElement,
      widget?.textarea,
    ].filter(Boolean);

    for (const el of candidates) {
      try {
        if ("value" in el) el.value = value;
        if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
      } catch {}
    }
  }

  function forceSetAutomationWidgetValue(node, value = "") {
    if (!node || !Array.isArray(node.widgets)) return 0;
    let count = 0;
    node.widgets.forEach((widget, index) => {
      const name = normalizeWidgetName(widget?.name || widget?.label || widget?.displayName || widget?.localized_name);
      if (name !== "automation_payload") return;
      try {
        widget.value = value;
        widget.last_y = 0;
        clearWidgetDomValue(widget, value);
        if (!Array.isArray(node.widgets_values)) node.widgets_values = [];
        node.widgets_values[index] = value;
        count += 1;
      } catch {}
    });

    try {
      node.properties = node.properties || {};
      delete node.properties.automation_payload;
      delete node.properties["自动化映射"];
      node.properties.banana_automation_cleared_at = Date.now();
      node.properties.banana_automation_disabled = value ? false : true;
    } catch {}

    markCanvasDirty(node);
    return count;
  }

  function clearAutomationDomFallback() {
    // 右侧属性面板和新版 ComfyUI 的 DOM 控件有时会短暂保存旧值。
    // 只清明显包含自动化 payload 的文本框，避免误伤普通提示词。
    try {
      document.querySelectorAll("textarea, input").forEach((el) => {
        const value = String(el.value || "");
        if (shouldClearAutomationValue(value)) {
          el.value = "";
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    } catch {}
  }

  function autoClearStaleAutomationPayloadOnNode(node) {
    if (!node || !Array.isArray(node.widgets)) return false;
    let changed = false;
    node.widgets.forEach((widget, index) => {
      const name = normalizeWidgetName(widget?.name || widget?.label || widget?.displayName || widget?.localized_name);
      if (name !== "automation_payload") return;
      const value = widget?.value;
      if (shouldClearAutomationValue(value)) {
        widget.value = "";
        clearWidgetDomValue(widget, "");
        if (!Array.isArray(node.widgets_values)) node.widgets_values = [];
        node.widgets_values[index] = "";
        changed = true;
      }
    });
    if (changed) {
      try {
        node.properties = node.properties || {};
        node.properties.banana_automation_disabled = true;
        node.properties.banana_automation_cleared_at = getAutomationClearFlag() || Date.now();
      } catch {}
      markCanvasDirty(node);
    }
    return changed;
  }

  function resetAutomationState() {
    state.automation.inputRoots = [];
    state.automation.outputRoot = "";
    state.automation.groupConcurrency = 3;
    state.automation.maxImagesPerGroup = 10;
    state.automation.saveImages = true;
    state.automation.saveVideo = false;
    state.automation.previewGroups = [];
    state.automation.lastPreview = null;
  }

  function automationWidgetNodes() {
    return allNodes().filter((node) => {
      if (isTemplateNode(node)) return true;
      return !!findWidget(node, ["automation_payload", "自动化映射"]);
    });
  }

  function removeAutomationStorageKeys() {
    try { localStorage.removeItem(AUTOMATION_STORAGE_KEY); } catch {}
    try {
      for (const key of OLD_AUTOMATION_STORAGE_KEYS) {
        localStorage.removeItem(key);
      }
      // 兼容可能存在的开发中旧 key。
      localStorage.removeItem("banana_three_view_automation_payload_v709");
      localStorage.removeItem("banana_three_view_automation_payload_v708");
      localStorage.removeItem("banana_three_view_automation_payload_v707");
    } catch {}
  }

  function syncNodeWidgetValuesByName(node, normalizedName, value) {
    if (!node || !Array.isArray(node.widgets)) return 0;
    let count = 0;
    node.widgets.forEach((widget, index) => {
      const name = normalizeWidgetName(widget?.name || widget?.label || widget?.displayName || widget?.localized_name);
      if (name !== normalizedName) return;
      try {
        widget.value = value;
        if (widget.inputEl) widget.inputEl.value = value;
        if (widget.element && "value" in widget.element) widget.element.value = value;
        if (widget.domElement && "value" in widget.domElement) widget.domElement.value = value;
        if (!Array.isArray(node.widgets_values)) node.widgets_values = [];
        node.widgets_values[index] = value;
        count += 1;
      } catch {}
    });
    try {
      if (node.properties) {
        delete node.properties.automation_payload;
        delete node.properties["自动化映射"];
      }
    } catch {}
    markCanvasDirty(node);
    return count;
  }

  function clearAutomationPayloadFromNodes(announce = true, broadcast = true) {
    const clearedAt = setAutomationClearFlag(Date.now());
    resetAutomationState();
    removeAutomationStorageKeys();

    try { localStorage.removeItem(COMMAND_STORAGE_KEY); } catch {}

    const nodes = automationWidgetNodes();
    let clearedCount = 0;

    const clearOnce = () => {
      nodes.forEach((node) => {
        clearedCount += forceSetAutomationWidgetValue(node, "");
        setWidgetValue(node, ["generate_scope", "生成范围", "重跑范围"], "全部并发生成");
        autoClearStaleAutomationPayloadOnNode(node);
      });
      clearAutomationDomFallback();
      beautifyTargetNodes();
    };

    // 立即清一次，并在 ComfyUI 属性面板/节点异步回写后继续压掉旧值。
    // 某些版本会在选择节点/刷新右侧参数面板后把 workflow 里保存的 widget 值重新写回，
    // 因此这里拉长清理窗口，同时 setupNodeBeautifyLoop 也会持续检查。
    clearOnce();
    [80, 240, 600, 1200, 2500, 5000, 10000, 20000, 45000, 90000].forEach((ms) => setTimeout(clearOnce, ms));

    if (broadcast) {
      const command = {
        type: "automation_clear",
        action: "automation_clear",
        created_at: clearedAt,
      };

      try {
        localStorage.setItem(COMMAND_STORAGE_KEY, JSON.stringify(command));
      } catch {}

      try {
        const bc = new BroadcastChannel(COMMAND_CHANNEL);
        bc.postMessage(command);
        setTimeout(() => bc.close(), 300);
      } catch {}
    }

    if (announce) {
      setLauncherState(`已清除自动化：${nodes.length} 个节点`, "ok");
      setTimeout(() => setLauncherState("节点 automation_payload 已清空；旧工作流载入后也会自动压掉旧 JSON", "ok"), 1000);
    }
  }

  function applyAutomationPayload(payload, announce = true, options = {}) {
    if (!payload || !Array.isArray(payload.input_roots)) return;

    const now = Date.now();
    const createdAt = Number(payload.created_at || payload.createdAt || 0) || 0;
    const clearFlag = getAutomationClearFlag();
    if (!options.force && !options.fromUser && !options.fromModal) {
      if (now < state.automation.clearGuardUntil) return;
      if (clearFlag && createdAt && createdAt <= clearFlag) return;
      if (clearFlag && !createdAt) return;
    }

    // 只有主动应用/跑本组/跑全部时才退出“强清除模式”。
    removeAutomationClearFlag();

    payload = { ...payload, created_at: createdAt || now, enabled: payload.enabled !== false };
    try {
      localStorage.setItem(AUTOMATION_STORAGE_KEY, JSON.stringify(payload));
    } catch {}

    const nodes = automationWidgetNodes();
    let appliedCount = 0;
    const payloadText = JSON.stringify(payload, null, 2);
    nodes.forEach((node) => {
      try {
        node.properties = node.properties || {};
        node.properties.banana_automation_disabled = false;
        delete node.properties.banana_automation_cleared_at;
      } catch {}
      const count = forceSetAutomationWidgetValue(node, payloadText);
      if (count > 0) {
        appliedCount += 1;
      } else if (setWidgetValue(node, ["automation_payload", "自动化映射"], payloadText)) {
        appliedCount += 1;
      } else if (syncNodeWidgetValuesByName(node, "automation_payload", payloadText) > 0) {
        appliedCount += 1;
      }
    });

    const command = {
      type: "automation",
      action: "automation_apply",
      created_at: Date.now(),
      payload,
    };

    try {
      localStorage.setItem(COMMAND_STORAGE_KEY, JSON.stringify(command));
    } catch {}

    try {
      const bc = new BroadcastChannel(COMMAND_CHANNEL);
      bc.postMessage(command);
      setTimeout(() => bc.close(), 300);
    } catch {}

    beautifyTargetNodes();

    if (announce) {
      const groupCount = Array.isArray(payload.preview_groups) && payload.preview_groups.length ? payload.preview_groups.length : "未预览";
      setLauncherState(`自动化已应用：${groupCount} 组 / ${appliedCount} 个节点`, "syncing");
      setTimeout(() => setLauncherState("模板节点已自动美化", "ok"), 1200);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function fetchAutomationHistory(announce = false) {
    try {
      const data = await getJson(AUTOMATION_HISTORY_ROUTE);
      state.automation.historyItems = Array.isArray(data.items) ? data.items.slice().reverse() : [];
      state.automation.historyLoadedAt = Date.now();
      renderAutomationHistory();
      if (announce) setLauncherState(`已读取历史：${state.automation.historyItems.length} 条`, "ok");
    } catch (error) {
      console.warn("[Hrio Design] fetch history failed:", error);
      if (announce) setLauncherState(`历史读取失败：${error.message || error}`, "error");
    }
  }

  async function clearAutomationHistory() {
    try {
      await postJson(AUTOMATION_HISTORY_CLEAR_ROUTE, {});
      state.automation.historyItems = [];
      state.automation.historyLoadedAt = Date.now();
      renderAutomationHistory();
      setLauncherState("自动化历史已清理", "ok");
    } catch (error) {
      console.warn("[Hrio Design] clear history failed:", error);
      setLauncherState(`历史清理失败：${error.message || error}`, "error");
    }
  }

  function renderAutomationHistory() {
    const modal = document.getElementById(MODAL_ID);
    if (!modal) return;
    const list = modal.querySelector("[data-auto-history-list]");
    const summary = modal.querySelector("[data-auto-history-summary]");
    const items = state.automation.historyItems || [];
    if (summary) {
      summary.textContent = items.length ? `已缓存 ${items.length} 条历史，最新记录在最上方。` : "暂无历史缓存。";
    }
    if (!list) return;
    if (!items.length) {
      list.innerHTML = `<div class="auto-muted">暂无自动化输出历史。</div>`;
      return;
    }
    list.innerHTML = items.slice(0, 80).map((item) => {
      const ok = item.ok !== false;
      const seq = escapeHtml(item.sequence || "-");
      const type = escapeHtml(item.node_type || item.type || "image");
      const when = escapeHtml(item.created_at || "");
      const out = escapeHtml(item.output_dir || "");
      const msg = ok ? `${type} · ${out}` : `${type} · ${item.error || "失败"}`;
      return `
        <div class="auto-history-item" title="${out}">
          <div class="${ok ? "auto-history-ok" : "auto-history-bad"}">${ok ? "成功" : "失败"}</div>
          <div class="auto-history-main"><strong>序号 ${seq} · ${escapeHtml(msg)}</strong><span>${when}</span></div>
          <button class="auto-btn secondary" style="height:28px;padding:0 8px;" data-auto-run-group="${seq}" type="button">重跑</button>
        </div>
      `;
    }).join("");
  }

  function exposeDebugApi() {
    window.__BANANA_WINTER_RHYME_IMAGE_BRIDGE__ = {
      applyConfigToNodes,
      applyRetryToNodes,
      applyAutomationPayload,
      buildAutomationPayload,
      beautifyTargetNodes,
      targetNodes,
      queueGraph,
      readLastStoredCommand,
      clearAutomationPayloadFromNodes,
      getGraph,
      resetFloatPosition: () => {
        try {
          localStorage.removeItem(FLOAT_POSITION_STORAGE_KEY);
        } catch {}
        const panel = document.getElementById(PANEL_ID);
        if (panel) {
          panel.style.left = "auto";
          panel.style.top = "auto";
          panel.style.right = "20px";
          panel.style.bottom = "20px";
        }
      },
    };
  }

  function init() {
    if (window.__BANANA_WINTER_RHYME_IMAGE_BRIDGE_V713__) return;
    window.__BANANA_WINTER_RHYME_IMAGE_BRIDGE_V713__ = true;

    createLauncher();
    setupCommandBridge();
    registerComfyExtension();
    setupNodeBeautifyLoop();
    exposeDebugApi();

    setTimeout(() => autoSyncConfigFromBackend("startup_early"), 650);
    setTimeout(() => autoSyncConfigFromBackend("startup"), 1600);
    setTimeout(() => autoSyncConfigFromBackend("startup_late"), 3600);

    const hardClearIfNeeded = () => {
      if (!isAutomationHardClearMode()) return;
      automationWidgetNodes().forEach((node) => forceSetAutomationWidgetValue(node, ""));
      clearAutomationDomFallback();
      beautifyTargetNodes();
    };

    window.addEventListener("focus", () => setTimeout(hardClearIfNeeded, 80));
    window.addEventListener("click", () => setTimeout(hardClearIfNeeded, 80), true);

    setTimeout(readLastStoredCommand, 500);
    setTimeout(readLastStoredCommand, 1200);
    setTimeout(readLastStoredCommand, 2500);
    setTimeout(beautifyTargetNodes, 500);
    setTimeout(beautifyTargetNodes, 1200);
    setTimeout(beautifyTargetNodes, 2500);
    setTimeout(hardClearIfNeeded, 700);
    setTimeout(hardClearIfNeeded, 1800);
    setTimeout(hardClearIfNeeded, 3500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
