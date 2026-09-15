# H3 runtime ablation

面向社区的完整方法论、假说分析和未来计划见 [`docs/experiments/h3-runtime-acceleration-keep-ablation-20260916.md`](../docs/experiments/h3-runtime-acceleration-keep-ablation-20260916.md)。

## 结算口径

本轮以 `shots/nun/shot01_idle.yaml` 的 `keep` profile 为准：5 秒输出、0.75 MP、Turbo、8 steps、seed `424243`，实际视频为 1184×672、24 fps、5.167 秒。计时从向 ComfyUI `/prompt` 提交开始，到包含 VAE、音频和 MP4 输出在内的 `/history` 完成为止；不是单次模型 forward，也不是首帧时间。

当前仓库默认 production path 是 Kitchen + TeaCache；表中的 exact baseline 特意显式关闭 TeaCache，
用于质量回归和速度比较。

机器实际识别为 NVIDIA GeForce RTX 4090 Laptop GPU（Ada/SM89，16 GB）；因此结果可作为 4090D 类 Ada 卡的参考，但不能冒充物理 4090D 实测。

| variant | 状态 | E2E 秒 | 相对冷基线 303.640s | 说明 |
| --- | --- | ---: | ---: | --- |
| exact baseline / Kitchen (TeaCache off) | completed | **303.090** | 0.18% faster | 精确回归基线，约 5m03s |
| SageAttention `auto` | completed | **292.167** | **3.78% faster** | 可用，但未超过 Kitchen |
| SageAttention explicit CUDA | completed | **314.408** | 3.55% slower | 修复 Triton cache 权限后可运行，但更慢 |
| SageAttention `allow_compile` | completed | **320.432** | 5.53% slower | 可运行，但 compile 首跑和本次 E2E 均更慢 |
| TeaCache | completed | **228.076** | **24.89% faster** | 独立冷进程；当前速度优先候选，近似轨迹 |
| Spectrum | completed | **251.688** | **17.11% faster** | 独立冷进程；可运行，近似偏差高于 TeaCache |
| AGSoft Balanced cache | completed | **300.722** | 0.96% faster | 测量噪声范围，无实际收益 |
| FastPath | failed | 64.465 | — | `aimdo memory compile error` |
| Speed Cache | failed | 98.792 | — | `FinalLayer.forward()` 缺少 `sigma/sample_sigmas/shifts` 参数 |

主干 baseline 另有一次全新进程测得 303.640s；与 303.090s 的差异为 0.18%，说明 keep 基线稳定。TeaCache/Spectrum 的最终数字也取各自独立冷进程；此前同一进程切换后得到的 193.906s/200.133s 不纳入结算。之前的 4–6 秒数据属于 explore 的 0.5 MP/4 steps warm/切换后测量，不能代表 5 秒 keep 视频，本报告不再将其与本表混用。

## 结论与标准

* 精确质量标准：保持 Kitchen + `euler` + `simple` + H3 shift `12/3`，作为回归和质量基准。
* 速度标准：若接受近似加速，首选 TeaCache（约 3m48s）；Spectrum 作为第二候选（约 4m12s）。两者都必须用固定 seed 做人工 A/B，不能声称无损。
* SageAttention 已完成 Windows 适配；本机 SM89 上 `auto` 会选择 SageAttention2++ 的 FP8 CUDA 路径，只比 Kitchen 快约 11 秒，explicit FP16 CUDA 和 `allow_compile` 反而慢，因此不替换 Kitchen 默认。
* AGSoft、FastPath、Speed Cache 不进入默认生产 graph。尤其 Speed Cache 是进程级 patch，且当前 H3 `FinalLayer` ABI 不兼容；不要与 TeaCache/Spectrum 串联。

## 可复现命令

```powershell
# 每次只跑一个 variant，并在下一项前退出/重启 ComfyUI
python scripts/benchmark_h3_runtime.py shots/nun/shot01_idle.yaml `
  --api-url http://127.0.0.1:8198 --profile keep --seed 424243 `
  --variants teacache
```

结果 JSON 会记录 variant、runtime、sampler、scheduler、节点类型、E2E 秒数和失败原因。
逐 variant 独立启动时，应分别指定不同端口，或在下一项前完整退出 ComfyUI。

原始完成视频和 JSON 报告保留在本机 `output/video/` 与 `benchmarks/`；视频属于消融证据，不能直接晋级训练集，仍需经过 `h3.py extract/qc` 和人工审核。
