# Hrio-Design v8.1.0 独立上架发布说明

这是从原 Hrio-Commerce 分支出来的设计师模板版插件。

## 新版内容

- 插件更名：`Hrio-Design`
- 面板更名：`Hrio Design 设计师模板生成`
- 新模板方向：平面设计、室内设计
- 面板路由：`/hrio-design/editor`
- 配置路由：`/hrio-design/config`
- 配置文件：`banana_designer_prompts.json`
- 保留普通单图、普通生视频、三方案并发节点

## 发布到 ComfyUI Manager / Comfy Registry

1. 把本包内容覆盖到你的新 GitHub 仓库，例如 `Hrio-Design`。
2. 确认 GitHub Secrets 中存在 `REGISTRY_ACCESS_TOKEN`。
3. 提交并推送：

```bash
git add .
git commit -m "release v8.1.0 Hrio Design"
git push origin main
```

如需再次发布新版，只改 `pyproject.toml` 的 `version`，并同步 `__init__.py`、`banana_manifest.json`、`banana_update.py` 里的版本号。
