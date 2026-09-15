# H3 runtime ablation

测试固定为 `shots/nun/shot01_idle.yaml`、seed `424242`、`explore`（0.5 MP、Turbo、4 steps），只切换 attention backend。计时是从向 ComfyUI `/prompt` 提交到视频输出完成，包含真实队列和执行路径。

在当前 Windows Ada/SM89 测试机（Torch `2.10.0+cu130`，识别名为 RTX 4090 Laptop GPU）上，连续 warm run 的结果为：

| backend | warm run | 相对 PyTorch |
| --- | ---: | ---: |
| Comfy Kitchen（主干默认） | 4.032 s | 33.40% faster |
| SageAttention | 4.106 / 4.071 s（均值 4.088 s） | 32.47% faster |
| PyTorch attention | 6.054 s | baseline |

首次切换 backend 会触发模型重新准备/编译，记录为 Kitchen `88.921 s`、Sage `90.522 s`、PyTorch `138.870 s`；它们不是 steady-state 吞吐。完整原始报告：[`h3-runtime-ablation-20260916-031055.json`](h3-runtime-ablation-20260916-031055.json) 和 [`h3-runtime-ablation-20260916-031031.json`](h3-runtime-ablation-20260916-031031.json)。

结论：Sage 在这台 Ada/SM89 环境能正常执行，并显著快于纯 PyTorch；但它没有超过主干 Kitchen，因此主干默认保持 Kitchen，Sage 作为可追溯的单 shot 消融后端。实际 4090D 仍应按同一命令复测一次。
