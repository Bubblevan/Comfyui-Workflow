# 本地运行时

这里保留本机可直接运行的 Python 和依赖环境，用于让 `MinimaxH3` 不依赖仓库外的 ComfyUI Python 环境。

- Windows 启动：运行 `scripts/start_comfyui.ps1`
- Linux/WSL 启动：运行 `scripts/start_comfyui.sh`
- Harness CLI：运行 `runtime/python/python.exe scripts/h3.py validate`
- Harness tests：运行 `runtime/python/python.exe -m pytest`
- 运行时目录不提交到 Git，迁移仓库时需要整体复制。

Harness 依赖清单见仓库根目录的 `requirements-harness.txt`。模型路径唯一来自
`configs/extra_model_paths.yaml`。
