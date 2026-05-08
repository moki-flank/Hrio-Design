# FILE: banana_triple_view_node.py
from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

import numpy as np
from PIL import Image

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)

try:
    from banana_node import (
        logger,
        _MANIFEST,
        _NODE,
        _cfg,
        _cfg_or_manifest,
        _enum_source_options,
        _enum_source_display,
        _manual_model_default,
        _manual_image_size_default,
        _manual_aspect_ratio_default,
        _upload_reference_images_for_node,
        _tensors_to_uploaded_urls,
        _pil_to_tensor,
        _cat_image_batches_safe,
        _run_three_view_jobs,
        _THREE_VIEW_SCOPE_OPTIONS,
        _runtime_results_payload,
        _clear_runtime_results,
        _error_img,
        _return_images_with_ui_preview,
        _HAS_PROMPT_SERVER,
        PromptServer,
        aiohttp_web,
    )
except Exception as e:
    raise RuntimeError(f"banana_triple_view_node.py 依赖 banana_node.py，请确认 banana_node.py 已正确安装: {e}") from e


PLUGIN_VERSION = "8.1.0"

EDITOR_ROUTE = "/hrio-design/editor"
MANIFEST_ROUTE = "/hrio-design/manifest"
CONFIG_ROUTE = "/hrio-design/config"
CONFIG_DEFAULTS_ROUTE = "/hrio-design/config/defaults"
RUNTIME_ROUTE = "/hrio-design/runtime"
RUNTIME_CLEAR_ROUTE = "/hrio-design/runtime/clear"
OLD_EDITOR_ROUTES = []  # 独立新插件不注册旧 /banana 路由，避免和 hrio-commerce 冲突
OLD_CONFIG_ROUTES = []
OLD_CONFIG_DEFAULTS_ROUTES = []
OLD_RUNTIME_ROUTES = []
OLD_RUNTIME_CLEAR_ROUTES = []
AUTOMATION_SELECT_FOLDER_ROUTE = "/hrio-design/automation/select-folder"
AUTOMATION_PREVIEW_ROUTE = "/hrio-design/automation/preview"
AUTOMATION_HISTORY_ROUTE = "/hrio-design/automation/history"
AUTOMATION_HISTORY_CLEAR_ROUTE = "/hrio-design/automation/history-clear"
AUTOMATION_HISTORY_FILE = "hrio_design_automation_history.json"
_AUTOMATION_HISTORY_LOCK = threading.Lock()
_AUTOMATION_HISTORY_MAX_ITEMS = 500

MODE_OPTIONS: Dict[str, str] = {"平面｜品牌主视觉 KV": "brand_key_visual", "平面｜活动海报 / 宣传海报": "poster_design", "平面｜社媒封面 / 小红书封面": "social_cover", "平面｜网页首屏 / Banner": "web_hero_banner", "平面｜PPT / 提案封面": "proposal_cover", "平面｜品牌视觉延展": "brand_extension", "室内｜空间风格概念图": "space_style_concept", "室内｜室内氛围渲染": "interior_mood_render", "室内｜材质情绪板": "material_moodboard", "室内｜软装搭配方案": "soft_furnishing_plan", "室内｜墙面 / 地面材质替换": "material_replacement", "室内｜灯光氛围调整": "lighting_mood"}

DELETED_MODE_KEYS = set()

FIELD_KEYS = [
    "image_roles",
    "global_prompt",
    "front_prompt",
    "side_prompt",
    "back_prompt",
    "variant_a_prompt",
    "variant_b_prompt",
    "variant_c_prompt",
    "consistency_prompt",
    "negative_prompt",
    "designer_type",
    "output_strategy",
    "creativity",
]

MODE_EXTRA_KEYS = [
    "preview_urls",
    "previewUrls",
]

PREVIEW_VIEW_KEYS = ["front", "side", "back", "variant_a", "variant_b", "variant_c"]
VARIANT_TO_LEGACY_VIEW = {"variant_a": "front", "variant_b": "side", "variant_c": "back"}
LEGACY_VIEW_TO_VARIANT = {"front": "variant_a", "side": "variant_b", "back": "variant_c"}

TOP_LEVEL_KEEP_KEYS = [
    "plugin_version",
    "version",
    "description",
    "updated_at",
    "preview_base_url",
    "preview_ext",
    "background_url",
    "mode_meta",
    "preview_urls",
    "previewUrls",
    "designer_type_options",
    "output_strategy_options",
    "creativity_options",
    "theme_skins",
    "global_negative_prompt",
]

ECOMMERCE_DEFAULTS: Dict[str, Any] = {
    "display_name": "🎨 Hrio｜设计师模板生成",
    "category": "HRIO设计/模板面板",
    "output_node": True,
    "default_prompt_template": "平面｜品牌主视觉 KV",
    "default_mode": "平面｜品牌主视觉 KV",
    "default_model": "banano2",
    "default_image_size": "4K",
    "default_aspect_ratio": "16:9 (横屏宽幅)",
    "prompt_store_path": "banana_designer_prompts.json",
    "editor_route": EDITOR_ROUTE,
    "editor_html": "web/banana_prompt_editor.html",
    "theme": "Hrio Design",
    "theme_en": "Graphic & Interior Design",
    "theme_accent": "#8fc7ff",
    "theme_deep": "#315d8f",
    "theme_bg": "linear-gradient(135deg, #eef7ff 0%, #f8fbff 48%, #fff7fb 100%)",
    "preview_base_url": "https://img.hrio.site/assets/plu",
    "preview_ext": "png",
    "mode_options": MODE_OPTIONS,
    "optional_image_slots": 10,
}

