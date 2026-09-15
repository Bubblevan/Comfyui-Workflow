# 本地运行时

这里保留本机可直接运行的 Python 和依赖环境，用于让 `MinimaxH3` 不依赖仓库外的 ComfyUI Python 环境。

- Windows 启动：运行 `scripts/start_comfyui.ps1`
- Linux/WSL 启动：运行 `scripts/start_comfyui.sh`
- Harness CLI：运行 `runtime/python/python.exe scripts/h3.py validate`
- Harness tests：运行 `runtime/python/python.exe -m pytest`
- 运行时目录不提交到 Git，迁移仓库时需要整体复制。

## SageAttention / Windows

当前本机 ComfyUI 环境已验证：Torch `2.10.0+cu130`、Python `3.13.11`、RTX 4090
Laptop GPU。`runtime/venv` 已安装 `sageattention 2.2.0+cu130torch2.10.0andhigher.post6`
和 `triton-windows 3.7.1.post27`，`ComfyUI/custom_nodes/ComfyUI-KJNodes` 已安装并注册
MiniMax H3 的 Sage 节点。

启动脚本会自动把 Triton 自带的 Windows C 编译器和 CUDA 运行时路径注入当前进程，避免
系统里的其他 CUDA / GCC 抢先被 Triton 使用，并把 `TRITON_CACHE_DIR` 固定到仓库内的
`temp/triton-cache`，避免 Windows 用户目录缓存的权限问题。需要让 ComfyUI 的全局 attention 走 Sage 时：

```powershell
.\scripts\start_comfyui.ps1 -UseSageAttention
```

不加这个开关时，canonical H3 graph 使用主干默认的 Comfy Kitchen attention + TeaCache、H3 sigma
shift 以及 `euler`/`simple` 采样组合；需要精确回归时，在 shot 的 `runtime.approximation.method`
中显式写 `none`。这个开关只影响没有显式选择 model backend 的全局 ComfyUI 路径。shot 的
`runtime.attention.backend: sage` 仍可按单个 H3 流程显式插入参考
workflow 使用的两个 KJ patch 节点。Sage 与 H3 的 memory-efficient patch 都是实验性路径，
正式批量生成前应使用固定 seed 做一次质量和稳定性 A/B。

Harness 依赖清单见仓库根目录的 `requirements-harness.txt`。模型路径唯一来自
`configs/extra_model_paths.yaml`。

keep/0.75 MP/8 steps 的完整 E2E 消融结算见 [`../benchmarks/README.md`](../benchmarks/README.md)。
本机实际 GPU 是 RTX 4090 Laptop GPU；SageAttention `auto` 已通过完整视频测试，explicit
CUDA 后端虽可运行但更慢，因此主干仍以 Comfy Kitchen 为精确质量标准。
