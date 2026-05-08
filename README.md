# Hrio Design

Hrio Design 是独立的 ComfyUI 自定义节点插件，面向平面设计与室内设计。

## 节点

- `Hrio_Design_Template_Node`：设计师模板面板
- `Hrio_Design_Three_View_Node`：三方案并发
- `Hrio_Design_Single_Image_Node`：单图生成
- `Hrio_Design_Single_Video_Node`：单视频生成
- `Hrio_Design_Video_Node`：视频生成

## 发布信息

- GitHub 仓库：`git@github.com:moki-flank/Hrio-Design.git`
- Comfy Registry 包名：`hrio-design`
- 版本：`8.1.4`

## 一键推送

Windows 双击或执行：

```bat
setup_git_and_push.bat
```

macOS/Linux 执行：

```bash
chmod +x setup_git_and_push.sh
./setup_git_and_push.sh
```

推送到 `main` 后，GitHub Actions 会使用仓库 Secret `REGISTRY_ACCESS_TOKEN` 自动发布到 Comfy Registry / ComfyUI-Manager。

## 本地安装

复制整个目录到：

```text
ComfyUI/custom_nodes/Hrio-Design/
```

然后重启 ComfyUI。
