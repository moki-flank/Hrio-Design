// FILE: web/js/banana_triple_view_ui.js
(() => {
  "use strict";

  const EDITOR_ROUTE = "/hrio-design/editor";
  const AUTOMATION_SELECT_FOLDER_ROUTE = "/hrio-design/automation/select-folder";
  const AUTOMATION_PREVIEW_ROUTE = "/hrio-design/automation/preview";
  const AUTOMATION_HISTORY_ROUTE = "/hrio-design/runtime";
  const AUTOMATION_HISTORY_CLEAR_ROUTE = "/hrio-design/runtime/clear";
  const CONFIG_ROUTE = "/hrio-design/config";
  const RUNTIME_ROUTE = "/hrio-design/runtime";
  const OLD_EDITOR_ROUTES = [
    "/banana/designer-template-editor",
    "/banana/triple-view-editor",
    "/banana/prompt-editor",
    "/banana/ecommerce-editor",
    "/ai-ecommerce/editor",
  ];
  // 不使用 spread，避免部分 ComfyUI Desktop 前端/打包器把 ... 转写异常导致整个扩展脚本不执行。
  const EDITOR_ROUTE_CANDIDATES = [EDITOR_ROUTE].concat(OLD_EDITOR_ROUTES);

  const PANEL_ID = "hrio-design-image-launcher";
  const STYLE_ID = "hrio-design-image-style";
  const MODAL_ID = "hrio-design-automation-modal";
  const EDITOR_MODAL_ID = "hrio-design-editor-modal";
  const VIDEO_MODAL_ID = "hrio-design-video-modal";
  const HISTORY_MODAL_ID = "hrio-design-history-modal";
  const EXTENSION_NAME = "hrio.design.bridge.v8_2_2";

  const COMMAND_CHANNEL = "hrio_design_three_view_bridge";
  const DESIGNER_COMMAND_CHANNEL = "hrio_design_template_bridge";
  const COMMAND_STORAGE_KEY = "hrio_design_three_view_command";
  const DESIGNER_COMMAND_STORAGE_KEY = "hrio_design_template_command";
  const LIVE_CONFIG_KEY = "hrio_design_three_view_live_config";
  const DESIGNER_LIVE_CONFIG_KEY = "hrio_design_template_live_config";
  const AUTOMATION_STORAGE_KEY = "hrio_design_automation_payload_v821";
  const OLD_AUTOMATION_STORAGE_KEYS = [
    "hrio_design_automation_payload_v810",
    "hrio_design_automation_payload_v819",
    "hrio_design_automation_payload_v820",
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
  const AUTOMATION_TOGGLE_WIDGET_MARK = "__hrio_automation_toggle_widget__";

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
    launcher: {
      lastText: "就绪",
      lastKind: "ok",
      lastUpdatedAt: 0,
      lastActionKey: "init",
    },
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
    history: {
      items: [],
      loadedAt: 0,
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
  let automationPreviewTimer = null;

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

      #${PANEL_ID}.warn .wr-dot {
        background: #f59e0b;
        box-shadow: 0 0 0 5px rgba(245,158,11,.16);
      }

      /* HRIO_NO_STATUS_BAR: 彻底隐藏右下角浮窗状态栏，避免一闪一闪。 */
      #${PANEL_ID} .wr-state {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        opacity: 0 !important;
        pointer-events: none !important;
        overflow: hidden !important;
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

      #${VIDEO_MODAL_ID} {
        position: fixed;
        inset: 0;
        z-index: 1000002;
        display: none;
        place-items: center;
        background: rgba(10, 22, 36, .46);
        backdrop-filter: blur(8px);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      }

      #${VIDEO_MODAL_ID}.show {
        display: grid;
      }

      #${VIDEO_MODAL_ID} .video-card {
        width: min(980px, calc(100vw - 36px));
        max-height: calc(100vh - 42px);
        overflow: hidden;
        border-radius: 24px;
        border: 1px solid rgba(255,255,255,.92);
        background: linear-gradient(135deg, rgba(239,248,255,.98), rgba(255,248,252,.96));
        box-shadow: 0 28px 82px rgba(31,73,118,.34);
        color: #24496f;
        display: flex;
        flex-direction: column;
      }

      #${VIDEO_MODAL_ID} .video-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 15px 16px 12px 18px;
        border-bottom: 1px solid rgba(113,159,210,.18);
      }

      #${VIDEO_MODAL_ID} .video-head strong {
        display: block;
        font-size: 16px;
        font-weight: 950;
      }

      #${VIDEO_MODAL_ID} .video-head span {
        display: block;
        margin-top: 3px;
        font-size: 12px;
        color: rgba(49,93,143,.66);
      }

      #${VIDEO_MODAL_ID} .video-actions {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      #${VIDEO_MODAL_ID} .video-btn,
      #${VIDEO_MODAL_ID} .video-close {
        height: 32px;
        border-radius: 13px;
        border: 1px solid rgba(113,159,210,.20);
        background: rgba(255,255,255,.76);
        color: #315d8f;
        cursor: pointer;
        padding: 0 11px;
        font-size: 12px;
        font-weight: 900;
      }

      #${VIDEO_MODAL_ID} .video-close {
        width: 32px;
        padding: 0;
        font-size: 18px;
      }

      #${VIDEO_MODAL_ID} .video-body {
        padding: 16px;
        overflow: auto;
        display: grid;
        gap: 12px;
      }

      #${VIDEO_MODAL_ID} .video-empty {
        padding: 18px;
        border-radius: 18px;
        background: rgba(255,255,255,.68);
        border: 1px dashed rgba(113,159,210,.24);
        color: rgba(49,93,143,.72);
        font-size: 13px;
        line-height: 1.6;
      }

      #${VIDEO_MODAL_ID} .video-item {
        display: grid;
        gap: 8px;
        padding: 12px;
        border-radius: 18px;
        background: rgba(255,255,255,.70);
        border: 1px solid rgba(113,159,210,.18);
      }

      #${VIDEO_MODAL_ID} .video-item-head {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
        font-size: 12px;
        color: rgba(49,93,143,.72);
      }

      #${VIDEO_MODAL_ID} .video-item-head strong {
        color: #24496f;
        font-size: 13px;
      }

      #${VIDEO_MODAL_ID} video {
        width: 100%;
        max-height: min(62vh, 560px);
        border-radius: 14px;
        background: #0b1220;
      }

      #${HISTORY_MODAL_ID} {
        position: fixed;
        inset: 0;
        z-index: 1000003;
        display: none;
        place-items: center;
        background: rgba(10, 22, 36, .46);
        backdrop-filter: blur(8px);
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
      }

      #${HISTORY_MODAL_ID}.show {
        display: grid;
      }

      #${HISTORY_MODAL_ID} .history-card {
        width: min(1120px, calc(100vw - 36px));
        max-height: calc(100vh - 42px);
        overflow: hidden;
        border-radius: 24px;
        border: 1px solid rgba(255,255,255,.92);
        background: linear-gradient(135deg, rgba(239,248,255,.98), rgba(255,248,252,.96));
        box-shadow: 0 28px 82px rgba(31,73,118,.34);
        color: #24496f;
        display: flex;
        flex-direction: column;
      }

      #${HISTORY_MODAL_ID} .history-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 15px 16px 12px 18px;
        border-bottom: 1px solid rgba(113,159,210,.18);
      }

      #${HISTORY_MODAL_ID} .history-head strong { display: block; font-size: 16px; font-weight: 950; }
      #${HISTORY_MODAL_ID} .history-head span { display: block; margin-top: 3px; font-size: 12px; color: rgba(49,93,143,.66); }
      #${HISTORY_MODAL_ID} .history-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

      #${HISTORY_MODAL_ID} .history-btn,
      #${HISTORY_MODAL_ID} .history-close {
        height: 32px;
        border-radius: 13px;
        border: 1px solid rgba(113,159,210,.20);
        background: rgba(255,255,255,.76);
        color: #315d8f;
        cursor: pointer;
        padding: 0 11px;
        font-size: 12px;
        font-weight: 900;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }

      #${HISTORY_MODAL_ID} .history-close { width: 32px; padding: 0; font-size: 18px; }
      #${HISTORY_MODAL_ID} .history-body { padding: 16px; overflow: auto; display: grid; gap: 12px; }
      #${HISTORY_MODAL_ID} .history-empty { padding: 18px; border-radius: 18px; background: rgba(255,255,255,.68); border: 1px dashed rgba(113,159,210,.24); color: rgba(49,93,143,.72); font-size: 13px; line-height: 1.6; }
      #${HISTORY_MODAL_ID} .history-item { display: grid; grid-template-columns: 220px minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 12px; border-radius: 18px; background: rgba(255,255,255,.70); border: 1px solid rgba(113,159,210,.18); }
      #${HISTORY_MODAL_ID} .history-main { min-width: 0; display: grid; gap: 5px; }
      #${HISTORY_MODAL_ID} .history-title { font-size: 13px; font-weight: 950; color: #24496f; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
      #${HISTORY_MODAL_ID} .history-meta { font-size: 11px; color: rgba(49,93,143,.68); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
      #${HISTORY_MODAL_ID} .history-status-ok { color: #12805f; font-weight: 950; }
      #${HISTORY_MODAL_ID} .history-status-bad { color: #b42318; font-weight: 950; }
      #${HISTORY_MODAL_ID} .history-media { display: flex; flex-wrap: wrap; gap: 8px; min-width: 0; }
      #${HISTORY_MODAL_ID} .history-thumb { width: 64px; height: 64px; border-radius: 12px; object-fit: cover; border: 1px solid rgba(96,135,190,.18); background: #eef5ff; }
      #${HISTORY_MODAL_ID} video.history-thumb { object-fit: cover; background: #0b1220; }
      #${HISTORY_MODAL_ID} .history-path { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10.5px; color: rgba(49,93,143,.62); word-break: break-all; }
      @media (max-width: 860px) {
        #${HISTORY_MODAL_ID} .history-item { grid-template-columns: 1fr; }
        #${HISTORY_MODAL_ID} .history-actions { justify-content: flex-end; }
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
      #${MODAL_ID} .auto-table td:nth-child(1) { width: 72px; }
      #${MODAL_ID} .auto-table th:nth-child(3),
      #${MODAL_ID} .auto-table td:nth-child(3) { width: 240px; }
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
        max-height: 360px;
        border-radius: 14px;
      }

      #${MODAL_ID} .auto-thumb-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: flex-start;
        min-width: 0;
      }

      #${MODAL_ID} .auto-thumb-card {
        width: 74px;
        min-width: 74px;
        border: 1px solid rgba(96, 135, 190, 0.18);
        border-radius: 12px;
        padding: 5px;
        background: rgba(255, 255, 255, 0.72);
        box-shadow: 0 8px 20px rgba(30, 64, 110, 0.06);
      }

      #${MODAL_ID} .auto-thumb-card img,
      #${MODAL_ID} .auto-thumb-empty {
        width: 62px;
        height: 62px;
        border-radius: 10px;
        object-fit: cover;
        display: block;
        background: linear-gradient(135deg, #eef5ff, #f8fbff);
        border: 1px solid rgba(96, 135, 190, 0.18);
      }

      #${MODAL_ID} .auto-thumb-card img {
        cursor: zoom-in;
      }

      #${MODAL_ID} .auto-thumb-empty {
        display: flex;
        align-items: center;
        justify-content: center;
        color: #8ca1bd;
        font-size: 11px;
      }

      #${MODAL_ID} .auto-thumb-meta {
        margin-top: 4px;
        line-height: 1.25;
        font-size: 11px;
        color: #496583;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }

      #${MODAL_ID} .auto-thumb-sub {
        color: #8aa0ba;
        font-size: 10px;
      }

      #${MODAL_ID} .auto-scan-report {
        display: grid;
        gap: 6px;
        margin-top: 8px;
      }

      #${MODAL_ID} .auto-scan-report-row {
        display: grid;
        grid-template-columns: 46px minmax(0, 1fr) auto;
        gap: 8px;
        align-items: center;
        padding: 7px 8px;
        border-radius: 12px;
        background: rgba(246, 250, 255, .78);
        border: 1px solid rgba(113,159,210,.16);
      }

      #${MODAL_ID} .auto-scan-report-row code {
        color: #315d8f;
        font-weight: 900;
      }

      #${MODAL_ID} .auto-scan-report-path {
        min-width: 0;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
        color: #466381;
      }

      #${MODAL_ID} .auto-scan-report-stat {
        color: #7990ad;
        font-size: 11px;
        white-space: nowrap;
      }

      .hrio-auto-image-lightbox {
        position: fixed;
        inset: 0;
        z-index: 100000;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 28px;
        background: rgba(6, 15, 28, 0.72);
        backdrop-filter: blur(10px);
      }

      .hrio-auto-image-lightbox-inner {
        max-width: min(92vw, 1100px);
        max-height: 92vh;
        background: #fff;
        border-radius: 18px;
        box-shadow: 0 30px 90px rgba(0, 0, 0, 0.35);
        padding: 12px;
      }

      .hrio-auto-image-lightbox-inner img {
        max-width: calc(92vw - 24px);
        max-height: calc(88vh - 54px);
        display: block;
        border-radius: 12px;
      }

      .hrio-auto-image-lightbox-caption {
        margin-top: 8px;
        max-width: calc(92vw - 24px);
        color: #334b68;
        font-size: 12px;
        line-height: 1.45;
        word-break: break-all;
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
    // 直接打开主面板路由，避免节点执行/失败后预探测请求阻塞，导致看起来“面板打不开”。
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
    if (panel) {
      hideLauncherStateBar();
      return;
    }

    panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.className = "ok";
    panel.innerHTML = `
      <div class="wr-head" title="按住这里可以拖动浮窗">
        <div class="wr-logo">🎨</div>
        <div class="wr-title">
          <strong>Hrio Design｜设计师生成</strong>
          <span>平面设计 · 室内设计 · 提示词手动 · 自动化全节点</span>
        </div>
      </div>
      <div class="wr-grid compact">
        <button class="wr-btn full" data-open-editor type="button">打开Hrio Design模板面板</button>
        <button class="wr-btn secondary" data-automation type="button">自动化</button>
        <button class="wr-btn secondary" data-video-view type="button">查看视频</button>
        <button class="wr-btn secondary" data-clear-automation type="button">清除自动化</button>
        <button class="wr-btn secondary" data-history type="button">历史记录</button>
      </div>

      <div class="wr-foot compact">
        提示词配置只同步 Hrio Design 设计师模板面板节点；普通单图、普通三方案、普通视频和视频生成节点的手动提示词不会被覆盖；自动化 payload 仍会应用到所有带 automation_payload 的节点。
      </div>
    `;

    panel.querySelector("[data-open-editor]").onclick = () => {
      openTemplateEditor();
    };

    panel.querySelector("[data-automation]").onclick = () => {
      openAutomationModal();
    };

    panel.querySelector("[data-video-view]").onclick = () => {
      openVideoModal();
    };

    panel.querySelector("[data-clear-automation]").onclick = () => {
      clearAutomationPayloadFromNodes(true);
    };

    panel.querySelector("[data-history]").onclick = () => {
      openHistoryModal();
    };

    document.body.appendChild(panel);
    hideLauncherStateBar();
    applySavedFloatPosition(panel);
    makeLauncherDraggable(panel);
  }

  function hideLauncherStateBar() {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;
    try {
      panel.querySelectorAll(".wr-state").forEach((el) => el.remove());
    } catch {}
  }

  function setLauncherState(text, kind = "ok", options = {}) {
    // 状态栏已取消显示：只记录内部状态，不再写入浮窗 DOM。
    // 这样保留所有调用兼容性，同时彻底避免状态条闪烁。
    const message = String(text || "就绪");
    const normalizedKind = kind === "normal" ? "ok" : (kind || "ok");
    state.launcher.lastText = message;
    state.launcher.lastKind = normalizedKind;
    state.launcher.lastUpdatedAt = Date.now();
    state.launcher.lastActionKey = String(options?.actionKey || message);
    hideLauncherStateBar();
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

  function isAutomationWidgetName(value) {
    const n = normalizeWidgetName(value);
    if (!n) return false;
    return (
      n === "automation_payload" ||
      n === "hrio_design_automation_payload" ||
      n === "banana_automation_payload" ||
      n === "自动化映射" ||
      n.includes("automation_payload") ||
      String(value || "").includes("自动化映射")
    );
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
      (hasPrompt && hasImageModel && !hasWidget(node, ["front_prompt", "方案A提示词", "side_prompt", "back_prompt"]))
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

    if (text.includes("Hrio_Design") || text.includes("HrioBanana") || text.includes("Hrio Design")) {
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
      if (!widget.__hrioOriginalWidgetState) {
        widget.__hrioOriginalWidgetState = {
          type: widget.type,
          label: widget.label,
          name: widget.name,
          disabled: widget.disabled,
          hidden: widget.hidden,
          computeSize: widget.computeSize,
          draw: widget.draw,
          options: Object.assign({}, widget.options || {}),
        };
      }
      widget.hidden = true;
      widget.disabled = true;
      widget.serialize = true;
      widget.label = "";
      widget.type = "hidden";
      widget.options = Object.assign({}, widget.options || {}, { hidden: true, minHeight: 0, maxHeight: 0 });
      widget.computeSize = () => [0, -4];
      widget.draw = () => {};
      widget.last_y = -100000;
      widget.y = -100000;

      const els = [widget.inputEl, widget.element, widget.domElement, widget.textElement, widget.textarea].filter(Boolean);
      for (const el of els) {
        if (!el || !el.style) continue;
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

  function showWidgetOnNode(node, widget) {
    if (!node || !widget) return;
    try {
      const backup = widget.__hrioOriginalWidgetState || {};
      widget.hidden = false;
      widget.disabled = false;
      widget.serialize = true;
      widget.type = backup.type && backup.type !== "hidden" ? backup.type : "text";
      widget.name = backup.name || widget.name || "automation_payload";
      widget.label = backup.label || "自动化映射";
      widget.options = Object.assign({}, backup.options || widget.options || {}, { hidden: false });
      if (backup.computeSize) widget.computeSize = backup.computeSize;
      else delete widget.computeSize;
      if (backup.draw) widget.draw = backup.draw;
      else delete widget.draw;
      widget.last_y = 0;
      widget.y = 0;

      const els = [widget.inputEl, widget.element, widget.domElement, widget.textElement, widget.textarea].filter(Boolean);
      for (const el of els) {
        if (!el || !el.style) continue;
        el.style.display = "";
        el.style.visibility = "";
        el.style.height = "";
        el.style.minHeight = "";
        el.style.maxHeight = "";
        el.style.opacity = "";
        el.style.pointerEvents = "";
      }
    } catch {}
  }

  function findAutomationToggleWidget(node) {
    const widgets = Array.isArray(node?.widgets) ? node.widgets : [];
    return widgets.find((widget) => widget && (widget[AUTOMATION_TOGGLE_WIDGET_MARK] || normalizeWidgetName(widget.name).startsWith("hrio_automation_toggle"))) || null;
  }

  function refreshAutomationPayloadVisibility(node) {
    const widget = findWidget(node, ["automation_payload", "自动化映射"]);
    if (!widget) return;
    const expanded = !!node?.properties?.hrio_automation_payload_expanded;
    if (expanded) showWidgetOnNode(node, widget);
    else hideWidgetOnNode(node, widget);

    const toggle = findAutomationToggleWidget(node);
    if (toggle) {
      toggle.name = expanded ? "自动化（点击收起 JSON）" : "自动化（默认隐藏，点击展开）";
      toggle.label = toggle.name;
      toggle.serialize = false;
    }
  }

  function ensureAutomationToggleWidget(node) {
    if (!node || !findWidget(node, ["automation_payload", "自动化映射"])) return;
    let toggle = findAutomationToggleWidget(node);
    if (!toggle && typeof node.addWidget === "function") {
      try {
        toggle = node.addWidget("button", "自动化（默认隐藏，点击展开）", null, () => {
          node.properties = node.properties || {};
          node.properties.hrio_automation_payload_expanded = !node.properties.hrio_automation_payload_expanded;
          refreshAutomationPayloadVisibility(node);
          markCanvasDirty(node);
        });
      } catch {}
    }
    if (toggle) {
      toggle[AUTOMATION_TOGGLE_WIDGET_MARK] = true;
      toggle.serialize = false;
      toggle.callback = () => {
        node.properties = node.properties || {};
        node.properties.hrio_automation_payload_expanded = !node.properties.hrio_automation_payload_expanded;
        refreshAutomationPayloadVisibility(node);
        markCanvasDirty(node);
      };
    }
    refreshAutomationPayloadVisibility(node);
  }

  function shouldDropPromptNoiseWidgetName(widgetName) {
    const n = normalizeWidgetName(widgetName);
    if (!n) return false;

    const exact = new Set([
      "global_prompt",
      "common_prompt",
      "shared_prompt",
      "common_negative_prompt",
      "global_negative_prompt",
      "negative_prompt",
      "共同提示词",
      "共同限定词",
      "全局提示词",
      "全局限定词",
      "负面提示词",
      "负面限定词",
    ]);
    if (exact.has(n)) return true;

    const raw = String(widgetName || "");
    if (raw.includes("共同提示词") || raw.includes("共同限定词")) return true;
    if (raw.includes("全局提示词") || raw.includes("全局限定词")) return true;
    if (raw.includes("负面提示词") || raw.includes("负面限定词")) return true;

    if (n.includes("global") && n.includes("prompt")) return true;
    if (n.includes("common") && n.includes("prompt")) return true;
    if (n.includes("shared") && n.includes("prompt")) return true;
    if (n.includes("negative") && n.includes("prompt")) return true;

    return false;
  }

  function dropPromptNoiseWidgets(node) {
    if (!node || !Array.isArray(node.widgets)) return false;

    let changed = false;
    for (let i = node.widgets.length - 1; i >= 0; i -= 1) {
      const widget = node.widgets[i];
      const candidates = [
        widget?.name,
        widget?.label,
        widget?.displayName,
        widget?.localized_name,
      ].filter(Boolean);

      if (!candidates.some(shouldDropPromptNoiseWidgetName)) continue;

      node.widgets.splice(i, 1);
      try {
        if (Array.isArray(node.widgets_values)) node.widgets_values.splice(i, 1);
      } catch {}
      changed = true;
    }

    if (changed) {
      try {
        node.properties = node.properties || {};
        delete node.properties.global_prompt;
        delete node.properties.common_prompt;
        delete node.properties.shared_prompt;
        delete node.properties.common_negative_prompt;
        delete node.properties.global_negative_prompt;
        delete node.properties.negative_prompt;
        delete node.properties["共同提示词"];
        delete node.properties["共同限定词"];
        delete node.properties["全局提示词"];
        delete node.properties["全局限定词"];
        delete node.properties["负面提示词"];
        delete node.properties["负面限定词"];
      } catch {}
      markCanvasDirty(node);
    }

    return changed;
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
          dropPromptNoiseWidgets(node);
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
              refreshAutomationPayloadVisibility(node);
            }
          });
          ensureAutomationToggleWidget(node);
          autoClearStaleAutomationPayloadOnNode(node);
        }

        const targetWidth = (kind === "video" || kind === "normal_video") ? 360 : (kind === "normal_single" ? 420 : 430);
        const targetHeight = (kind === "video" || kind === "normal_video") ? 500 : (kind === "normal_single" ? 500 : 500);
        if (typeof node.setSize === "function" && node.size) {
          const w = Math.max(Number(node.size[0] || 0), targetWidth);
          node.setSize([w, targetHeight]);
        } else if (Array.isArray(node.size)) {
          node.size[0] = Math.max(Number(node.size[0] || 0), targetWidth);
          node.size[1] = targetHeight;
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
    // v8.1.3：只允许“设计师模板面板节点”接收模板配置同步。
    // 普通单图、普通三方案、普通生视频、独立视频生成节点全部保持用户手动输入，
    // 不再被右下角面板、打开面板、刷新配置、重抽、自动化等动作覆盖提示词。
    if (!node || !promptPack || kind !== "panel") return;

    try {
      node.properties = node.properties || {};
      node.properties["hrio_design_template_synced_only"] = true;
      node.properties["hrio_design_prompt_synced_at"] = Date.now();
    } catch {}
  }

  function applyConfigToNodes(command) {
    const config = command.config || command.prompt_config || {};
    const modeOptions = command.mode_options || config.mode_options || {};
    const modeTitle = command.current_mode_title || firstTitleByKey(modeOptions, command.current_mode_key) || "";
    const modeKey = command.current_mode_key || modeOptions[modeTitle] || "";
    const nodes = targetNodes().filter((node) => bananaNodeKind(node) === "panel");
    const promptPack = buildDesignerNodePrompts(command, config, modeKey, modeTitle);

    if (!nodes.length) {
      setLauncherState("未找到 Hrio Design 设计师模板节点，请先添加“🎨 Hrio Design｜设计师模板面板”", "error");
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
    setLauncherState(`已同步模板节点：${modeTitle || modeKey || "配置"}`, "syncing");
    setTimeout(() => setLauncherState("普通节点保持手动输入，不会被覆盖", "ok", { passive: true }), 900);
  }

  function applyRetryToNodes(command) {
    const modeTitle = command.mode_title || command.current_mode_title || "";
    const modeKey = command.mode_key || command.current_mode_key || "";
    const view = command.view || command.variant_key || "all";
    const scope = VIEW_SCOPE_MAP[view] || VIEW_SCOPE_MAP.all;
    const nodes = automationWidgetNodes();
    const config = command.config || command.prompt_config || state.lastConfig || {};
    const promptPack = buildDesignerNodePrompts(command, config, modeKey, modeTitle);

    if (!nodes.length) {
      setLauncherState("未找到 Hrio Design 自动化节点", "error");
      return;
    }

    nodes.forEach((node) => {
      const kind = bananaNodeKind(node);

      // 模板相关 mode / labels 只写模板面板；普通节点保持手动。
      if (kind === "panel") {
        if (modeTitle) {
          setWidgetValue(node, ["mode", "模式", "生成模式", "提示词模板"], modeTitle);
        }

        if (modeKey) {
          setWidgetValue(node, ["mode_actual", "mode_key", "模式key"], modeKey);
        }

        setWidgetValue(node, ["labels_prefix", "label_prefix", "标题前缀"], modeTitle || modeKey);
        applyDesignerPromptsToNode(node, kind, promptPack);
      }

      // 自动化 / 重跑范围是全节点：只要节点有对应 widget 就写入。
      setWidgetValue(node, ["generate_scope", "生成范围", "重跑范围"], scope);

      const automationPayload = parseAutomationPayloadFromNode(node);
      const automationEnabled = automationPayload && automationPayload.enabled !== false && Array.isArray(automationPayload.input_roots);
      if (automationEnabled) {
        const nextAutomationPayload = automationPayloadForRetry(automationPayload, command, view);
        forceSetAutomationWidgetValue(node, JSON.stringify(nextAutomationPayload, null, 2));
      } else {
        const cacheKey = command.group?.cache_key || command.cache_key || "";
        if (cacheKey) {
          setWidgetValue(node, ["cache_key", "缓存key"], cacheKey);
        }
      }
    });

    beautifyTargetNodes();
    setLauncherState(`全节点自动化重跑：${scope}`, "syncing");

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
      setTimeout(() => setLauncherState("模板节点已自动美化", "ok", { passive: true }), 800);
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

      setLauncherState("提示词只同步模板节点；自动化保持全节点", "ok");
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

          // ── PATCH v2：只拦截节点底部缩略图，不破坏媒体资产面板 ──────────────
          // ComfyUI 的执行顺序是：
          // 1) WS 收到 executed 后，先把 output 写入 app.nodeOutputs[nodeId]；
          // 2) 再调用 node.onExecuted(output)；
          // 3) 默认 onExecuted 会把 ui.images 写到 node.imgs，从而渲染节点底部缩略图。
          // 所以这里在原始 onExecuted 之后清空 node.imgs：
          // - 左侧媒体资产面板仍然能读 app.nodeOutputs；
          // - 节点底部不再显示重复缩略图；
          // - 不会影响自动化/历史 JSON 缓存。
          if (!node.__hrioNoBottomPreviewPatchedV2) {
            node.__hrioNoBottomPreviewPatchedV2 = true;
            const _origOnExecuted = typeof node.onExecuted === "function" ? node.onExecuted.bind(node) : null;
            node.onExecuted = function(message) {
              let result;
              try {
                if (_origOnExecuted) result = _origOnExecuted(message);
              } finally {
                try {
                  this.imgs = null;
                  this.imageIndex = null;
                  this.overIndex = null;
                  this._imageIndex = null;
                  this._imgs = null;
                } catch (_e) {}

                try {
                  const app = getApp();
                  if (app && app.graph && typeof app.graph.setDirtyCanvas === "function") {
                    app.graph.setDirtyCanvas(true, false);
                  } else {
                    const canvas = getCanvas();
                    if (canvas && typeof canvas.setDirty === "function") canvas.setDirty(true, false);
                  }
                } catch (_e) {}
              }
              return result;
            };
          }
          // ─────────────────────────────────────────────────────────────────

          setTimeout(() => {
            beautifyTargetNodes();
            ensureAutomationToggleWidget(node);
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

  function createVideoModal() {
    injectStyle();

    let modal = document.getElementById(VIDEO_MODAL_ID);
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = VIDEO_MODAL_ID;
    modal.innerHTML = `
      <div class="video-card">
        <div class="video-head">
          <div>
            <strong>Hrio Design｜生成视频预览</strong>
            <span>显示最近由 Hrio 视频节点下载到 ComfyUI temp 的视频。</span>
          </div>
          <div class="video-actions">
            <button class="video-btn" data-video-refresh type="button">刷新</button>
            <button class="video-close" data-video-close type="button">×</button>
          </div>
        </div>
        <div class="video-body" data-video-list>
          <div class="video-empty">正在读取视频记录...</div>
        </div>
      </div>
    `;

    const close = () => modal.classList.remove("show");
    modal.querySelector("[data-video-close]").onclick = close;
    modal.querySelector("[data-video-refresh]").onclick = () => refreshVideoModal(true);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) close();
    });

    document.body.appendChild(modal);
    return modal;
  }

  function videoViewUrlFromItem(item) {
    const direct = String(item?.view_url || item?.url || "").trim();
    if (direct) return direct;
    const filename = String(item?.filename || "").trim();
    if (!filename) return "";
    const params = new URLSearchParams({
      filename,
      type: String(item?.type || "temp"),
      subfolder: String(item?.subfolder || ""),
    });
    return "/view?" + params.toString();
  }

  function renderVideoModal(videos) {
    const modal = document.getElementById(VIDEO_MODAL_ID);
    if (!modal) return;
    const list = modal.querySelector("[data-video-list]");
    if (!list) return;

    const items = Array.isArray(videos) ? videos : [];
    if (!items.length) {
      list.innerHTML = `<div class="video-empty">暂无视频记录。请先运行“🎨 Hrio｜生视频”或“🎨 Hrio｜普通生视频（单输出）”，生成成功后这里会显示最近视频。</div>`;
      return;
    }

    list.innerHTML = items.slice(0, 20).map((item, index) => {
      const url = videoViewUrlFromItem(item);
      const label = escapeHtml(item.label || `视频 ${index + 1}`);
      const when = item.updated_at_ms ? new Date(Number(item.updated_at_ms)).toLocaleString() : "";
      const filename = escapeHtml(item.filename || item.local_path || item.source_url || "");
      const mime = escapeHtml(item.mime || item.format || "video/mp4");
      if (!url) {
        return `<div class="video-empty">${label} 没有可播放地址：${filename}</div>`;
      }
      return `
        <div class="video-item">
          <div class="video-item-head">
            <div><strong>${label}</strong><div>${escapeHtml(when)} · ${filename}</div></div>
            <a class="video-btn" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">新窗口打开</a>
          </div>
          <video controls preload="metadata" src="${escapeHtml(url)}" type="${mime}"></video>
        </div>
      `;
    }).join("");
  }

  async function refreshVideoModal(announce = false) {
    const modal = createVideoModal();
    const list = modal.querySelector("[data-video-list]");
    if (list) list.innerHTML = `<div class="video-empty">正在读取视频记录...</div>`;
    try {
      const data = await getJson(RUNTIME_ROUTE);
      const videos = Array.isArray(data.videos) ? data.videos : [];
      renderVideoModal(videos);
      if (announce) setLauncherState(`已读取视频：${videos.length} 条`, "ok");
    } catch (error) {
      if (list) list.innerHTML = `<div class="video-empty">视频记录读取失败：${escapeHtml(error.message || error)}</div>`;
      if (announce) setLauncherState(`视频读取失败：${error.message || error}`, "error");
    }
  }

  function openVideoModal() {
    const modal = createVideoModal();
    modal.classList.add("show");
    refreshVideoModal(false);
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
            <span>选择最多 10 个输入项目根目录；输出根目录可留空，后端会自动写入 ComfyUI/output/hrio_design_automation。后端递归扫描根目录及子文件夹，按图片文件名数字或父文件夹数字序号横向聚合并发执行。</span>
          </div>
          <button class="auto-close" data-auto-close type="button">×</button>
        </div>

        <div class="auto-body">
          <div class="auto-row">
            <div class="auto-box">
              <h3>输入根目录</h3>
              <div class="auto-muted">每个根目录可以直接放图片，例如 001.png、002.png；也可以放项目子文件夹，例如 001/front.png、001/reference.jpg。序号规则：优先提取图片文件名数字；文件名没有数字时使用最近父文件夹数字。</div>
              <div class="auto-actions">
                <button class="auto-btn" data-auto-add-input-root type="button">添加输入根目录</button>
                <button class="auto-btn secondary" data-auto-clear-input-root type="button">清空输入</button>
              </div>
              <div class="auto-list" data-auto-input-root-list></div>
            </div>

            <div class="auto-box">
              <h3>输出根目录</h3>
              <div class="auto-muted">每个序号组会输出到 output_序号/run_01/，例如 output_001/run_01/front.png。可留空，后端自动使用 ComfyUI/output/hrio_design_automation。</div>
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
              <div class="auto-muted">可先预览分组确认序号；也可以直接应用并运行，后端会按 JSON/input_roots 自行扫描。普通图像节点会上传每组参考图并多次重试生成，生视频节点会上传参考图并轮询视频任务。</div>
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

    modal.querySelectorAll("[data-auto-copy]").forEach((btn) => {
      btn.onclick = () => {
        const payload = buildAutomationPayload();
        navigator.clipboard?.writeText(JSON.stringify(payload, null, 2)).catch(() => {});
        setLauncherState("自动化 JSON 已复制", "syncing");
        setTimeout(() => setLauncherState("模板节点已自动美化", "ok", { passive: true }), 900);
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
    scheduleAutomationPreview(260);
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
      scheduleAutomationPreview(180);
      setLauncherState("已添加输入根目录，正在自动预览分组", "ok");
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
      scheduleAutomationPreview(180);
      setLauncherState("已选择输出根目录，正在自动预览分组", "ok");
    } catch (error) {
      console.warn("[Hrio Design] select output root failed:", error);
      setLauncherState(`选择失败：${error.message || error}`, "warn");
    }
  }

  function canPreviewAutomationGroups() {
    return Array.isArray(state.automation.inputRoots) && state.automation.inputRoots.length > 0;
  }

  function scheduleAutomationPreview(delay = 350) {
    if (automationPreviewTimer) {
      clearTimeout(automationPreviewTimer);
      automationPreviewTimer = null;
    }
    if (!canPreviewAutomationGroups()) return;
    const modal = document.getElementById(MODAL_ID);
    if (!modal || !modal.classList.contains("show")) return;
    automationPreviewTimer = setTimeout(() => {
      automationPreviewTimer = null;
      previewAutomationGroups({ silent: true });
    }, Math.max(0, Number(delay) || 0));
  }

  async function previewAutomationGroups(options = {}) {
    const silent = !!options.silent;
    try {
      const payload = buildAutomationPayload();
      if (!payload.input_roots.length) throw new Error("请先添加输入根目录");
      // 预览缩略图不强制要求输出目录；没选输出目录时，只是不显示最终 output_序号/run_01 路径。
      if (!silent) setLauncherState("正在预览自动化分组缩略图...", "syncing");
      const data = await postJson(AUTOMATION_PREVIEW_ROUTE, payload);
      state.automation.previewGroups = Array.isArray(data.groups) ? data.groups : [];
      state.automation.lastPreview = data || null;
      renderAutomationModal(false);
      const summary = data && data.scan_summary ? data.scan_summary : {};
      const imageCount = Number(summary.image_count || 0);
      const groupCount = state.automation.previewGroups.length;
      if (groupCount) {
        setLauncherState(`已预览 ${groupCount} 个序号组，输入图 ${imageCount} 张`, "ok");
      } else {
        setLauncherState(`已扫描 ${imageCount} 张图片，但没有形成序号组`, "warn");
      }
    } catch (error) {
      console.warn("[Hrio Design] preview automation failed:", error);
      state.automation.lastPreview = {
        ok: false,
        error: error && error.message ? error.message : String(error),
        scan_reports: [],
        scan_summary: {},
      };
      renderAutomationModal(false);
      if (!silent) setLauncherState(`预览失败：${error.message || error}`, "warn");
      else setLauncherState(`自动预览失败：${error.message || error}`, "warn");
    }
  }

  function automationPreviewItems(group) {
    if (!group || typeof group !== "object") return [];
    if (Array.isArray(group.preview_items) && group.preview_items.length) return group.preview_items;
    if (Array.isArray(group.items)) return group.items;
    return [];
  }


  function renderAutomationScanReport(reports) {
    reports = Array.isArray(reports) ? reports : [];
    if (!reports.length) return "";
    return `<div class="auto-scan-report">${reports.map((r) => {
      const idx = Number(r.root_index || 0) + 1;
      const path = String(r.root_path || "");
      const exists = !!r.exists;
      const scanned = Number(r.scanned_file_count || 0);
      const images = Number(r.image_count || 0);
      const seqs = Number(r.sequence_count || 0);
      const noSeq = Number(r.skipped_no_sequence_count || 0);
      const err = String(r.error || "");
      const status = exists ? `${images} 图 / ${seqs} 组${noSeq ? ` / ${noSeq} 张无序号` : ""}` : "目录不存在";
      return `
        <div class="auto-scan-report-row" title="${escapeHtml(path + (err ? "\n" + err : ""))}">
          <code>${idx}</code>
          <div class="auto-scan-report-path">${escapeHtml(path || "-")}</div>
          <div class="auto-scan-report-stat">${escapeHtml(err || status)} · 扫描 ${scanned}</div>
        </div>
      `;
    }).join("")}</div>`;
  }

  function renderAutomationInputPreview(group) {
    const items = automationPreviewItems(group);
    if (!items.length) return `<div class="auto-muted">未找到输入图</div>`;

    return `<div class="auto-thumb-grid">${items.map((item) => {
      const rootIndex = Number(item.root_index || 0) + 1;
      const fileName = String(item.relative_path || item.file_name || item.image_path || "");
      const imagePath = String(item.image_path || "");
      const thumb = String(item.thumb_data_url || item.preview_data_url || item.thumbnail || "");
      const width = Number(item.width || 0);
      const height = Number(item.height || 0);
      const sizeText = width && height ? `${width}×${height}` : "";
      const title = `${rootIndex}. ${fileName}${imagePath ? "\n" + imagePath : ""}${sizeText ? "\n" + sizeText : ""}`;
      const imgHtml = thumb
        ? `<img src="${escapeHtml(thumb)}" alt="${escapeHtml(fileName)}" title="${escapeHtml(title)}" data-auto-thumb data-auto-thumb-title="${escapeHtml(title)}" />`
        : `<div class="auto-thumb-empty" title="${escapeHtml(item.preview_error || imagePath || fileName)}">无图</div>`;
      return `
        <div class="auto-thumb-card" title="${escapeHtml(title)}">
          ${imgHtml}
          <div class="auto-thumb-meta">${rootIndex}. ${escapeHtml(fileName || "图片")}</div>
          <div class="auto-thumb-sub">${escapeHtml(sizeText || "input")}</div>
        </div>
      `;
    }).join("")}</div>`;
  }

  function openAutomationImagePreview(src, title = "") {
    src = String(src || "").trim();
    if (!src) return;
    const old = document.querySelector(".hrio-auto-image-lightbox");
    if (old) old.remove();
    const box = document.createElement("div");
    box.className = "hrio-auto-image-lightbox";
    box.innerHTML = `
      <div class="hrio-auto-image-lightbox-inner">
        <img src="${escapeHtml(src)}" alt="${escapeHtml(title || "preview")}" />
        <div class="hrio-auto-image-lightbox-caption">${escapeHtml(title || "点击空白处关闭")}</div>
      </div>
    `;
    box.addEventListener("click", (event) => {
      if (event.target === box) box.remove();
    });
    document.addEventListener("keydown", function onKeydown(event) {
      if (event.key === "Escape") {
        box.remove();
        document.removeEventListener("keydown", onKeydown);
      }
    });
    document.body.appendChild(box);
  }

  function sanitizeAutomationPreviewGroups(groups) {
    return (Array.isArray(groups) ? groups : []).map((group) => ({
      sequence: String(group.sequence || ""),
      output_dir: String(group.output_dir || ""),
      present_root_count: Number(group.present_root_count || 0),
      expected_root_count: Number(group.expected_root_count || 0),
      preview_count: Number(group.preview_count || automationPreviewItems(group).length || 0),
      items: (Array.isArray(group.items) ? group.items : []).map((item) => ({
        root_index: Number(item.root_index || 0),
        root_path: String(item.root_path || ""),
        source_type: String(item.source_type || "root_image"),
        file_name: String(item.file_name || ""),
        image_path: String(item.image_path || ""),
        sequence: String(item.sequence || group.sequence || ""),
      })),
    }));
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
    const lastPreview = state.automation.lastPreview || null;
    const scanReports = lastPreview && Array.isArray(lastPreview.scan_reports) ? lastPreview.scan_reports : [];
    const scanSummary = lastPreview && lastPreview.scan_summary ? lastPreview.scan_summary : null;
    if (summary) {
      if (groups.length) {
        const imageCount = scanSummary ? Number(scanSummary.image_count || 0) : 0;
        summary.textContent = `已预览 ${groups.length} 个序号组，输入图 ${imageCount || ""} 张。执行时每个组只跑一次，最多 ${state.automation.groupConcurrency || 3} 组并发。`;
      } else if (lastPreview) {
        const imageCount = scanSummary ? Number(scanSummary.image_count || 0) : 0;
        const noSeq = scanSummary ? Number(scanSummary.skipped_no_sequence_count || 0) : 0;
        summary.textContent = `已递归扫描 ${scanReports.length} 个输入目录，找到 ${imageCount} 张图片，形成 0 个序号组${noSeq ? `；${noSeq} 张图片没有数字序号` : ""}。`;
      } else {
        summary.textContent = canPreviewAutomationGroups() ? "已添加输入目录，正在等待预览。" : "尚未预览。";
      }
    }

    const list = modal.querySelector("[data-auto-preview-list]");
    if (list) {
      if (!groups.length) {
        const reportHtml = renderAutomationScanReport(scanReports);
        const errorText = lastPreview && lastPreview.error ? `<div class="auto-muted">预览失败：${escapeHtml(lastPreview.error)}</div>` : "";
        const hint = canPreviewAutomationGroups()
          ? `没有扫描到可分组图片。请确认图片或父文件夹包含数字序号，例如 <code>001.png</code>、<code>001/front.png</code>。`
          : `点击“添加输入根目录”后会自动预览分组。`;
        list.innerHTML = `<tr><td colspan="4" class="auto-muted"><div>${hint}</div>${errorText}${reportHtml}</td></tr>`;
      } else {
        list.innerHTML = groups.map((g) => {
          const previewItems = automationPreviewItems(g);
          const rawItems = previewItems.map((it) => `${Number(it.root_index || 0) + 1}. ${it.relative_path || it.file_name || it.image_path || ""}`);
          const seq = String(g.sequence || "");
          const outDir = String(g.output_dir || "");
          const countText = `${previewItems.length}/${g.expected_root_count || state.automation.inputRoots.length || previewItems.length}`;
          return `
            <tr>
              <td><code>${escapeHtml(seq)}</code><div class="auto-thumb-sub">${escapeHtml(countText)} 张</div></td>
              <td title="${escapeHtml(rawItems.join("\n"))}">${renderAutomationInputPreview(g)}</td>
              <td title="${escapeHtml(outDir)}"><div class="auto-cell-main">${escapeHtml(outDir)}</div></td>
              <td><button class="auto-btn secondary" style="height:28px;padding:0 8px;" data-auto-run-group="${escapeHtml(seq)}" type="button">跑本组</button></td>
            </tr>
          `;
        }).join("");
        list.querySelectorAll("[data-auto-thumb]").forEach((img) => {
          img.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            openAutomationImagePreview(img.getAttribute("src"), img.getAttribute("data-auto-thumb-title") || img.getAttribute("title") || "");
          });
        });
      }
    }
  }

  function buildAutomationPayload() {
    return {
      enabled: true,
      type: "banana_sequence_group_automation",
      version: "8.2.2",
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
      preview_groups: sanitizeAutomationPreviewGroups(state.automation.previewGroups || []),
    };
  }

  function runAutomationGroupsFromModal(sequence = null) {
    try {
      const payload = buildAutomationPayload();
      if (!payload.input_roots.length && !(Array.isArray(payload.preview_groups) && payload.preview_groups.length)) {
        throw new Error("请先添加输入根目录，或粘贴包含 preview_groups 的自动化 JSON");
      }

      const groups = state.automation.previewGroups || [];

      if (sequence) {
        const seq = String(sequence);
        const found = groups.some((g) => String(g.sequence || "") === seq);
        if (groups.length && !found) throw new Error(`预览列表里没有序号 ${seq}`);
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
      queueGraphDebounced(2400);
    } catch (error) {
      setLauncherState(`运行失败：${error.message || error}`, "error");
    }
  }

  function parseAutomationPayloadFromNode(node) {
    const candidates = [];
    const widget = findWidget(node, ["automation_payload", "自动化映射"]);
    if (widget) candidates.push(widget.value);
    if (node && node.properties) {
      candidates.push(node.properties.hrio_design_automation_payload);
      candidates.push(node.properties.banana_automation_payload);
      candidates.push(node.properties.automation_payload);
      candidates.push(node.properties["自动化映射"]);
    }
    for (const value of candidates) {
      if (!value) continue;
      try {
        const data = typeof value === "string" ? JSON.parse(value) : value;
        if (data && typeof data === "object") return data;
      } catch {}
    }
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
    if (!node) return 0;
    let count = 0;
    const widgets = Array.isArray(node.widgets) ? node.widgets : [];
    widgets.forEach((widget, index) => {
      const name = widget?.name || widget?.label || widget?.displayName || widget?.localized_name;
      if (!isAutomationWidgetName(name)) return;
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
      if (value) {
        node.properties.hrio_design_automation_payload = value;
        node.properties.banana_automation_payload = value;
        node.properties.automation_payload = value;
        node.properties["自动化映射"] = value;
        node.properties.banana_automation_disabled = false;
        delete node.properties.banana_automation_cleared_at;
      } else {
        delete node.properties.hrio_design_automation_payload;
        delete node.properties.banana_automation_payload;
        delete node.properties.automation_payload;
        delete node.properties["自动化映射"];
        node.properties.banana_automation_cleared_at = Date.now();
        node.properties.banana_automation_disabled = true;
      }
    } catch {}

    refreshAutomationPayloadVisibility(node);
    markCanvasDirty(node);
    return count || (isTemplateNode(node) ? 1 : 0);
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
    if (!node) return false;
    let changed = false;
    const widgets = Array.isArray(node.widgets) ? node.widgets : [];
    widgets.forEach((widget, index) => {
      const name = widget?.name || widget?.label || widget?.displayName || widget?.localized_name;
      if (!isAutomationWidgetName(name)) return;
      const value = widget?.value;
      if (shouldClearAutomationValue(value)) {
        widget.value = "";
        clearWidgetDomValue(widget, "");
        if (!Array.isArray(node.widgets_values)) node.widgets_values = [];
        node.widgets_values[index] = "";
        changed = true;
      }
    });
    try {
      const props = node.properties || {};
      const propValue = props.hrio_design_automation_payload || props.automation_payload || props["自动化映射"];
      if (shouldClearAutomationValue(propValue)) {
        node.properties = props;
        delete node.properties.hrio_design_automation_payload;
        delete node.properties.banana_automation_payload;
        delete node.properties.automation_payload;
        delete node.properties["自动化映射"];
        changed = true;
      }
    } catch {}

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
    // 自动化 payload 是全节点能力：识别到的 Hrio 节点全部参与。
    // 即使旧工作流里暂时没有 automation_payload widget，也会写入 node.properties，后端会从 PROMPT / EXTRA_PNGINFO 读取。
    // 普通单图、普通三方案、普通视频和视频生成节点的手动提示词不会被模板面板覆盖。
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
      const rawName = widget?.name || widget?.label || widget?.displayName || widget?.localized_name;
      const name = normalizeWidgetName(rawName);
      if (normalizedName === "automation_payload") {
        if (!isAutomationWidgetName(rawName)) return;
      } else if (name !== normalizedName) return;
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
      node.properties = node.properties || {};
      if (value) {
        node.properties.hrio_design_automation_payload = value;
        node.properties.banana_automation_payload = value;
        node.properties.automation_payload = value;
        node.properties["自动化映射"] = value;
        node.properties.banana_automation_disabled = false;
        delete node.properties.banana_automation_cleared_at;
      } else {
        delete node.properties.hrio_design_automation_payload;
        delete node.properties.banana_automation_payload;
        delete node.properties.automation_payload;
        delete node.properties["自动化映射"];
        node.properties.banana_automation_disabled = true;
        node.properties.banana_automation_cleared_at = Date.now();
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
      setTimeout(() => setLauncherState("全节点 automation_payload 已清空；普通节点提示词保持不变", "ok", { passive: true }), 1000);
    }
  }

  function applyAutomationPayload(payload, announce = true, options = {}) {
    if (!payload || typeof payload !== "object") return;
    if (!Array.isArray(payload.input_roots)) payload.input_roots = [];
    if (!payload.input_roots.length && !Array.isArray(payload.preview_groups)) return;

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

    payload = Object.assign({}, payload, { created_at: createdAt || now, enabled: payload.enabled !== false });
    try {
      localStorage.setItem(AUTOMATION_STORAGE_KEY, JSON.stringify(payload));
    } catch {}

    const payloadText = JSON.stringify(payload, null, 2);

    const writeOnce = () => {
      // 先美化/清理旧的共同/负面提示词控件，再写入 automation_payload。
      beautifyTargetNodes();
      const nodes = automationWidgetNodes();
      let appliedCount = 0;

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
        } else {
          try {
            node.properties = node.properties || {};
            node.properties.hrio_design_automation_payload = payloadText;
            node.properties.banana_automation_payload = payloadText;
            node.properties.automation_payload = payloadText;
            node.properties["自动化映射"] = payloadText;
            appliedCount += 1;
          } catch {}
        }
      });

      return { nodes, appliedCount };
    };

    const first = writeOnce();

    // ComfyUI 会异步回写右侧属性面板 / widgets_values，多次压入保证入队时节点能读到自动化映射。
    [80, 180, 360, 620, 1000, 1600, 2400, 3600, 5200].forEach((ms) => setTimeout(writeOnce, ms));

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
      setLauncherState(`自动化已应用：${groupCount} 组 / ${first.appliedCount} 个节点`, "syncing");
      setTimeout(() => setLauncherState("自动化 JSON 已写入全部可自动化节点后台，等待队列运行", "ok", { passive: true }), 1200);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }


  function runtimeGroupVisibleVariantKeys(group) {
    const keys = Array.isArray(group?.visible_variants) && group.visible_variants.length
      ? group.visible_variants.map((x) => String(x || "")).filter(Boolean)
      : ((String(group?.output_strategy || "").toLowerCase() === "single_image" || String(group?.node_type || "").includes("single_image"))
        ? ["variant_a"]
        : ["variant_a", "variant_b", "variant_c"]);
    return keys.length ? keys : ["variant_a"];
  }

  function runtimeGroupMediaItems(group) {
    const views = group?.views && typeof group.views === "object" ? group.views : {};
    const slotMap = { variant_a: "front.png", variant_b: "side.png", variant_c: "back.png", front: "front.png", side: "side.png", back: "back.png" };
    const media = [];
    runtimeGroupVisibleVariantKeys(group).forEach((key) => {
      const item = views[key] || null;
      const url = String(item?.view_url || item?.url || item?.image || "").trim();
      const mediaRef = item?.media && typeof item.media === "object" ? item.media : {};
      if (!url && !mediaRef.path && !mediaRef.local_path) return;
      const slot = String(mediaRef.slot || mediaRef.filename || mediaRef.name || slotMap[key] || `${key}.png`);
      media.push({
        slot,
        kind: "image",
        view_url: url,
        url,
        path: String(mediaRef.path || mediaRef.local_path || ""),
        local_path: String(mediaRef.local_path || mediaRef.path || ""),
        filename: String(mediaRef.filename || mediaRef.name || slot),
      });
    });
    return media;
  }

  function normalizeHistoryStableText(value) {
    return String(value || "")
      .trim()
      .replace(/\\/g, "/")
      .replace(/\?.*$/, "")
      .toLowerCase();
  }

  function historyStableMediaKey(item) {
    const media = normalizeHistoryMedia(item);
    const keys = [];
    media.forEach((m) => {
      const value = normalizeHistoryStableText(m.local_path || m.path || m.view_url || m.url || m.filename || m.name || "");
      if (value) keys.push(value);
    });
    return keys.sort().join("|");
  }

  function historyStableKey(item) {
    if (!item || typeof item !== "object") return "";
    const type = normalizeHistoryStableText(item.node_type || item.type || "");
    const sequence = normalizeHistoryStableText(item.sequence || sequenceFromRuntimeGroup(item) || "");
    const outputDir = normalizeHistoryStableText(item.output_dir || "");
    const mediaKey = historyStableMediaKey(item);
    const runId = normalizeHistoryStableText(item.run_id || item.cache_key || item.key || "");

    // 自动化/最近生成最容易重复：同一个输出目录 + 同一个序号 + 同一种节点，只保留最新一条。
    if (outputDir && sequence) return `out:${type}:${sequence}:${outputDir}`;

    // 视频或手动生成没有 output_dir 时，用媒体路径/URL 去重。
    if (mediaKey) return `media:${type}:${sequence}:${mediaKey}`;

    // 兜底再使用后端 run_id/key。
    if (runId) return `run:${runId}`;

    return `fallback:${type}:${sequence}:${normalizeHistoryStableText(item.created_at_ms || item.created_at || "")}`;
  }

  function historySortMs(item) {
    const raw = Number(item?.created_at_ms || item?.updated_at_ms || 0);
    return Number.isFinite(raw) ? raw : 0;
  }

  function dedupeUnifiedHistoryItems(items) {
    const rows = Array.isArray(items) ? items.filter((x) => x && typeof x === "object") : [];
    const sorted = rows.slice().sort((a, b) => historySortMs(b) - historySortMs(a));
    const seen = new Set();
    const out = [];
    sorted.forEach((item) => {
      const key = historyStableKey(item);
      if (key && seen.has(key)) return;
      if (key) seen.add(key);
      out.push(item);
    });
    return out;
  }

  function normalizeUnifiedHistoryItems(data) {
    if (Array.isArray(data?.items)) return dedupeUnifiedHistoryItems(data.items.slice().reverse());
    const groups = Array.isArray(data?.groups) ? data.groups.slice() : [];
    const videos = Array.isArray(data?.videos) ? data.videos.slice() : [];
    const items = [];
    groups.forEach((group) => {
      if (!group || typeof group !== "object") return;
      const media = runtimeGroupMediaItems(group);
      items.push({
        run_id: String(group.run_id || group.cache_key || ""),
        sequence: String(group.sequence || ""),
        node_type: String(group.node_type || (String(group.output_strategy || "").toLowerCase() === "single_image" ? "normal_single_image" : "normal_three_view")),
        type: "image",
        ok: group.has_error ? false : true,
        error: group.has_error ? "部分方案需要重跑" : "",
        created_at: group.created_at || (group.updated_at_ms ? new Date(Number(group.updated_at_ms)).toLocaleString() : ""),
        created_at_ms: Number(group.created_at_ms || group.updated_at_ms || 0),
        output_dir: String(group.output_dir || ""),
        model: String(group.model || ""),
        display_model: String(group.model || ""),
        input_image_count: Number(group.input_image_count || 0),
        uploaded_image_count: Number(group.uploaded_image_count || 0),
        source_images: Array.isArray(group.source_images) ? group.source_images : [],
        media,
        output_files: {},
        template_display: String(group.template_display || group.mode_display || ""),
      });
    });
    videos.forEach((video) => {
      if (!video || typeof video !== "object") return;
      const url = String(video.view_url || video.url || "").trim();
      items.push({
        run_id: String(video.run_id || video.key || ""),
        sequence: String(video.sequence || ""),
        node_type: "video",
        type: "video",
        ok: video.has_error ? false : true,
        error: String(video.error || ""),
        created_at: video.created_at || (video.updated_at_ms ? new Date(Number(video.updated_at_ms)).toLocaleString() : ""),
        created_at_ms: Number(video.created_at_ms || video.updated_at_ms || 0),
        output_dir: String(video.output_dir || ""),
        model: String(video.model || ""),
        display_model: String(video.model || ""),
        input_image_count: 0,
        uploaded_image_count: 0,
        source_images: [],
        media: [{
          slot: String(video.filename || "result.mp4"),
          kind: "video",
          view_url: url,
          url,
          path: String(video.local_path || ""),
          local_path: String(video.local_path || ""),
          filename: String(video.filename || "result.mp4"),
        }],
        output_files: {},
      });
    });
    items.sort((a, b) => Number(b.created_at_ms || 0) - Number(a.created_at_ms || 0));
    return dedupeUnifiedHistoryItems(items);
  }

  async function fetchAutomationHistory(announce = false) {
    try {
      const data = await getJson(AUTOMATION_HISTORY_ROUTE);
      const items = normalizeUnifiedHistoryItems(data);
      state.automation.historyItems = items;
      state.automation.historyLoadedAt = Date.now();
      state.history.items = items;
      state.history.loadedAt = Date.now();
      renderHistoryModal(items);
      if (announce) setLauncherState(`已读取统一生成历史：${items.length} 条`, "ok");
      return items;
    } catch (error) {
      console.warn("[Hrio Design] fetch history failed:", error);
      if (announce) setLauncherState(`历史读取失败：${error.message || error}`, "error");
      renderHistoryModal([], error);
      return [];
    }
  }

  async function clearAutomationHistory() {
    try {
      await postJson(AUTOMATION_HISTORY_CLEAR_ROUTE, {});
      state.automation.historyItems = [];
      state.history.items = [];
      state.automation.historyLoadedAt = Date.now();
      state.history.loadedAt = Date.now();
      renderHistoryModal([]);
      setLauncherState("统一结果 JSON 已清理", "ok");
    } catch (error) {
      console.warn("[Hrio Design] clear history failed:", error);
      setLauncherState(`历史清理失败：${error.message || error}`, "error");
    }
  }

  function createHistoryModal() {
    injectStyle();
    let modal = document.getElementById(HISTORY_MODAL_ID);
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = HISTORY_MODAL_ID;
    modal.innerHTML = `
      <div class="history-card">
        <div class="history-head">
          <div>
            <strong>Hrio Design｜全部生成历史</strong>
            <span>图片、最近生成、自动化生成统一读取同一个 JSON 缓存；历史单独弹窗查看。</span>
          </div>
          <div class="history-actions">
            <button class="history-btn" data-history-refresh type="button">刷新</button>
            <button class="history-btn" data-history-clear type="button">清理历史</button>
            <button class="history-close" data-history-close type="button">×</button>
          </div>
        </div>
        <div class="history-body" data-history-list>
          <div class="history-empty">正在读取生成历史...</div>
        </div>
      </div>
    `;

    const close = () => modal.classList.remove("show");
    modal.querySelector("[data-history-close]").onclick = close;
    modal.querySelector("[data-history-refresh]").onclick = () => refreshHistoryModal(true);
    modal.querySelector("[data-history-clear]").onclick = () => clearAutomationHistory();
    modal.addEventListener("click", (event) => {
      if (event.target === modal) close();
    });
    document.body.appendChild(modal);
    return modal;
  }

  function normalizeHistoryMedia(item) {
    const media = [];
    const seen = new Set();
    const pushMedia = (m) => {
      if (!m || typeof m !== "object") return;
      const key = normalizeHistoryStableText(m.local_path || m.path || m.view_url || m.url || m.source || m.filename || m.name || m.slot || "");
      if (key && seen.has(key)) return;
      if (key) seen.add(key);
      media.push(m);
    };

    if (Array.isArray(item?.media)) {
      item.media.forEach(pushMedia);
    }

    const files = item?.output_files && typeof item.output_files === "object" ? item.output_files : {};
    Object.entries(files).forEach(([slot, value]) => {
      if (!value) return;
      const key = normalizeHistoryStableText(value);
      if (key && seen.has(key)) return;
      const lower = String(value).toLowerCase();
      pushMedia({ slot, path: String(value), kind: lower.endsWith(".mp4") || lower.endsWith(".mov") || lower.endsWith(".webm") || lower.endsWith(".m4v") ? "video" : "image" });
    });
    return media;
  }

  function renderHistoryMedia(media) {
    const items = Array.isArray(media) ? media : [];
    if (!items.length) return `<div class="history-empty" style="padding:10px;">无可预览媒体</div>`;
    return `<div class="history-media">${items.slice(0, 8).map((m) => {
      const url = String(m.view_url || m.url || "").trim();
      const path = String(m.path || m.local_path || m.source || m.name || m.filename || "");
      const title = escapeHtml(`${m.slot || m.kind || "media"} · ${path}`);
      const isVideo = String(m.kind || "").toLowerCase() === "video" || /\.(mp4|mov|webm|m4v)(\?|$)/i.test(url || path);
      if (url && isVideo) return `<video class="history-thumb" src="${escapeHtml(url)}" title="${title}" controls preload="metadata"></video>`;
      if (url) return `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer"><img class="history-thumb" src="${escapeHtml(url)}" title="${title}" /></a>`;
      return `<div class="history-empty" style="width:160px;padding:8px;">${escapeHtml(m.slot || m.kind || "文件")}<div class="history-path">${escapeHtml(path)}</div></div>`;
    }).join("")}</div>`;
  }

  function historyNodeTypeLabel(type) {
    const raw = String(type || "");
    if (raw.includes("single_image")) return "普通单图";
    if (raw.includes("three_view")) return "三方案";
    if (raw.includes("video")) return "视频";
    return raw || "生成";
  }

  function buildAutomationPayloadFromHistoryItem(item) {
    const seq = String(item?.sequence || sequenceFromRuntimeGroup(item) || "001");
    const sourceImages = Array.isArray(item?.source_images) ? item.source_images.filter(Boolean).map(String) : [];
    if (!sourceImages.length && item?.rerun_payload && typeof item.rerun_payload === "object") {
      return Object.assign({}, item.rerun_payload, {
        enabled: true,
        created_at: Date.now(),
        run_sequences: [seq],
        target_sequences: [seq],
        sequences: [seq],
        run_sequence: seq,
        selected_sequence: seq,
        sequence: seq,
        group_concurrency: 1,
        run_mode: "single_group",
        run_view: "all",
      });
    }
    if (!sourceImages.length) throw new Error("这条记录没有 source_images，通常是手动生成结果，无法自动重跑；请直接在节点或设计师面板重新生成。");
    const previewGroup = {
      sequence: seq,
      output_dir: "",
      present_root_count: sourceImages.length,
      expected_root_count: sourceImages.length,
      preview_count: sourceImages.length,
      items: sourceImages.map((path, index) => ({
        root_index: index,
        root_path: "",
        source_type: "history_source_image",
        file_name: String(path).split(/[\\/]/).pop() || `image_${index + 1}.png`,
        image_path: path,
        sequence: seq,
      })),
    };
    return {
      enabled: true,
      type: "banana_sequence_group_automation",
      version: "8.2.2",
      created_at: Date.now(),
      input_roots: [],
      output_root: "",
      group_concurrency: 1,
      max_input_roots: 10,
      max_images_per_group: Math.min(10, Math.max(1, sourceImages.length)),
      extract_rule: "history_exact_source_images",
      collect_images_mode: "history_preview_group_exact",
      collect_mode: "history_preview_group_exact",
      save_images: true,
      save_video: String(item?.node_type || "").includes("video"),
      video_filename: "result.mp4",
      image_filenames: { front: "front.png", side: "side.png", back: "back.png", single: "single.png" },
      preview_groups: [previewGroup],
      run_sequences: [seq],
      target_sequences: [seq],
      sequences: [seq],
      run_sequence: seq,
      selected_sequence: seq,
      sequence: seq,
      run_mode: "single_group",
      run_view: "all",
      force_apply_token: `history:${seq}:${Date.now()}`,
    };
  }

  function rerunHistoryItem(index) {
    try {
      const item = state.history.items[Number(index)];
      if (!item) throw new Error("历史记录不存在或已刷新");
      const payload = buildAutomationPayloadFromHistoryItem(item);
      applyAutomationPayload(payload, true, { force: true, fromModal: true, fromHistory: true });
      const modal = document.getElementById(HISTORY_MODAL_ID);
      if (modal) modal.classList.remove("show");
      setLauncherState(`已从历史重跑序号 ${payload.sequence || ""}`.trim(), "syncing");
      queueGraphDebounced(2400);
    } catch (error) {
      setLauncherState(`历史重跑失败：${error.message || error}`, "error");
    }
  }

function renderHistoryModal(items, error = null) {
    const modal = document.getElementById(HISTORY_MODAL_ID);
    if (!modal) return;
    const list = modal.querySelector("[data-history-list]");
    if (!list) return;
    if (error) {
      list.innerHTML = `<div class="history-empty">读取历史失败：${escapeHtml(error.message || error)}</div>`;
      return;
    }
    const rows = dedupeUnifiedHistoryItems(Array.isArray(items) ? items : [])
      .filter((item) => Number(item.input_image_count || 0) > 0 || Number(item.uploaded_image_count || 0) > 0);
    if (!rows.length) {
      list.innerHTML = `<div class="history-empty">暂无生成历史。现在手动生成、最近生成、自动化生成都会写入同一个 JSON 缓存，并统一在这里查看。</div>`;
      return;
    }
    list.innerHTML = rows.slice(0, 160).map((item, index) => {
      const ok = item.ok !== false;
      const seq = escapeHtml(item.sequence || sequenceFromRuntimeGroup(item) || "-");
      const type = historyNodeTypeLabel(item.node_type || item.type || "");
      const when = escapeHtml(item.created_at || (item.created_at_ms ? new Date(Number(item.created_at_ms)).toLocaleString() : ""));
      const out = escapeHtml(item.output_dir || "");
      const model = escapeHtml(item.display_model || item.model || "");
      const media = normalizeHistoryMedia(item);
      const status = ok ? `<span class="history-status-ok">成功</span>` : `<span class="history-status-bad">失败：${escapeHtml(item.error || "未知错误")}</span>`;
      return `
        <div class="history-item">
          ${renderHistoryMedia(media)}
          <div class="history-main">
            <div class="history-title">序号 ${seq} · ${escapeHtml(type)} · ${status}</div>
            <div class="history-meta">${when}${model ? ` · ${model}` : ""}</div>
            <div class="history-meta">输入 ${escapeHtml(item.input_image_count || 0)} 张 · 上传 ${escapeHtml(item.uploaded_image_count || 0)} 张</div>
            <div class="history-path">${out}</div>
          </div>
          <div class="history-actions">
            <button class="history-btn" data-history-rerun="${index}" type="button">重跑本组</button>
          </div>
        </div>
      `;
    }).join("");
    list.querySelectorAll("[data-history-rerun]").forEach((btn) => {
      btn.onclick = () => rerunHistoryItem(btn.getAttribute("data-history-rerun"));
    });
  }

  async function refreshHistoryModal(announce = false) {
    const modal = createHistoryModal();
    const list = modal.querySelector("[data-history-list]");
    if (list) list.innerHTML = `<div class="history-empty">正在读取生成历史...</div>`;
    const items = await fetchAutomationHistory(announce);
    renderHistoryModal(items);
  }

  function openHistoryModal() {
    const modal = createHistoryModal();
    modal.classList.add("show");
    refreshHistoryModal(false);
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
      openVideoModal,
      openHistoryModal,
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
    if (window.__HRIO_DESIGN_BRIDGE_V822__) return;
    window.__HRIO_DESIGN_BRIDGE_V822__ = true;

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