DESIGN_MODE_META: Dict[str, Dict[str, Any]] = {"brand_key_visual": {"title": "平面｜品牌主视觉 KV", "designer_type": "graphic_design", "icon": "品", "desc": "品牌素材、Logo、产品主体、核心视觉元素。适合品牌发布与商业提案。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "极简高级版", "file": "01_平面设计_品牌主视觉KV_01_极简高级版.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "视觉冲击版", "file": "01_平面设计_品牌主视觉KV_02_视觉冲击版.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "实验设计版", "file": "01_平面设计_品牌主视觉KV_03_实验设计版.png"}]}, "poster_design": {"title": "平面｜活动海报 / 宣传海报", "designer_type": "graphic_design", "icon": "海", "desc": "活动主题、宣传海报、营销视觉底图。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "商业稳定版", "file": "02_平面设计_活动海报宣传海报_01_商业稳定版.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "年轻传播版", "file": "02_平面设计_活动海报宣传海报_02_年轻传播版.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "艺术实验版", "file": "02_平面设计_活动海报宣传海报_03_艺术实验版.png"}]}, "social_cover": {"title": "平面｜社媒封面 / 小红书封面", "designer_type": "graphic_design", "icon": "媒", "desc": "社媒封面、小红书封面、短视频封面。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "高级干净版", "file": "03_平面设计_社媒封面小红书封面_01_高级干净版.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "强吸引版", "file": "03_平面设计_社媒封面小红书封面_02_强吸引版.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "氛围故事版", "file": "03_平面设计_社媒封面小红书封面_03_氛围故事版.png"}]}, "web_hero_banner": {"title": "平面｜网页首屏 / Banner", "designer_type": "graphic_design", "icon": "网", "desc": "网页首屏、Banner、产品官网背景。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "官网高级版", "file": "04_平面设计_网页首屏Banner_01_官网高级版.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "科技视觉版", "file": "04_平面设计_网页首屏Banner_02_科技视觉版.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "品牌氛围版", "file": "04_平面设计_网页首屏Banner_03_品牌氛围版.png"}]}, "proposal_cover": {"title": "平面｜PPT / 提案封面", "designer_type": "graphic_design", "icon": "提", "desc": "PPT 封面、商业提案、咨询公司汇报封面。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "商务咨询版", "file": "05_平面设计_PPT提案封面_01_商务咨询版.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "设计事务所版", "file": "05_平面设计_PPT提案封面_02_设计事务所版.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "创意提案版", "file": "05_平面设计_PPT提案封面_03_创意提案版.png"}]}, "brand_extension": {"title": "平面｜品牌视觉延展", "designer_type": "graphic_design", "icon": "延", "desc": "品牌主视觉延展、物料延展、同系统视觉资产。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "主视觉延展", "file": "06_平面设计_品牌视觉延展_01_主视觉延展.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "应用场景延展", "file": "06_平面设计_品牌视觉延展_02_应用场景延展.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "抽象系统延展", "file": "06_平面设计_品牌视觉延展_03_抽象系统延展.png"}]}, "space_style_concept": {"title": "室内｜空间风格概念图", "designer_type": "interior_design", "icon": "室", "desc": "空间风格、设计概念、室内提案方向。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "克制高级版", "file": "07_室内设计_空间风格概念图_01_克制高级版.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "温暖生活版", "file": "07_室内设计_空间风格概念图_02_温暖生活版.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "设计张力版", "file": "07_室内设计_空间风格概念图_03_设计张力版.png"}]}, "interior_mood_render": {"title": "室内｜室内氛围渲染", "designer_type": "interior_design", "icon": "氛", "desc": "室内氛围、自然光、样板间、居住情绪。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "白天自然光", "file": "08_室内设计_室内氛围渲染_01_白天自然光.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "傍晚暖光", "file": "08_室内设计_室内氛围渲染_02_傍晚暖光.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "高级静谧", "file": "08_室内设计_室内氛围渲染_03_高级静谧.png"}]}, "material_moodboard": {"title": "室内｜材质情绪板", "designer_type": "interior_design", "icon": "材", "desc": "石材、木材、织物、金属、软装材质系统。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "主材质板", "file": "09_室内设计_材质情绪板_01_主材质板.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "软装搭配板", "file": "09_室内设计_材质情绪板_02_软装搭配板.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "局部细节板", "file": "09_室内设计_材质情绪板_03_局部细节板.png"}]}, "soft_furnishing_plan": {"title": "室内｜软装搭配方案", "designer_type": "interior_design", "icon": "软", "desc": "家具、布艺、灯具、地毯、装饰画、摆件搭配。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "克制高级", "file": "10_室内设计_软装搭配方案_01_克制高级.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "温暖生活", "file": "10_室内设计_软装搭配方案_02_温暖生活.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "设计感强化", "file": "10_室内设计_软装搭配方案_03_设计感强化.png"}]}, "material_replacement": {"title": "室内｜墙面 / 地面材质替换", "designer_type": "interior_design", "icon": "替", "desc": "墙面、地面、石材、木饰面、微水泥材质替换。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "墙面材质替换", "file": "11_室内设计_墙面地面材质替换_01_墙面材质替换.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "地面材质替换", "file": "11_室内设计_墙面地面材质替换_02_地面材质替换.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "墙地整体协调", "file": "11_室内设计_墙面地面材质替换_03_墙地整体协调.png"}]}, "lighting_mood": {"title": "室内｜灯光氛围调整", "designer_type": "interior_design", "icon": "光", "desc": "自然光、间接光、重点照明、夜间高级氛围。", "variants": [{"key": "variant_a", "field": "variant_a_prompt", "label": "方案 A", "name": "白天自然光", "file": "12_室内设计_灯光氛围调整_01_白天自然光.png"}, {"key": "variant_b", "field": "variant_b_prompt", "label": "方案 B", "name": "傍晚暖光", "file": "12_室内设计_灯光氛围调整_02_傍晚暖光.png"}, {"key": "variant_c", "field": "variant_c_prompt", "label": "方案 C", "name": "夜间高级氛围", "file": "12_室内设计_灯光氛围调整_03_夜间高级氛围.png"}]}}

DEFAULT_MODES: Dict[str, Dict[str, Any]] = {"brand_key_visual": {"designer_type": "graphic_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：品牌主视觉 KV。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：极简高级版。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：视觉冲击版。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：实验设计版。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "poster_design": {"designer_type": "graphic_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：活动海报 / 宣传海报。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：商业稳定版。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：年轻传播版。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：艺术实验版。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "social_cover": {"designer_type": "graphic_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：社媒封面 / 小红书封面。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：高级干净版。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：强吸引版。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：氛围故事版。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "web_hero_banner": {"designer_type": "graphic_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：网页首屏 / Banner。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：官网高级版。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：科技视觉版。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：品牌氛围版。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "proposal_cover": {"designer_type": "graphic_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：PPT / 提案封面。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：商务咨询版。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：设计事务所版。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：创意提案版。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "brand_extension": {"designer_type": "graphic_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：品牌视觉延展。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：主视觉延展。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：应用场景延展。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：抽象系统延展。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "space_style_concept": {"designer_type": "interior_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：空间风格概念图。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：克制高级版。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：温暖生活版。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：设计张力版。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "interior_mood_render": {"designer_type": "interior_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：室内氛围渲染。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：白天自然光。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：傍晚暖光。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：高级静谧。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "material_moodboard": {"designer_type": "interior_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：材质情绪板。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：主材质板。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：软装搭配板。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：局部细节板。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "soft_furnishing_plan": {"designer_type": "interior_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：软装搭配方案。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：克制高级。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：温暖生活。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：设计感强化。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "material_replacement": {"designer_type": "interior_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：墙面 / 地面材质替换。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：墙面材质替换。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：地面材质替换。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：墙地整体协调。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}, "lighting_mood": {"designer_type": "interior_design", "preview_urls": {}, "image_roles": "Image 1 = 主体素材；Image 2 = 风格参考；Image 3 = 配色参考；Image 4 = 版式参考；Image 5 = 材质或纹理参考；Image 6 = 背景或场景参考。", "global_prompt": "任务：灯光氛围调整。请基于上传参考图生成高审美设计图，保持构图高级、层级清晰、材质自然、画面干净。不要直接生成文字，不要乱码，不要水印。", "variant_a_prompt": "方案 A：白天自然光。构图稳定、清晰、适合正式商业使用。", "variant_b_prompt": "方案 B：傍晚暖光。增强视觉吸引力、层次、空间与光影。", "variant_c_prompt": "方案 C：夜间高级氛围。更有设计张力，但仍保持高级可落地。", "consistency_prompt": "三张图必须保持同一设计系统、同一视觉气质、同一素材逻辑，只允许方案表达差异。", "negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲，不要畸形结构，不要杂乱拼贴，不要廉价滤镜。"}}

def _strip_deleted_modes(options: Dict[str, str]) -> Dict[str, str]:
    return {
        str(k): str(v)
        for k, v in (options or {}).items()
        if str(v) not in DELETED_MODE_KEYS
    }


def _ecommerce_manifest() -> Dict[str, Any]:
    raw = _MANIFEST.get("ecommerce_three_view", {}) or {}
    merged = copy.deepcopy(ECOMMERCE_DEFAULTS)

    if isinstance(raw, dict):
        for k, v in raw.items():
            if k == "mode_options" and isinstance(v, dict) and v:
                merged[k] = _strip_deleted_modes(v)
            else:
                merged[k] = v

    merged["display_name"] = "🎨 Hrio｜设计师模板生成"
    merged["category"] = "HRIO设计/模板面板"
    merged["editor_route"] = EDITOR_ROUTE
    merged["theme"] = "Hrio Design"
    merged["theme_en"] = "Graphic & Interior Design"
    merged["theme_accent"] = "#8fc7ff"
    merged["theme_deep"] = "#315d8f"
    merged["theme_bg"] = "linear-gradient(135deg, #eef7ff 0%, #f8fbff 48%, #fff7fb 100%)"

    merged["mode_options"] = _strip_deleted_modes(merged.get("mode_options") or MODE_OPTIONS)
    if not merged["mode_options"]:
        merged["mode_options"] = copy.deepcopy(MODE_OPTIONS)

    return merged


def _prompt_config_path() -> str:
    cfg = _ecommerce_manifest()
    filename = str(cfg.get("prompt_store_path") or "banana_ecommerce_prompts.json").strip()
    filename = filename.replace("\\", "/").split("/")[-1] or "banana_ecommerce_prompts.json"
    return os.path.join(MODULE_DIR, filename)


def _manifest_mode_options() -> Dict[str, str]:
    return _strip_deleted_modes(_ecommerce_manifest().get("mode_options") or MODE_OPTIONS)


def _mode_actual_from_display(value: Any, hidden_key: Any = "") -> str:
    hidden = str(hidden_key or "").strip()
    options = _manifest_mode_options()

    if hidden and hidden in set(options.values()) and hidden not in DELETED_MODE_KEYS:
        return hidden

    raw = str(value or "").strip()

    if raw in options:
        return options[raw]

    for _, actual in options.items():
        if raw == actual:
            return actual

    default_display = str(
        _ecommerce_manifest().get("default_prompt_template")
        or _ecommerce_manifest().get("default_mode")
        or "平面｜品牌主视觉 KV"
    )
    return options.get(default_display, "brand_key_visual")


def _mode_display_from_actual(actual_value: Any) -> str:
    actual = str(actual_value or "").strip()

    for display, value in _manifest_mode_options().items():
        if str(value).strip() == actual:
            return display

    return str(
        _ecommerce_manifest().get("default_prompt_template")
        or _ecommerce_manifest().get("default_mode")
        or "平面｜品牌主视觉 KV"
    )


def _field_dict_from_any(raw: Any, fallback_key: str) -> Dict[str, Any]:
    base = copy.deepcopy(DEFAULT_MODES.get(fallback_key, DEFAULT_MODES.get("brand_key_visual", next(iter(DEFAULT_MODES.values())))))

    if isinstance(raw, dict):
        for key in FIELD_KEYS:
            if isinstance(raw.get(key), str):
                base[key] = raw[key]

        for key in MODE_EXTRA_KEYS:
            value = raw.get(key)
            if isinstance(value, dict):
                base[key] = copy.deepcopy(value)

        if "previewUrls" in base and "preview_urls" not in base:
            base["preview_urls"] = copy.deepcopy(base.get("previewUrls") or {})

    elif isinstance(raw, str) and raw.strip():
        base["global_prompt"] = raw.strip()

    for key in FIELD_KEYS:
        base.setdefault(key, "")

    if not isinstance(base.get("preview_urls"), dict):
        base["preview_urls"] = {}

    return base


def _default_prompt_config() -> Dict[str, Any]:
    cfg = _ecommerce_manifest()
    modes: Dict[str, Dict[str, Any]] = {}

    for actual in set(list(_manifest_mode_options().values()) + list(DEFAULT_MODES.keys())):
        if actual in DELETED_MODE_KEYS:
            continue
        if actual in DEFAULT_MODES:
            item = copy.deepcopy(DEFAULT_MODES[actual])
            item.setdefault("preview_urls", {})
            modes[actual] = item

    return {
        "plugin_version": PLUGIN_VERSION,
        "version": 1,
        "description": "Hrio Design 设计师模板生成配置。mode/prompt_template 表示提示词模板；model 表示大模型，两者互不干扰。",
        "preview_base_url": cfg.get("preview_base_url", "https://img.hrio.site/assets/plu"),
        "preview_ext": cfg.get("preview_ext", "png"),
        "background_url": cfg.get("background_url", "https://img.hrio.site/assets/plu/bg.png"),
        "designer_type_options": {"平面设计": "graphic_design", "室内设计": "interior_design"},
        "output_strategy_options": {"单图生成": "single", "三方案并发": "three_variants", "主图 + 延展 + 细节": "main_extend_detail"},
        "creativity_options": {"保守": "safe", "平衡": "balanced", "大胆": "bold"},
        "theme_skins": {
            "冬之韵淡灰": {"key": "winter_gray", "background_url": "https://img.hrio.site/assets/plu/bg.png", "tone": "淡灰、冰蓝、冬之韵、建筑线稿、克制留白"},
            "暖砂淡黄": {"key": "warm_yellow", "background_url": "https://img.hrio.site/assets/plu/bg2.png", "tone": "淡黄、暖砂、石膏肌理、柔和室内、自然光感"},
        },
        "mode_options": _manifest_mode_options(),
        "mode_meta": copy.deepcopy(DESIGN_MODE_META),
        "preview_urls": {key: {"variant_a": "", "variant_b": "", "variant_c": ""} for key in modes.keys()},
        "modes": modes,
        "prompts": {},
        "global_negative_prompt": "不要真实文字，不要乱码字体，不要水印，不要二维码，不要价格，不要促销标签，不要购物按钮，不要低清晰度，不要明显 AI 扭曲。",
    }


def _read_prompt_config() -> Dict[str, Any]:
    path = _prompt_config_path()
    default_cfg = _default_prompt_config()

    if not os.path.exists(path):
        return default_cfg

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning(f"读取 {os.path.basename(path)} 失败，使用默认配置: {e}")
        return default_cfg

    if not isinstance(raw, dict):
        return default_cfg

    merged = copy.deepcopy(default_cfg)

    for key in TOP_LEVEL_KEEP_KEYS:
        if key not in raw:
            continue
        if key == "mode_meta" and isinstance(raw.get(key), dict):
            merged.setdefault("mode_meta", {})
            merged["mode_meta"].update(copy.deepcopy(raw[key]))
        elif key == "theme_skins" and isinstance(raw.get(key), dict):
            merged.setdefault("theme_skins", {})
            merged["theme_skins"].update(copy.deepcopy(raw[key]))
        elif key in {"preview_urls", "previewUrls"}:
            # preview_urls 在后面统一合并到 modes，避免覆盖掉默认 12 个模板。
            continue
        else:
            merged[key] = copy.deepcopy(raw[key])

    raw_options = raw.get("mode_options")
    if isinstance(raw_options, dict) and raw_options:
        merged_options = copy.deepcopy(_manifest_mode_options() or MODE_OPTIONS)
        for display, actual in raw_options.items():
            actual = str(actual or "").strip()
            display = str(display or actual).strip()
            if actual and display and actual not in DELETED_MODE_KEYS:
                merged_options[display] = actual
        merged["mode_options"] = _strip_deleted_modes(merged_options)

    raw_modes = raw.get("modes")
    if isinstance(raw_modes, dict):
        for actual, fields in raw_modes.items():
            actual = str(actual)
            if actual in DELETED_MODE_KEYS:
                continue
            merged["modes"][actual] = _field_dict_from_any(fields, actual)

    old_prompts = raw.get("prompts")
    if isinstance(old_prompts, dict):
        merged["prompts"] = old_prompts

    top_preview_urls = raw.get("preview_urls") or raw.get("previewUrls")
    if isinstance(top_preview_urls, dict):
        merged["preview_urls"] = copy.deepcopy(top_preview_urls)

        for mode_key, urls in top_preview_urls.items():
            if not isinstance(urls, dict):
                continue

            mode_key = str(mode_key)
            if mode_key in DELETED_MODE_KEYS:
                continue

            if mode_key not in merged["modes"]:
                merged["modes"][mode_key] = _field_dict_from_any({}, mode_key)

            if not isinstance(merged["modes"][mode_key].get("preview_urls"), dict):
                merged["modes"][mode_key]["preview_urls"] = {}

            for view in PREVIEW_VIEW_KEYS:
                if urls.get(view):
                    merged["modes"][mode_key]["preview_urls"][view] = urls.get(view)
            for legacy, variant in LEGACY_VIEW_TO_VARIANT.items():
                if urls.get(legacy) and not merged["modes"][mode_key]["preview_urls"].get(variant):
                    merged["modes"][mode_key]["preview_urls"][variant] = urls.get(legacy)
                if urls.get(variant) and not merged["modes"][mode_key]["preview_urls"].get(legacy):
                    merged["modes"][mode_key]["preview_urls"][legacy] = urls.get(variant)

    return merged


def _save_prompt_config(data: Any) -> Dict[str, Any]:
    current = _read_prompt_config()

    if not isinstance(data, dict):
        raise RuntimeError("保存失败：请求体必须是 JSON 对象")

    saved = copy.deepcopy(current)

    for key in [
        "description",
        "preview_base_url",
        "preview_ext",
        "background_url",
        "mode_meta",
        "preview_urls",
        "previewUrls",
    ]:
        if key in data:
            save_key = "preview_urls" if key == "previewUrls" else key
            if save_key == "mode_meta" and isinstance(data.get(key), dict):
                saved.setdefault("mode_meta", {})
                saved["mode_meta"].update(copy.deepcopy(data[key]))
            else:
                saved[save_key] = copy.deepcopy(data[key])

    if isinstance(data.get("mode_options"), dict):
        merged_options = copy.deepcopy(_manifest_mode_options() or MODE_OPTIONS)
        for display, actual in data["mode_options"].items():
            actual = str(actual or "").strip()
            display = str(display or actual).strip()
            if actual and display and actual not in DELETED_MODE_KEYS:
                merged_options[display] = actual
        saved["mode_options"] = _strip_deleted_modes(merged_options)

    if isinstance(data.get("modes"), dict):
        for actual, fields in data["modes"].items():
            actual = str(actual)
            if actual in DELETED_MODE_KEYS:
                continue

            saved.setdefault("modes", {})[actual] = _field_dict_from_any(fields, actual)

    if isinstance(saved.get("preview_urls"), dict):
        for mode_key, urls in saved["preview_urls"].items():
            if not isinstance(urls, dict):
                continue

            mode_key = str(mode_key)
            if mode_key in DELETED_MODE_KEYS:
                continue

            saved.setdefault("modes", {})
            if mode_key not in saved["modes"]:
                saved["modes"][mode_key] = _field_dict_from_any({}, mode_key)

            saved["modes"][mode_key].setdefault("preview_urls", {})

            for view in PREVIEW_VIEW_KEYS:
                if urls.get(view):
                    saved["modes"][mode_key]["preview_urls"][view] = urls.get(view)
            for legacy, variant in LEGACY_VIEW_TO_VARIANT.items():
                if urls.get(legacy) and not saved["modes"][mode_key]["preview_urls"].get(variant):
                    saved["modes"][mode_key]["preview_urls"][variant] = urls.get(legacy)
                if urls.get(variant) and not saved["modes"][mode_key]["preview_urls"].get(legacy):
                    saved["modes"][mode_key]["preview_urls"][legacy] = urls.get(variant)

    preview_urls = {}
    for mode_key, fields in (saved.get("modes") or {}).items():
        if not isinstance(fields, dict):
            continue

        urls = fields.get("preview_urls")
        if isinstance(urls, dict):
            preview_urls[mode_key] = {
                "variant_a": urls.get("variant_a") or urls.get("front", ""),
                "variant_b": urls.get("variant_b") or urls.get("side", ""),
                "variant_c": urls.get("variant_c") or urls.get("back", ""),
                "front": urls.get("front") or urls.get("variant_a", ""),
                "side": urls.get("side") or urls.get("variant_b", ""),
                "back": urls.get("back") or urls.get("variant_c", ""),
            }

    saved["preview_urls"] = preview_urls

    saved["plugin_version"] = PLUGIN_VERSION
    saved["version"] = int(saved.get("version") or 0) + 1

    path = _prompt_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)

    logger.success(f"Hrio Design 设计师模板生成提示词模板配置已保存: {path}")
    return saved


def _mode_fields(mode_actual: str) -> Dict[str, Any]:
    cfg = _read_prompt_config()
    modes = cfg.get("modes") or {}
    fields = modes.get(mode_actual)

    if not isinstance(fields, dict):
        fields = DEFAULT_MODES.get(mode_actual, DEFAULT_MODES.get("brand_key_visual", next(iter(DEFAULT_MODES.values()))))

    return _field_dict_from_any(fields, mode_actual)


def _compose_prompt(mode_actual: str, view_key: str) -> str:
    fields = _mode_fields(mode_actual)

    view_field = {
        "front": "variant_a_prompt",
        "side": "variant_b_prompt",
        "back": "variant_c_prompt",
        "variant_a": "variant_a_prompt",
        "variant_b": "variant_b_prompt",
        "variant_c": "variant_c_prompt",
    }.get(view_key, "variant_a_prompt")

    legacy_fallback = {
        "variant_a_prompt": "front_prompt",
        "variant_b_prompt": "side_prompt",
        "variant_c_prompt": "back_prompt",
    }.get(view_field, "front_prompt")

    view_prompt = fields.get(view_field) or fields.get(legacy_fallback) or ""

    mode_display = _mode_display_from_actual(mode_actual)
    variant_label = {
        "variant_a_prompt": "方案 A",
        "variant_b_prompt": "方案 B",
        "variant_c_prompt": "方案 C",
    }.get(view_field, "方案 A")

    parts = [
        f"模板类型：{mode_display}",
        f"输出方案：{variant_label}",
        f"参考图角色：{fields.get('image_roles', '')}",
        f"全局任务：{fields.get('global_prompt', '')}",
        f"方案任务：{view_prompt}",
        f"一致性要求：{fields.get('consistency_prompt', '')}",
        f"负面约束：{fields.get('negative_prompt', '')}",
        "输出要求：只输出单张高质量设计图，不要拼图，不要三联图，不要九宫格，不要文字标注，不要水印。构图高级、层级清晰、光影干净、结构准确。",
    ]

    return "\n\n".join([p for p in parts if str(p or "").strip()])


# -----------------------------------------------------------------------------
# 自动化：后端扫描输入根目录 -> 按子文件夹数字序号横向聚合 -> 并发执行不同序号组。
# -----------------------------------------------------------------------------

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _safe_int_local(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        out = int(float(str(value).strip()))
    except Exception:
        out = int(default)
    if min_value is not None:
        out = max(int(min_value), out)
    if max_value is not None:
        out = min(int(max_value), out)
    return out


def _safe_bool_local(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _extract_sequence(folder_name: str) -> str:
    parts = re.findall(r"\d+", str(folder_name or ""))
    return "".join(parts) if parts else ""


def _clean_path_list(values: Any, max_count: int = 10) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    seen = set()
    for item in values:
        path = str(item or "").strip().strip('"')
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
        if len(out) >= max_count:
            break
    return out


def _clean_sequence_list(values: Any, max_count: int = 9999) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    out: List[str] = []
    seen = set()
    for item in values:
        raw = str(item or "").strip().strip('"')
        if not raw:
            continue
        seq = _extract_sequence(raw) or raw
        if not seq or seq in seen:
            continue
        seen.add(seq)
        out.append(seq)
        if len(out) >= max_count:
            break
    return out


def _scan_input_root(root: str) -> List[Dict[str, Any]]:
    """
    只支持「根目录直放图片模式」。

    输入示例：
        input_root_01/001.png
        input_root_01/002.png
        input_root_02/001.png
        input_root_02/002.png

    扫描规则：
    - 只扫描 input_root 下的直接图片文件；
    - 不扫描 001_截图/ 这类子文件夹；
    - 从图片文件名中贪婪提取所有数字并拼接作为序号；
    - 相同序号会在多个 input_root 之间横向聚合。
    """
    items: List[Dict[str, Any]] = []
    root = str(root or "").strip()
    if not root or not os.path.isdir(root):
        return items

    try:
        names = sorted(os.listdir(root))
    except Exception:
        return items

    for name in names:
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue

        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTS:
            continue

        stem = os.path.splitext(name)[0]
        seq = _extract_sequence(stem)
        if not seq:
            continue

        items.append({
            "source_type": "root_image",
            "file_name": name,
            "image_path": full,
            "sequence": seq,
        })

    return items


def _sequence_sort_key(seq: str):
    text = str(seq or "")
    try:
        return (0, int(text), len(text), text)
    except Exception:
        return (1, 0, len(text), text)


def _build_sequence_groups(input_roots: List[str], output_root: str = "", require_all_roots_present: bool = False) -> List[Dict[str, Any]]:
    """
    只按根目录图片文件名分组。

    每个 input_root 是一个输入槽位；执行时每个序号组最多从 10 个 input_root 中各取一张同序号图片，
    例如 001 组会收集：
        input_root_01/001.png
        input_root_02/001.png
        ...
        input_root_10/001.png
    """
    group_map: Dict[str, List[Dict[str, Any]]] = {}
    root_count = len(input_roots)

    for root_index, root in enumerate(input_roots):
        for item in _scan_input_root(root):
            seq = item["sequence"]
            group_map.setdefault(seq, []).append({
                "root_index": root_index,
                "root_path": root,
                "source_type": "root_image",
                "file_name": item["file_name"],
                "image_path": item["image_path"],
                "sequence": seq,
            })

    groups: List[Dict[str, Any]] = []
    for seq in sorted(group_map.keys(), key=_sequence_sort_key):
        items = sorted(group_map[seq], key=lambda x: int(x.get("root_index") or 0))
        present_roots = {int(x.get("root_index") or 0) for x in items}
        if require_all_roots_present and len(present_roots) < root_count:
            continue
        run_dir = os.path.join(str(output_root or ""), f"output_{seq}", "run_01") if output_root else ""
        groups.append({
            "sequence": seq,
            "items": items,
            "output_dir": run_dir,
            "present_root_count": len(present_roots),
            "expected_root_count": root_count,
        })
    return groups


def _collect_images_for_group(items: List[Dict[str, Any]], max_count: int = 10) -> List[str]:
    """收集某个序号组里的直接图片路径，按 input_root 顺序排列。"""
    paths: List[str] = []
    for item in sorted(items or [], key=lambda x: int(x.get("root_index") or 0)):
        image_path = str(item.get("image_path") or "")
        if not image_path or not os.path.isfile(image_path):
            continue
        ext = os.path.splitext(image_path)[1].lower()
        if ext in IMAGE_EXTS:
            paths.append(image_path)
            if len(paths) >= max_count:
                return paths
    return paths[:max_count]

def _automation_payload_from_string(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _automation_enabled(raw: Any) -> bool:
    data = _automation_payload_from_string(raw)
    return bool(data) and _safe_bool_local(data.get("enabled"), False)


def _normalize_automation_payload(raw: Any) -> Dict[str, Any]:
    data = _automation_payload_from_string(raw)
    input_roots = _clean_path_list(data.get("input_roots") or data.get("inputFolders") or data.get("input_folders"), 10)
    output_root = str(data.get("output_root") or data.get("outputRoot") or "").strip()
    group_concurrency = _safe_int_local(data.get("group_concurrency", data.get("groupConcurrency", 3)), 3, 1, 10)
    max_images_per_group = _safe_int_local(data.get("max_images_per_group", data.get("maxImagesPerGroup", 10)), 10, 1, 10)
    require_all = _safe_bool_local(data.get("require_all_roots_present"), False)
    run_sequences = _clean_sequence_list(
        data.get("run_sequences")
        or data.get("target_sequences")
        or data.get("sequences")
        or data.get("run_sequence")
        or data.get("runSequence")
        or data.get("selected_sequence")
        or data.get("sequence")
    )
    run_view = str(data.get("run_view") or data.get("view") or "").strip()
    run_mode = str(data.get("run_mode") or data.get("action") or "").strip()

    return {
        "enabled": _safe_bool_local(data.get("enabled"), False),
        "version": str(data.get("version") or "7.10.0"),
        "input_roots": input_roots,
        "output_root": output_root,
        "group_concurrency": group_concurrency,
        "max_input_roots": 10,
        "max_images_per_group": max_images_per_group,
        "extract_rule": "greedy_digits_join_all",
        "collect_images_mode": "root_images_group_by_filename_sequence",
        "collect_mode": "root_images_group_by_filename_sequence",
        "require_all_roots_present": require_all,
        "save_images": _safe_bool_local(data.get("save_images"), True),
        "save_video": _safe_bool_local(data.get("save_video"), False),
        "run_sequences": run_sequences,
        "run_view": run_view,
        "run_mode": run_mode,
        "video_filename": str(data.get("video_filename") or "result.mp4"),
        "image_filenames": data.get("image_filenames") if isinstance(data.get("image_filenames"), dict) else {
            "front": "front.png",
            "side": "side.png",
            "back": "back.png",
        },
    }


def _automation_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _normalize_automation_payload(payload)
    input_roots = cfg["input_roots"]
    output_root = cfg["output_root"]
    groups = _build_sequence_groups(
        input_roots,
        output_root=output_root,
        require_all_roots_present=bool(cfg.get("require_all_roots_present")),
    )

    return {
        "ok": True,
        "input_roots": input_roots,
        "output_root": output_root,
        "group_count": len(groups),
        "groups": groups,
    }


def _select_folder_with_tkinter() -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(title="选择 Hrio Design 自动化文件夹")
    finally:
        root.destroy()
    return str(path or "").strip()


def _load_image_tensors_from_paths(paths: List[str]) -> List[Any]:
    tensors: List[Any] = []
    for path in paths:
        img = Image.open(path).convert("RGB")
        tensors.append(_pil_to_tensor(img))
    return tensors


def _save_tensor_image(tensor: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    t = tensor.detach().cpu()
    if t.ndim == 4:
        t = t[0]
    arr = (t.clamp(0, 1).numpy() * 255).astype(np.uint8)
    Image.fromarray(arr).save(path)


def _write_text_file(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(text or ""))


def _automation_history_path() -> str:
    return os.path.join(MODULE_DIR, AUTOMATION_HISTORY_FILE)


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _read_automation_history() -> Dict[str, Any]:
    path = _automation_history_path()
    if not os.path.exists(path):
        return {
            "ok": True,
            "version": PLUGIN_VERSION,
            "updated_at_ms": 0,
            "count": 0,
            "items": [],
        }

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {
            "ok": True,
            "version": PLUGIN_VERSION,
            "updated_at_ms": 0,
            "count": 0,
            "items": [],
        }

    if not isinstance(data, dict):
        data = {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    data["ok"] = True
    data["version"] = str(data.get("version") or PLUGIN_VERSION)
    data["updated_at_ms"] = int(data.get("updated_at_ms") or 0)
    data["count"] = len(items)
    data["items"] = items[-_AUTOMATION_HISTORY_MAX_ITEMS:]
    return data


def _clear_automation_history() -> Dict[str, Any]:
    payload = {
        "ok": True,
        "version": PLUGIN_VERSION,
        "updated_at_ms": _utc_now_ms(),
        "count": 0,
        "items": [],
    }
    with _AUTOMATION_HISTORY_LOCK:
        with open(_automation_history_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def _history_existing_files(output_dir: str) -> Dict[str, str]:
    output_dir = str(output_dir or "")
    names = ["front.png", "side.png", "back.png", "result.mp4", "run_info.json", "error.txt"]
    out: Dict[str, str] = {}
    for name in names:
        path = os.path.join(output_dir, name) if output_dir else ""
        if path and os.path.exists(path):
            out[name] = path
    return out


def _append_automation_history_record(record: Dict[str, Any]) -> None:
    if not isinstance(record, dict):
        return

    item = copy.deepcopy(record)
    for key in ("front", "side", "back", "batch", "tensor", "image"):
        item.pop(key, None)

    output_dir = str(item.get("output_dir") or "")
    item.setdefault("output_files", _history_existing_files(output_dir))
    item.setdefault("created_at_ms", _utc_now_ms())
    item.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    item.setdefault("plugin_version", PLUGIN_VERSION)

    with _AUTOMATION_HISTORY_LOCK:
        data = _read_automation_history()
        items = data.get("items") if isinstance(data.get("items"), list) else []
        items.append(item)
        items = items[-_AUTOMATION_HISTORY_MAX_ITEMS:]
        payload = {
            "ok": True,
            "version": PLUGIN_VERSION,
            "updated_at_ms": _utc_now_ms(),
            "count": len(items),
            "items": items,
        }
        with open(_automation_history_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


def _run_automation_one_group(
    *,
    group: Dict[str, Any],
    cfg: Dict[str, Any],
    api_key: str,
    model: str,
    image_size: str,
    aspect_ratio: str,
    prompts: Dict[str, str],
    labels: str,
    cache_key: str,
    auto_retry_until_success: bool,
    max_retry_per_view: int,
    retry_interval_sec: float,
    generate_scope: str = "全部并发生成",
) -> Dict[str, Any]:
    seq = str(group.get("sequence") or "")
    run_dir = str(group.get("output_dir") or os.path.join(cfg["output_root"], f"output_{seq}", "run_01"))
    os.makedirs(run_dir, exist_ok=True)

    try:
        image_paths = _collect_images_for_group(group.get("items") or [], int(cfg.get("max_images_per_group") or 10))
        if not image_paths:
            raise RuntimeError(f"序号 {seq} 没有找到可用图片")

        tensors = _load_image_tensors_from_paths(image_paths)
        upload_dir = _cfg_or_manifest("upload_dir", "uploads/images")
        image_urls = _tensors_to_uploaded_urls(tensors, api_key, upload_dir)

        result = _run_three_view_jobs(
            api_key=api_key,
            model=model,
            image_size=image_size,
            aspect_ratio=aspect_ratio,
            image_urls=image_urls,
            prompts=prompts,
            labels_prefix=f"{labels}-自动化{seq}-" if labels else f"自动化{seq}-",
            generate_scope=generate_scope,
            cache_key=f"{cache_key}:{seq}",
            auto_retry_until_success=auto_retry_until_success,
            max_retry_per_view=max_retry_per_view,
            retry_interval_sec=retry_interval_sec,
        )

        image_names = cfg.get("image_filenames") or {}
        if bool(cfg.get("save_images", True)):
            _save_tensor_image(result["front"], os.path.join(run_dir, str(image_names.get("front") or "front.png")))
            _save_tensor_image(result["side"], os.path.join(run_dir, str(image_names.get("side") or "side.png")))
            _save_tensor_image(result["back"], os.path.join(run_dir, str(image_names.get("back") or "back.png")))

        meta = {
            "sequence": seq,
            "ok": True,
            "node_type": "image_template",
            "output_dir": run_dir,
            "input_image_count": len(image_paths),
            "uploaded_image_count": len(image_urls),
            "source_images": image_paths,
            "errors_by_key": result.get("errors_by_key") or {},
            "generate_scope": result.get("generate_scope") or generate_scope,
            "model": model,
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
            "labels": labels,
        }
        _write_text_file(os.path.join(run_dir, "run_info.json"), json.dumps(meta, ensure_ascii=False, indent=2))
        _append_automation_history_record(meta)
        return {
            **meta,
            "front": result.get("front"),
            "side": result.get("side"),
            "back": result.get("back"),
            "batch": result.get("batch"),
        }

    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        _write_text_file(os.path.join(run_dir, "error.txt"), err)
        logger.error(f"自动化序号 {seq} 失败: {e}")
        fail_meta = {
            "sequence": seq,
            "ok": False,
            "node_type": "image_template",
            "output_dir": run_dir,
            "error": str(e),
            "model": model,
            "image_size": image_size,
            "aspect_ratio": aspect_ratio,
            "labels": labels,
            "generate_scope": generate_scope,
        }
        _append_automation_history_record(fail_meta)
        return fail_meta

def _register_ecommerce_routes() -> None:
    if not _HAS_PROMPT_SERVER or PromptServer is None or aiohttp_web is None:
        return

    routes = PromptServer.instance.routes

    def _json_response(payload: Any, status: int = 200):
        return aiohttp_web.json_response(
            payload,
            status=status,
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    def _route_exists(method: str, path: str) -> bool:
        method = str(method or "GET").upper()
        path = str(path or "").strip()
        try:
            resources = list(routes.resources())
        except Exception:
            resources = []

        for resource in resources:
            canonical = str(getattr(resource, "canonical", "") or "")
            if canonical != path:
                continue
            try:
                resource_routes = list(resource)
            except Exception:
                resource_routes = []
            for route in resource_routes:
                route_method = str(getattr(route, "method", "") or "").upper()
                if route_method == method or route_method == "*":
                    return True
                # aiohttp 给 GET 自动注册 HEAD；HEAD 存在时也说明这个 path 已经占用过。
                if method == "GET" and route_method in {"GET", "HEAD"}:
                    return True
        return False

    def _safe_add_route(method: str, path: str, handler) -> None:
        method = str(method or "GET").upper()
        path = str(path or "").strip()
        if not path:
            return
        if _route_exists(method, path):
            logger.info(f"Hrio Design 路由已存在，跳过重复注册: {method} {path}")
            return
        try:
            decorator = getattr(routes, method.lower())
            decorator(path)(handler)
            logger.success(f"Hrio Design 路由已注册: {method} {path}")
        except Exception as e:
            msg = str(e)
            if "already registered" in msg or "will never be executed" in msg or "Duplicate" in msg:
                logger.info(f"Hrio Design 路由重复，已跳过: {method} {path}")
                return
            logger.warning(f"Hrio Design 路由注册失败: {method} {path} | {e}")

    async def _banana_ecommerce_manifest_get(request):
        payload = {
            "ok": True,
            "plugin_version": PLUGIN_VERSION,
            "editor_route": EDITOR_ROUTE,
            "editor_alias_routes": [],
            "designer_template": _ecommerce_manifest(),
            "ecommerce_three_view": _ecommerce_manifest(),
            "mode_options": _manifest_mode_options(),
            "prompt_config_path": os.path.basename(_prompt_config_path()),
        }
        return _json_response(payload)

    async def _banana_ecommerce_prompt_config_get(request):
        return _json_response(_read_prompt_config())

    async def _banana_ecommerce_prompt_config_post(request):
        try:
            data = await request.json()
            saved = _save_prompt_config(data)
            return _json_response(
                {
                    "ok": True,
                    "config": saved,
                    "prompt_config": saved,
                }
            )
        except Exception as e:
            return _json_response(
                {
                    "ok": False,
                    "error": str(e),
                },
                status=500,
            )

    async def _banana_ecommerce_prompt_config_defaults(request):
        return _json_response(_default_prompt_config())

    async def _banana_triple_view_editor(request):
        cfg = _ecommerce_manifest()
        rel = str(cfg.get("editor_html") or "web/banana_prompt_editor.html").strip()
        rel = rel.replace("\\", "/").lstrip("/")
        html_path = os.path.join(MODULE_DIR, rel)

        if not os.path.exists(html_path):
            return aiohttp_web.Response(
                status=404,
                text=f"找不到前端面板文件: {html_path}",
                content_type="text/plain",
                headers={"Cache-Control": "no-store"},
            )

        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        return aiohttp_web.Response(
            text=html,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def _banana_ecommerce_runtime_results_get(request):
        payload = _runtime_results_payload()
        if isinstance(payload, dict):
            payload["editor_route"] = EDITOR_ROUTE
        return _json_response(payload)

    async def _banana_ecommerce_runtime_clear_post(request):
        return _json_response(_clear_runtime_results())

    async def _banana_automation_select_folder_post(request):
        try:
            path = _select_folder_with_tkinter()
            return _json_response({"ok": bool(path), "path": path})
        except Exception as e:
            return _json_response({"ok": False, "error": str(e)}, status=500)

    async def _banana_automation_preview_post(request):
        try:
            data = await request.json()
            return _json_response(_automation_preview(data))
        except Exception as e:
            return _json_response({"ok": False, "error": str(e)}, status=500)

    async def _banana_automation_history_get(request):
        try:
            return _json_response(_read_automation_history())
        except Exception as e:
            return _json_response({"ok": False, "error": str(e)}, status=500)

    async def _banana_automation_history_clear_post(request):
        try:
            return _json_response(_clear_automation_history())
        except Exception as e:
            return _json_response({"ok": False, "error": str(e)}, status=500)

    _safe_add_route("GET", MANIFEST_ROUTE, _banana_ecommerce_manifest_get)
    for config_path in [CONFIG_ROUTE, *OLD_CONFIG_ROUTES]:
        _safe_add_route("GET", config_path, _banana_ecommerce_prompt_config_get)
        _safe_add_route("POST", config_path, _banana_ecommerce_prompt_config_post)
    for defaults_path in [CONFIG_DEFAULTS_ROUTE, *OLD_CONFIG_DEFAULTS_ROUTES]:
        _safe_add_route("GET", defaults_path, _banana_ecommerce_prompt_config_defaults)

    # 主面板路由 + 老面板路由兜底。这样旧 JS 缓存或旧按钮也能打开设计师面板。
    for editor_path in [EDITOR_ROUTE, *OLD_EDITOR_ROUTES]:
        _safe_add_route("GET", editor_path, _banana_triple_view_editor)

    for runtime_path in [RUNTIME_ROUTE, *OLD_RUNTIME_ROUTES]:
        _safe_add_route("GET", runtime_path, _banana_ecommerce_runtime_results_get)
    for runtime_clear_path in [RUNTIME_CLEAR_ROUTE, *OLD_RUNTIME_CLEAR_ROUTES]:
        _safe_add_route("POST", runtime_clear_path, _banana_ecommerce_runtime_clear_post)
    _safe_add_route("POST", AUTOMATION_SELECT_FOLDER_ROUTE, _banana_automation_select_folder_post)
    _safe_add_route("POST", AUTOMATION_PREVIEW_ROUTE, _banana_automation_preview_post)
    _safe_add_route("GET", AUTOMATION_HISTORY_ROUTE, _banana_automation_history_get)
    _safe_add_route("POST", AUTOMATION_HISTORY_CLEAR_ROUTE, _banana_automation_history_clear_post)

    logger.success(f"Hrio Design 设计师面板路由检查完成，主路由: {EDITOR_ROUTE}")


class BananaPanelThreeViewNode:
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("variant_a_image", "variant_b_image", "variant_c_image", "images", "info", "mp4url")
    FUNCTION = "generate"
    OUTPUT_NODE = True
    CATEGORY = "HRIO设计/模板面板"

    @classmethod
    def INPUT_TYPES(cls):
        cfg = _ecommerce_manifest()

        mode_options = list(_manifest_mode_options().keys())
        if not mode_options:
            mode_options = list(MODE_OPTIONS.keys())

        model_options = _enum_source_options("model_map", ["banano2", "banano-pro", "gemini3.1-pro"])
        image_size_options = _enum_source_options("image_size_options", ["1K", "2K", "4K", "8K（默认16:9）"])
        aspect_options = _enum_source_options(
            "aspect_ratio_options",
            ["Auto", "1:1 (方形)", "3:4 (竖屏标准)", "9:16 (竖屏/手机)", "16:9 (横屏宽幅)"],
        )

        default_mode = str(
            cfg.get("default_prompt_template")
            or cfg.get("default_mode")
            or "平面｜品牌主视觉 KV"
        )
        if default_mode not in mode_options:
            default_mode = mode_options[0]

        default_model = _enum_source_display(
            "model_map",
            cfg.get("default_model") or _manual_model_default(),
            "banano2",
        )
        if default_model not in model_options:
            default_model = model_options[0]

        default_size = _enum_source_display(
            "image_size_options",
            cfg.get("default_image_size") or _manual_image_size_default(),
            "4K",
        )
        if default_size not in image_size_options:
            default_size = "4K" if "4K" in image_size_options else image_size_options[0]

        default_ratio = _enum_source_display(
            "aspect_ratio_options",
            cfg.get("default_aspect_ratio") or _manual_aspect_ratio_default("16:9"),
            "16:9 (横屏宽幅)",
        )
        if default_ratio not in aspect_options:
            default_ratio = "16:9 (横屏宽幅)" if "16:9 (横屏宽幅)" in aspect_options else aspect_options[0]

        required = {
            "api_key": (
                "STRING",
                {
                    "default": _cfg("api_key", ""),
                    "multiline": False,
                    "tooltip": "填入 API Key；留空时尝试读取 config.ini 的 api_key",
                },
            ),
            "mode": (
                mode_options,
                {
                    "default": default_mode,
                    "tooltip": "提示词模板。注意：这里不是大模型 model，前端同步只会改这个字段，不会修改 model。",
                },
            ),
            "model": (
                model_options,
                {
                    "default": default_model,
                    "tooltip": "大模型 model。提示词模板同步不会修改这个字段。",
                },
            ),
            "image_size": (
                image_size_options,
                {
                    "default": default_size,
                    "tooltip": "三张图使用同一尺寸。",
                },
            ),
            "aspect_ratio": (
                aspect_options,
                {
                    "default": default_ratio,
                    "tooltip": "三张图使用同一宽高比。",
                },
            ),
            "generate_scope": (
                _THREE_VIEW_SCOPE_OPTIONS,
                {
                    "default": "全部并发生成",
                    "tooltip": "质量不满意时可只重新生成某一个视图；其他视图会使用本节点上一次成功缓存结果。",
                },
            ),
            "auto_retry_until_success": (
                "BOOLEAN",
                {
                    "default": True,
                    "tooltip": "开启后，单个视图失败或不出图会自动重试，直到成功或达到最大重试次数。",
                },
            ),
            "max_retry_per_view": (
                "INT",
                {
                    "default": 8,
                    "min": 1,
                    "max": 999,
                    "step": 1,
                    "tooltip": "每个视图最多自动重试次数。建议 5-12；填太大会导致节点运行很久。",
                },
            ),
            "retry_interval_sec": (
                "FLOAT",
                {
                    "default": 1.5,
                    "min": 0.1,
                    "max": 30.0,
                    "step": 0.1,
                    "tooltip": "单路失败后的重试间隔秒数。",
                },
            ),
        }

        optional = {
            "mode_actual": (
                "STRING",
                {
                    "default": "",
                    "multiline": False,
                    "tooltip": "前端同步用的模板内部 key；通常留空。",
                },
            ),
            "cache_key": (
                "STRING",
                {
                    "default": "",
                    "multiline": False,
                    "tooltip": "可选缓存 key；留空则按当前节点 ID 和模板隔离。",
                },
            ),
            "labels_prefix": (
                "STRING",
                {
                    "default": "",
                    "multiline": False,
                    "tooltip": "可选输出标题前缀；留空自动使用模板名。",
                },
            ),
            "automation_payload": (
                "STRING",
                {
                    "default": "",
                    "multiline": True,
                    "tooltip": "自动化文件夹映射 JSON。由右下角自动化面板写入；不影响普通单次生成。",
                },
            ),
        }

        slot_count = int(cfg.get("optional_image_slots") or _NODE.get("optional_image_slots", 10) or 10)
        for i in range(1, slot_count + 1):
            optional[f"image_{i}"] = (
                "IMAGE",
                {
                    "tooltip": f"参考图 {i}；同一批上传图会复用到正面/侧面/背面三个并发请求",
                },
            )

        return {
            "required": required,
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    def generate(
        self,
        api_key: str,
        mode: str,
        model: str,
        image_size: str,
        aspect_ratio: str,
        generate_scope: str = "全部并发生成",
        auto_retry_until_success: bool = True,
        max_retry_per_view: int = 8,
        retry_interval_sec: float = 1.5,
        mode_actual: str = "",
        cache_key: str = "",
        labels_prefix: str = "",
        automation_payload: str = "",
        unique_id=None,
        **kwargs,
    ):
        start = time.time()
        resolved_key = str(api_key or "").strip() or _cfg("api_key", "")

        if not resolved_key:
            msg = "请在节点中填入 API Key"
            logger.error(msg)
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")

        template_actual = _mode_actual_from_display(mode, mode_actual)
        template_display = _mode_display_from_actual(template_actual)

        if template_actual in DELETED_MODE_KEYS:
            msg = f"提示词模板 {template_actual} 已删除，请重新选择模板"
            logger.error(msg)
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")

        if _automation_enabled(automation_payload):
            return self.generate_automation(
                resolved_key=resolved_key,
                mode=mode,
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                auto_retry_until_success=auto_retry_until_success,
                max_retry_per_view=max_retry_per_view,
                retry_interval_sec=retry_interval_sec,
                generate_scope=generate_scope,
                mode_actual=mode_actual,
                cache_key=cache_key,
                labels_prefix=labels_prefix,
                automation_payload=automation_payload,
                unique_id=unique_id,
            )

        automation_info = ""
        if str(automation_payload or "").strip():
            try:
                automation_data = json.loads(str(automation_payload))
                groups = automation_data.get("preview_groups") or automation_data.get("groups") or []
                automation_info = f"automation_payload: 已填写但 enabled=false；预览组数={len(groups)}"
            except Exception:
                automation_info = "automation_payload: 已填写，但不是有效 JSON"

        try:
            image_urls = _upload_reference_images_for_node(kwargs, resolved_key)
        except Exception as e:
            msg = f"参考图上传失败: {e}"
            logger.error(msg)
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")

        prompts = {
            "front": _compose_prompt(template_actual, "front"),
            "side": _compose_prompt(template_actual, "side"),
            "back": _compose_prompt(template_actual, "back"),
        }

        labels = str(labels_prefix or template_display or template_actual).strip()
        run_cache_key = str(cache_key or "").strip() or f"hrio_design_generation:{unique_id}:{template_actual}"

        logger.info(
            f"Hrio Design 设计师模板生成开始: mode={template_display}/{template_actual}, model={model}, "
            f"size={image_size}, ratio={aspect_ratio}, scope={generate_scope}, ref_image_count={len(image_urls)}"
        )

        try:
            result = _run_three_view_jobs(
                api_key=resolved_key,
                model=model,
                image_size=image_size,
                aspect_ratio=aspect_ratio,
                image_urls=image_urls,
                prompts=prompts,
                labels_prefix=f"{labels}-" if labels else "",
                generate_scope=generate_scope,
                cache_key=run_cache_key,
                auto_retry_until_success=auto_retry_until_success,
                max_retry_per_view=max_retry_per_view,
                retry_interval_sec=retry_interval_sec,
            )
        except Exception as e:
            msg = str(e)[:2500]
            logger.error(f"Hrio Design 设计师模板生成失败: {msg}")
            img = _error_img("Hrio Design 设计师模板生成失败")
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")

        elapsed = time.time() - start
        ordered = result["ordered"]

        lines = [
            f"✅ Hrio Design 设计师模板生成完成，耗时 {elapsed:.1f}s",
            f"theme: Hrio Design / Graphic & Interior Design",
            f"mode: {template_display} ({template_actual})",
            f"model: {model}",
            f"image_size: {image_size}",
            f"aspect_ratio: {aspect_ratio}",
            f"generate_scope: {result.get('generate_scope')}",
            f"auto_retry_until_success: {result.get('auto_retry_until_success')}",
            f"max_retry_per_view: {result.get('max_retry_per_view')}",
            f"retry_interval_sec: {result.get('retry_interval_sec')}",
            f"cache_key: {result.get('cache_key')}",
            f"ref_image_count: {len(image_urls)}",
            "prompt_source: frontend_panel_config",
            f"prompt_config: {os.path.basename(_prompt_config_path())}",
            f"editor: {EDITOR_ROUTE}",
            "字段隔离: mode=提示词模板；model=大模型；前端同步不会覆盖 model",
            "输出接口: variant_a_image=方案A, variant_b_image=方案B, variant_c_image=方案C, images=三张批量合集",
            "输出顺序: images[0]=方案A, images[1]=方案B, images[2]=方案C",
        ]

        if automation_info:
            lines.append(automation_info)

        for idx, item in enumerate(ordered, start=1):
            lines.append(
                f"{idx}. {item.get('label', '')} | 耗时 {float(item.get('elapsed') or 0):.1f}s | seed={item.get('seed', '')} | "
                f"size={item.get('image_size', '')} | ratio={item.get('aspect_ratio', '')}"
            )
            if str(item.get("info") or "").strip():
                lines.append(str(item["info"]))

        summary = "\n".join(lines)

        logger.summary("Hrio Design 设计师模板生成完成", {
            "输出": "正面/侧面/背面 + batch",
            "耗时": f"{elapsed:.1f}s",
            "主题": "Hrio Design",
            "模板": f"{template_display}/{template_actual}",
            "大模型model": model,
            "尺寸": image_size,
            "宽高比": aspect_ratio,
            "生成范围": result.get("generate_scope"),
            "缓存Key": result.get("cache_key"),
            "失败视图": ",".join((result.get("errors_by_key") or {}).keys()) or "无",
            "ref_image_count": len(image_urls),
        })

        return _return_images_with_ui_preview((
            result["front"],
            result["side"],
            result["back"],
            result["batch"],
            summary,
            "",
        ), label="banana_panel_three_view")


    def generate_automation(
        self,
        *,
        resolved_key: str,
        mode: str,
        model: str,
        image_size: str,
        aspect_ratio: str,
        auto_retry_until_success: bool,
        max_retry_per_view: int,
        retry_interval_sec: float,
        generate_scope: str = "全部并发生成",
        mode_actual: str = "",
        cache_key: str = "",
        labels_prefix: str = "",
        automation_payload: str = "",
        unique_id=None,
    ):
        start = time.time()
        cfg = _normalize_automation_payload(automation_payload)

        template_actual = _mode_actual_from_display(mode, mode_actual)
        template_display = _mode_display_from_actual(template_actual)
        labels = str(labels_prefix or template_display or template_actual).strip()
        run_cache_key = str(cache_key or "").strip() or f"hrio_design_automation:{unique_id}:{template_actual}"

        if not cfg.get("input_roots"):
            msg = "自动化已启用，但没有 input_roots。请在自动化面板选择输入根目录。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")
        if not cfg.get("output_root"):
            msg = "自动化已启用，但没有 output_root。请在自动化面板选择输出根目录。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")

        groups = _build_sequence_groups(
            cfg["input_roots"],
            output_root=cfg["output_root"],
            require_all_roots_present=bool(cfg.get("require_all_roots_present")),
        )
        all_group_count = len(groups)
        run_sequences = set(str(x) for x in (cfg.get("run_sequences") or []) if str(x).strip())
        if run_sequences:
            groups = [g for g in groups if str(g.get("sequence") or "") in run_sequences]
        if not groups:
            if run_sequences:
                msg = f"自动化没有找到指定序号组：{', '.join(sorted(run_sequences))}。请先在自动化面板预览分组，确认序号存在。"
            else:
                msg = "自动化没有扫描到任何有效序号组。请确认每个输入根目录下直接放置带数字序号的图片，例如 001.png、002.png。"
            img = _error_img(msg)
            return _return_images_with_ui_preview((img, img, img, img, msg, ""), label="banana_panel_error")

        prompts = {
            "front": _compose_prompt(template_actual, "front"),
            "side": _compose_prompt(template_actual, "side"),
            "back": _compose_prompt(template_actual, "back"),
        }

        group_concurrency = int(cfg.get("group_concurrency") or 3)
        logger.info(
            f"Hrio Design 自动化开始: groups={len(groups)}, concurrency={group_concurrency}, "
            f"mode={template_display}/{template_actual}, model={model}, output_root={cfg['output_root']}"
        )

        results: List[Dict[str, Any]] = []
        futures = []
        with ThreadPoolExecutor(max_workers=max(1, min(10, group_concurrency))) as executor:
            for group in groups:
                futures.append(executor.submit(
                    _run_automation_one_group,
                    group=group,
                    cfg=cfg,
                    api_key=resolved_key,
                    model=model,
                    image_size=image_size,
                    aspect_ratio=aspect_ratio,
                    prompts=prompts,
                    labels=labels,
                    cache_key=run_cache_key,
                    auto_retry_until_success=auto_retry_until_success,
                    max_retry_per_view=max_retry_per_view,
                    retry_interval_sec=retry_interval_sec,
                    generate_scope=generate_scope,
                ))

            for future in as_completed(futures):
                results.append(future.result())

        results.sort(key=lambda x: _sequence_sort_key(str(x.get("sequence") or "")))
        ok_results = [r for r in results if r.get("ok")]
        fail_results = [r for r in results if not r.get("ok")]
        elapsed = time.time() - start

        representative = ok_results[-1] if ok_results else None
        if representative:
            front = representative.get("front")
            side = representative.get("side")
            back = representative.get("back")
            batch = representative.get("batch")
            if batch is None:
                batch = _cat_image_batches_safe([front, side, back])
        else:
            err_text = "自动化全部失败"
            front = side = back = batch = _error_img(err_text)

        lines = [
            f"✅ Hrio Design 自动化批处理完成，耗时 {elapsed:.1f}s",
            f"mode: {template_display} ({template_actual})",
            f"model: {model}",
            f"image_size: {image_size}",
            f"aspect_ratio: {aspect_ratio}",
            f"input_roots: {len(cfg['input_roots'])}",
            f"groups: {len(groups)} / all_groups: {all_group_count}",
            f"run_sequences: {', '.join(sorted(run_sequences)) if run_sequences else '全部'}",
            f"generate_scope: {generate_scope}",
            f"success: {len(ok_results)}",
            f"failed: {len(fail_results)}",
            f"group_concurrency: {group_concurrency}",
            f"max_images_per_group: {cfg.get('max_images_per_group')}",
            f"output_root: {cfg['output_root']}",
            "输入规则: 只扫描输入根目录下的直接图片文件，例如 input_root_01/001.png；输出目录规则: output_序号/run_01/，图片文件 front.png / side.png / back.png",
        ]

        if cfg.get("save_video"):
            lines.append("提示: 当前图像自动化节点本身不产生视频；视频已拆分为独立【🎨 Hrio Design｜视频生成】节点。")

        for r in results:
            if r.get("ok"):
                lines.append(f"✅ {r.get('sequence')} -> {r.get('output_dir')} | 输入图片 {r.get('input_image_count')} 张")
            else:
                lines.append(f"❌ {r.get('sequence')} -> {r.get('output_dir')} | {r.get('error')}")

        summary = "\n".join(lines)
        logger.summary("Hrio Design 自动化批处理完成", {
            "总组数": len(groups),
            "成功": len(ok_results),
            "失败": len(fail_results),
            "耗时": f"{elapsed:.1f}s",
            "并发": group_concurrency,
            "输出根目录": cfg["output_root"],
        })

        return _return_images_with_ui_preview((front, side, back, batch, summary, ""), label="banana_panel_automation")


_register_ecommerce_routes()

NODE_CLASS_MAPPINGS = {
    "BananaPanelThreeViewNode": BananaPanelThreeViewNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BananaPanelThreeViewNode": "🎨 Hrio Design｜设计师模板面板",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "BananaPanelThreeViewNode",
    "_ecommerce_manifest",
    "_manifest_mode_options",
    "_read_prompt_config",
    "_save_prompt_config",
    "_default_prompt_config",
]
