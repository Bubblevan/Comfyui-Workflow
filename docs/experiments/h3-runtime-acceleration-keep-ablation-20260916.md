# MiniMax H3 Ref2VA 在 Windows Ada 环境中的端到端加速消融

## 从一个看起来“快得不对”的数字开始

这轮实验最初的问题不是“哪个 attention kernel 更快”，而是一个更基础的计时口径问题。

之前的记录里出现过 4 秒左右、甚至 6 秒以内的数字。把它们放在“生成一个 5 秒视频”的语境里，
这个结果显然值得怀疑：它可能是单次 forward、首帧、warm run，或者是较低分辨率和较少 steps 的探索
流程，而不是用户真正关心的 keep 流程。

这次我把问题重新定义为一个可复现的端到端实验：固定同一个 shot、同一个 seed、同一套参考图和
同一个 ComfyUI API graph，只改变 attention 或 diffusion approximation 的实现；计时从向
ComfyUI 的 `/prompt` 提交开始，到 `/history` 报告完成且 MP4 已经写入为止。这样测到的不是模型
某一层的理论吞吐，而是一次真实生成任务交付给用户所需的墙钟时间。

结论先放在这里：在当前这台机器上，原版 keep 流程约为 303.64 秒，即 5 分 04 秒左右。TeaCache
在独立冷进程中把时间降到 228.076 秒，约快 24.89%，是本轮速度优先方案。Spectrum 需要
251.688 秒，约快 17.11%。SageAttention `auto` 可以正常工作，但只有约 3.78% 的收益；显式
FP16 CUDA 版本和 `allow_compile` 版本反而更慢。FastPath 与 Speed Cache 没有完成视频生成，
分别卡在 Windows aimdo 内存图编译和 H3 `FinalLayer` 参数接口上。

因此，仓库的默认主干现在切换为 Kitchen + TeaCache；需要严格复现原版数值轨迹时，必须显式写
`runtime.approximation.method: none`。这里的“默认”是工程决策，不等于“无损”：TeaCache 是
用预测结果跳过部分 diffusion forward 的近似方法，质量验收仍然需要固定 seed 的人工 A/B。

## 摘要

本文记录 MiniMax H3 Ref2VA 生产 harness 在 Windows Ada/SM89 环境上的一次运行时加速实验。实验
使用 `shots/nun/shot01_idle.yaml` 的 keep profile：0.75 MP、Turbo、8 steps、5 秒视频、seed
`424243`。实际编码结果为 1184×672、24 fps、5.167 秒、124 帧，并包含视频和音频封装。

实验比较了 Comfy Kitchen、SageAttention 多种后端、TeaCache、Spectrum、AGSoft cache、FastPath
和 Speed Cache。所有端到端数字均以完整输出为准，优先使用独立冷进程；对于同一进程容易留下全局
monkey-patch 的 Speed Cache，单独做隔离失败复测。结果显示，attention 优化和 diffusion 近似
优化解决的是两个不同层面的问题：前者只减少每个有效 denoising step 中 attention 的成本，后者
减少需要完整执行的 step 数。对于只有 8 steps 的 keep 视频，后者的收益更明显。

本轮没有把单次实验包装成统计学结论。每个候选只测了一次完整视频，精确基线测了两次，且实际
硬件是 RTX 4090 Laptop GPU，而不是用户口中的物理 RTX 4090D。因此本文的数字适合作为当前仓库
和当前机器的工程基准，不应被解释为不同显卡、不同 shot 或不同模型量化版本的普适 benchmark。

## 1. 实验问题与假设

### 1.1 问题定义

本轮要回答四个问题：

1. 原版 keep（0.75 MP、8 steps）到底需要多久，之前的 4–6 秒数据是什么；
2. SageAttention 是否真的比当前 Comfy Kitchen 主干更快；
3. TeaCache、Spectrum、AGSoft、FastPath、Speed Cache 这些社区方案，在 H3 Ref2VA 的真实
   graph 上是否可用、是否有端到端收益；
4. 在“速度、稳定性、可解释性、质量风险”同时存在时，默认主干应该选哪个方案。

### 1.2 事前假设

实验前可以提出一些合理但不应直接当成结论的假设。

第一，SageAttention 使用量化的 QK/PV kernel，理论上会降低 attention 的显存访问和计算成本，
所以它有机会比纯 PyTorch attention 快；但当前主干已经使用 Comfy Kitchen，Sage 不一定能再带来
同样幅度的收益。

第二，TeaCache 和 Spectrum 不主要优化单个 attention，而是根据相邻时间步的 hidden state 或
模型输出变化，预测当前 step 的结果，在满足阈值时跳过完整模型计算。它们应该比单纯换 attention
更容易获得大收益，但代价是轨迹不再与精确 baseline 完全相同。

第三，AGSoft 这类旧 cache 节点能否加速，取决于它是否能识别 H3 当前的时序和音视频条件。节点
能够插入 graph，并不意味着它一定在这个 shot 上触发足够多的 reuse。

第四，FastPath 和 Speed Cache 的社区 README 或 showcase 中的加速数字不能直接外推到当前仓库。
它们可能依赖特定 ComfyUI commit、特定模型 forward 签名、关闭某些内存管理功能，或使用了与本项目
不同的分辨率和 steps。最可靠的判断仍然是把它们接入同一 graph 后做完整生成。

## 2. 固定实验对象

### 2.1 Shot 和输出规格

所有 keep 结果使用同一个文件：

`shots/nun/shot01_idle.yaml`

该 shot 的关键参数如下：

| 项目 | 固定值 |
| --- | --- |
| 参考模式 | `free` |
| 输出时长 | 5 秒 |
| keep 分辨率预算 | 0.75 MP |
| steps | 8 |
| Turbo | true |
| takes | 1 |
| sampler | `euler` |
| scheduler | `simple` |
| reference size | `match` |
| H3 flow shift | video `12` / audio `3` |
| seed | `424243` |
| 音频策略 | silent |

输出文件由 ComfyUI 的 `SaveVideo` 节点完成封装。通过 ffprobe 和 OpenCV 复核，成功结果均为
1184×672、24 fps、5.167 秒、124 帧；因此候选之间的差异不是因为某一项生成了更短的视频。

### 2.2 运行环境

实验机器在 ComfyUI 日志中识别为：

| 项目 | 值 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4090 Laptop GPU |
| CUDA 架构 | Ada / SM89 |
| 显存 | 16376 MB |
| Python | 3.13.11 |
| PyTorch | 2.10.0+cu130 |
| ComfyUI | 0.35.1 |
| Comfy Kitchen | 0.2.33 |
| SageAttention | 2.2.0+cu130torch2.10.0andhigher.post6 |
| Triton Windows | 3.7.1.post27 |
| aimdo | 0.5.3 |

这台机器不是物理 RTX 4090D。两者都属于 Ada 家族，但显存容量、功耗墙、频率和散热条件不同，
所以这里不把 Laptop GPU 的数字写成“4090D 实测”。如果之后在 4090D 上复测，应该保留同一个
shot 和 seed，并把本报告作为对照，而不是直接覆盖旧结果。

### 2.3 graph 的共同结构

当前 harness 并不是把 prompt 字符串丢给一个黑盒接口。它首先读取 canonical API workflow，
然后按 runtime contract 改写下列节点或插入 model patch：

1. 载入 H3 transformer、text encoder、video VAE 和 audio VAE；
2. 将角色参考图 staging 到 ComfyUI input 目录；
3. 编译 Ref2VA prompt 和 Picture/semantic role 对应关系；
4. 通过 `MiniMaxH3SigmaShift` 接入 video/audio 的 H3 shift；
5. 通过 `ModelAttentionBackend` 选择 Comfy Kitchen，或插入 KJNodes 的 Sage patch；
6. 运行 `euler + simple` 的 8-step sampler；
7. 执行 video/audio VAE 解码并由 `SaveVideo` 写出 MP4。

这也是为什么本轮不采用“某个 kernel 跑了几毫秒”的数字作为最终结论：用户等待的是这条完整链路。

## 3. 计时方法

### 3.1 E2E 边界

benchmark 脚本在向 `/prompt` 发出 graph 后立即启动单调时钟，直到：

* ComfyUI history 标记 prompt completed；
* `output/video/` 下能够解析到生成的 MP4；
* 输出路径被 harness 成功解析。

因此 `elapsed_seconds` 包含队列提交、模型准备、动态 VRAM staging、第一次 kernel 编译、8 个
denoising step、VAE 解码、音频处理和 MP4 封装。它不包含 ComfyUI 进程启动到 API 可用之前的时间，
因为生产环境通常会让 ComfyUI 常驻；但是每个候选的“冷进程”测试都会在第一次 prompt 内承担模型
准备成本，具体口径在表格中注明。

### 3.2 冷进程与热状态

近似 cache 会保留模型级状态，Speed Cache 还会修改进程级 forward。若在同一 ComfyUI 进程中
顺序运行多个 variant，后面的结果可能受到前面 variant 的模型 clone、编译缓存或 monkey-patch
影响。

所以本轮采取两层处理：

* baseline、AGSoft、Sage explicit CUDA、Sage compile、FastPath 和 Speed Cache 均在单独进程中
  测试；
* TeaCache 与 Spectrum 先有一轮同进程切换结果，但最终报告只采用之后补做的独立冷进程结果。

后一个决定很重要。最初同进程数据是 TeaCache 193.906 秒、Spectrum 200.133 秒；它们看起来很
漂亮，但不能与冷进程 baseline 直接比较。冷进程复测后分别变成 228.076 秒和 251.688 秒，仍然
是有效加速，但幅度更保守。本文将前一组数字明确排除，不把它们混进最终结论。

### 3.3 相对加速的计算

所有“快了多少”都按下式计算：

\[
\text{speedup} = \frac{T_{cold\ baseline} - T_{variant}}{T_{cold\ baseline}}
\]

本轮冷 baseline 取 303.640 秒。对于 exact baseline 的另一条 303.090 秒记录，只用来检查基线
稳定性，不作为候选的分母。两次相差 0.550 秒，约 0.18%，在包含模型 staging、GPU 调度和
视频封装的墙钟计时里属于很小的波动。

## 4. 被测试的方法

### 4.1 Comfy Kitchen：精确质量基线

Kitchen 是当前 canonical graph 的 attention backend。它不跳过 diffusion step，也不改变 H3
sampling trajectory，因此用它作为精确质量基准最容易解释。

需要区分两个概念：

* “精确 baseline”是相对于本项目 workflow 的工程基准，不代表浮点层面与所有其他后端 bitwise
  一致；
* “default production path”是默认给用户跑的路径。本轮在速度决策后把后者改成 Kitchen + TeaCache，
  但保留 `approximation.method: none` 作为显式精确回归路径。

### 4.2 SageAttention

KJNodes 的 Sage patch 会把模型 transformer blocks 中的 attention override 到 SageAttention。当前
仓库支持 `auto`、显式 FP16 CUDA、显式 Triton 以及允许 torch.compile 等选项。

对 SM89，SageAttention 的 `auto` 会根据架构选择 FP8 CUDA 路径；这和“显式指定 FP16 CUDA”不是
一回事。SageAttention 官方 Python dispatch 也把 SM89 单独处理，因此本轮把 `sage`、`sage_cuda`
和 `sage_compile` 分开记录。

### 4.3 TeaCache

TeaCache 的思路不是把一个有效 step 算得更快，而是利用相邻 timestep 的变化规律估计当前模型
输出。如果变化足够小，就复用或预测结果，减少完整 diffusion forward 的次数。当前 harness 的
keep 默认参数为：

```yaml
runtime:
  approximation:
    method: teacache
    teacache:
      rel_l1_thresh: 0.15
      start_step: 2
      end_step: -2
      total_steps: 8
```

`total_steps` 会从实际 profile 的 steps 注入，因此 explore/keep 不会误用固定的 20 steps。
TeaCache 官方项目主要展示的是 cache/forecast 思路和特定模型、特定 steps 下的加速；本报告不把
官方 showcase 数字直接当成 H3 Ref2VA 的本地结果，而只采用本地 API E2E 测量。

### 4.4 Spectrum

Spectrum 同样属于预测类加速，但内部会维护历史状态、拟合 forecast，并提供 warmup、tail、history
storage、offline replay 等控制项。harness 使用官方节点的 balanced 默认组合，并把 video/audio
blend、history storage 等参数完整写入 graph，避免只写一个“enabled”而无法复现。

这类方法的关键风险是：只要预测了一步，后续 latent 就不再沿着精确 baseline 的轨迹走。因此
“输出视频能正常播放”和“视觉质量与精确 baseline 等价”是两个不同命题。

### 4.5 AGSoft cache

AGSoft 是已有的 legacy cache 路径。它仍然可以按显式 `cache.enabled: true` 接入，但现在默认
TeaCache 已经开启，所以二者不能隐式叠加。若要复测 AGSoft，manifest 必须写：

```yaml
runtime:
  approximation:
    method: none
  cache:
    enabled: true
    profile: Balanced
```

这一限制不是为了减少实验选项，而是为了避免两个 model patch 同时修改同一 diffusion forward，
最后得到一个无法解释的速度和质量结果。

### 4.6 FastPath 和 Speed Cache

FastPath 尝试缓存 transformer 中间 block，只保留 prefix/suffix 的精确计算；Speed Cache 则尝试
对 H3 forward 做更一般的 reuse，并可选择 SageAttention。

两者都属于“能不能接到当前 H3 版本”的兼容性实验，而不是成功后才测性能：

* FastPath 在模型初始化后触发 `aimdo memory compile error`，64.465 秒时失败；
* Speed Cache 在独立进程中仍触发 `FinalLayer.forward() missing 3 required positional arguments:
  'sigma', 'sample_sigmas', and 'shifts'`，98.792 秒时失败。

Speed Cache 的官方说明本身也提醒不要把不同 cache 实现串联。当前结果还说明，社区节点针对的
H3 forward 签名与本项目的 ComfyUI 0.35.1/H3 模型实现并不一致。除非上游节点适配这个 ABI，
否则继续调阈值没有意义。

## 5. 实验结果

### 5.1 最终冷进程结算表

| variant | 状态 | E2E 秒 | 相对 303.640s 冷基线 | 输出/失败原因 |
| --- | --- | ---: | ---: | --- |
| exact baseline / Kitchen | completed | **303.090** | 0.18% faster | 精确回归基线 |
| SageAttention `auto` | completed | **292.167** | **3.78% faster** | SM89 自动 FP8 CUDA dispatch |
| SageAttention explicit CUDA | completed | **314.408** | 3.55% slower | FP16 CUDA 可运行但更慢 |
| SageAttention `allow_compile` | completed | **320.432** | 5.53% slower | 可运行，compile 首跑不划算 |
| TeaCache | completed | **228.076** | **24.89% faster** | 独立冷进程，5.167 秒 MP4 |
| Spectrum | completed | **251.688** | **17.11% faster** | 独立冷进程，5.167 秒 MP4 |
| AGSoft Balanced cache | completed | **300.722** | 0.96% faster | 没有超过基线波动范围 |
| FastPath | failed | 64.465 | — | aimdo memory compile error |
| Speed Cache | failed | 98.792 | — | H3 `FinalLayer` ABI 不兼容 |

精确 baseline 另一次完整 keep 运行是 303.640 秒。`exact baseline / Kitchen` 这一行记录的是同一
benchmark sequence 中的 303.090 秒；两者的差异足以说明基线没有出现数量级漂移，但不应该被误读
成两次独立重复实验的置信区间。

### 5.2 之前的 4–6 秒数据为什么不能用

之前的 explore 实验使用 0.5 MP、Turbo、4 steps，并且统计中混合了首次模型准备和 warm run。
其中 Comfy Kitchen 的 steady warm 记录约 4.032 秒，Sage 的 warm 记录约 4.088 秒，PyTorch
约 6.054 秒；这些数字反映的是较小 graph 在已经准备好的进程里的单次 API 完成时间。

它们不是这次用户要求的 keep：

* 分辨率预算从 0.5 MP 变成了 0.75 MP；
* steps 从 4 变成了 8；
* keep 输出有完整的 video/audio VAE 和 MP4 封装；
* warm backend 切换之后的时间不包含与冷进程相同的模型准备成本；
* 这些因素不能通过一句“同一个 ComfyUI”抵消。

因此，之前的 4–6 秒不是“5 秒视频只需 4 秒”的证据，而是探索配置的局部结果。这次把它们保留
在历史文档中作为实验教训，但从 keep 结算表里移除。

### 5.3 输出完整性与数值差异探针

所有成功方案都通过了输出文件解析。它们的 resolution、fps、编码时长和帧数一致，说明 TeaCache
和 Spectrum 的速度收益不是通过截短视频实现的。

为了判断“近似方法到底改了多少”，我又对成功输出与 exact baseline 做了简单逐帧像素探针。对每个
同位置帧计算 RGB 的平均绝对像素差，得到：

| 方案 | 对比帧数 | mean absolute pixel error | p95 |
| --- | ---: | ---: | ---: |
| TeaCache | 124 | 8.892 | 10.711 |
| Spectrum | 124 | 17.446 | 22.543 |
| AGSoft | 124 | 6.920 | 9.759 |
| Sage explicit CUDA | 124 | 9.200 | 12.979 |

这不是 LPIPS、VMAF，也不是人工质量评分。它只能回答“编码后同位置像素是否发生数值变化”，不能
回答“观众是否更喜欢”或“角色身份是否保持”。它的作用是支持一个保守判断：Spectrum 的轨迹
偏离明显高于 TeaCache，所以 Spectrum 虽然可用，不能仅凭“也能生成”把它排在 TeaCache 前面。

抽查的首帧、中间帧和尾帧 contact sheet 没有发现尺寸、黑帧或封装异常；但这仍然不能替代逐视频
人工审核，尤其不能替代对脸部身份、肢体连续性和时间稳定性的检查。

## 6. 现象解释与竞争假说

### 6.1 为什么 TeaCache 的收益显著高于 Sage

最直接的解释是，两者减少的对象不同。

Sage 只影响 attention 子计算。即使 attention 占每个 denoising step 的比例很高，模型还要承担
线性层、normalization、卷积/投影、动态权重 staging、audio/video 分支以及后处理。它把每个有效
step 变便宜，却没有减少有效 step 数量；对于 8 steps 的 keep 流程，端到端收益自然可能只有几个
百分点。

TeaCache 则在满足条件时直接避免完整的模型 forward。日志里的进度条也显示出 step 之间出现明显
的长短交替：部分 step 接近完整计算时间，部分 step 很快结束。这与“anchor step 真算、相邻 step
forecast/reuse”的机制相符。它绕开的不只是 attention，而是该 step 的整条 transformer 计算，
所以收益达到约 25% 并不奇怪。

这不是证明 TeaCache 在所有 shot 上都能快 25%。如果动作更剧烈、镜头切换更多、条件变化更大，
相邻 timestep 的可预测性会下降，cache 触发率可能降低；如果阈值放宽，触发率会上升但轨迹风险也
会变大。这正是下一轮需要把“阈值—速度—质量”画成曲线的原因。

### 6.2 为什么 Spectrum 能加速但不如 TeaCache

Spectrum 的结果仍然比 exact baseline 快约 17.11%，说明其预测确实减少了有效计算。但它维护历史
并执行 forecast/replay/correction，会引入额外 bookkeeping；在只有 8 steps 的短序列中，这部分
固定开销占比并不小。

另一个可能解释是 conservative correction 策略：为了不让预测误差持续积累，Spectrum 会保留 warmup、
tail 和部分实际计算。它因此比简单地激进跳过更稳，但也不可能获得同样的最大 speedup。这个解释
目前仍然是工作假说，因为当前 benchmark 没有记录每一步的“真实执行/预测/回滚”计数；代码层面
已经把这些配置纳入 runtime，下一轮可以加计数器验证。

### 6.3 为什么 Sage auto 只快约 3.78%

本机 SM89 上 `auto` 会选择 FP8 CUDA 路径。它确实完成了完整视频，并比 303.640 秒略快。这个
3.78% 明显大于本轮两次 baseline 的 0.18% 差异，但单次候选仍然不足以给出稳健的统计区间。

explicit FP16 CUDA 达到 314.408 秒，说明“使用 SageAttention”不能简化成“任意 Sage 模式都快”。
不同 kernel 的适用架构、累加精度、编译路径和当前 H3 tensor shape 都会改变结果。`allow_compile`
达到 320.432 秒，也没有抵消 compile 首次成本；在当前 8-step、单镜头任务上，compile overhead
没有摊薄到足够多的批量。

### 6.4 为什么 AGSoft 的 0.96% 不算收益

AGSoft 的 300.722 秒比 303.640 秒少 2.918 秒，看起来是正数。但这次完整 E2E 中 baseline 本身
有 0.550 秒重复波动，GPU 调度、Windows WDDM、动态 offload 和 MP4 写入都可能造成几秒级变化。
没有至少多次重复、并且没有明确的 cache hit/miss 计数时，把 0.96% 写成“有效加速”是不负责任的。

更合理的结论是：AGSoft 在这个 shot 上能完成，但没有显示出值得承担额外兼容性和质量不确定性的
收益。因此它保留为显式 legacy experiment，不进入默认路径。

### 6.5 为什么 FastPath 和 Speed Cache 不应该继续调阈值

FastPath 失败在 aimdo memory compile，而不是输出质量或 cache threshold。Speed Cache 失败在
`FinalLayer.forward` 参数 ABI，而不是“触发率太低”。两类错误都发生在生成完成之前，继续调
`reuse_threshold`、`start_percent` 或 `max_consecutive_skips` 不会改变根因。

如果未来要重新评估：FastPath 需要先确认 aimdo 是否支持当前节点 wrapper；Speed Cache 需要先把
上游节点的 `FinalLayer` 调用改到当前 H3 signature，并用单元测试锁住 `sigma`、`sample_sigmas`
和 `shifts` 的传递。只有 ABI 修复后，性能实验才有意义。

## 7. 默认策略为什么选 TeaCache

这里的“选最优”不能只看一列秒数。工程上至少有四个维度：

| 维度 | Kitchen | Sage auto | TeaCache | Spectrum |
| --- | --- | --- | --- | --- |
| 精确轨迹 | 最强 | attention 数值有差异 | 明确是近似 | 明确是近似 |
| 冷进程 E2E | 303.640s | 292.167s | **228.076s** | 251.688s |
| 当前可用性 | 稳定 | 稳定 | 稳定 | 稳定 |
| 额外质量风险 | 最低 | 低到中 | 中 | 中到高（本轮像素偏差更大） |
| 适合作为默认 | 精确基线 | 不值得替换 Kitchen | **速度默认** | 备选实验 |

用户已经明确希望默认先使用 TeaCache，之后可以调整。因此仓库做出以下分层：

1. 默认 `runtime`：Kitchen attention + TeaCache；
2. 精确回归：`runtime.approximation.method: none`；
3. Sage：显式 attention 消融；
4. Spectrum：显式 forecast 消融；
5. AGSoft、FastPath、Speed Cache：只作为兼容性/历史实验，不进入生产默认。

这个选择承认了近似方法的收益，也承认它不是无损优化。默认切换不是宣布 TeaCache 在所有内容
上都“最好”，而是把当前已测、能完成输出、速度收益明显的方案放到最常用路径；质量回归仍有一条
清楚、可命名、可复现的 exact path。

## 8. Windows 环境改动

这次实验暴露出的实际问题不全在 H3 graph，部分来自 Windows runtime。

### 8.1 Triton 编译缓存

Sage explicit CUDA 第一次测试失败，是因为 Triton 默认尝试写用户目录下的 `.triton/cache`，触发
Windows 拒绝访问。启动脚本现在把：

```text
TRITON_CACHE_DIR = <repo>/temp/triton-cache
```

并继续注入 bundled Triton compiler 和 CUDA library 路径。修复后 Sage explicit CUDA 可以完成视频，
但实测依旧比 Kitchen 慢，所以这项修复是“让它可用”，不是“让它必然更快”。

### 8.2 UTF-8 custom node 加载

AGSoft 启动时会打印 Unicode 状态标记。启动脚本增加 `PYTHONUTF8=1`，避免系统 console code page
把一个无关的输出编码问题变成 custom node import failure。修复后 TeaCache、Spectrum、Speed
Cache、FastPath、KJNodes 和 AGSoft 都能被 ComfyUI 注册。

### 8.3 依赖和版本锁定

KJNodes 与四个 H3 实验节点都在配置中写入固定 commit。依赖清单记录 SageAttention 和 Triton
Windows 的版本；setup 脚本支持按固定 revision checkout，避免下一次拉取上游时把实验对象悄悄换掉。

这不是为了冻结整个生态，而是为了保证报告中的“同一个方法”在重跑时有明确的代码身份。如果要
升级 ComfyUI、KJNodes 或某个 cache 节点，应生成新的 benchmark report，而不是覆盖当前 JSON。

## 9. 可复现实验命令

精确 baseline：

```powershell
python scripts/benchmark_h3_runtime.py shots/nun/shot01_idle.yaml `
  --api-url http://127.0.0.1:8198 --profile keep --seed 424243 `
  --variants mainline
```

TeaCache：

```powershell
python scripts/benchmark_h3_runtime.py shots/nun/shot01_idle.yaml `
  --api-url http://127.0.0.1:8200 --profile keep --seed 424243 `
  --variants teacache
```

每个 approximation variant 都应在新的 ComfyUI 进程中启动。尤其不能在同一个进程里先运行
Speed Cache，再把后续输出当成其他 variant 的结果；benchmark 脚本现在会拒绝把 Speed Cache 与
其他 variant 放在同一条命令中。

完整结算 JSON：

[`benchmarks/h3-keep-ablation-20260916.json`](../../benchmarks/h3-keep-ablation-20260916.json)

该 JSON 除了耗时，还记录输出规格、硬件身份、失败原因、运行时选择和逐帧数值探针。真实 MP4
保留在 `output/video/`，因为视频本身会被 `.gitignore` 排除，不应与源代码一起提交。

## 10. 局限

### 10.1 样本量有限

每个候选只做了一次完整视频，baseline 做了两次。这个设计足以发现数量级错误和明显的兼容性
问题，但不能估计均值、方差或置信区间。尤其 AGSoft 的 0.96% 不应被当成统计显著收益。

### 10.2 shot 单一

当前 shot 是单角色、浅色背景、无切镜、动作幅度较小的 5 秒镜头。它非常适合做 identity/动作
稳定性 smoke test，却不能代表快速镜头、复杂背景、多角色、强遮挡、连续交互或大幅位移。
TeaCache 可能正好受益于这个 shot 的相邻状态相似性。

### 10.3 质量指标还不够

像素 MAE 只证明数值不同，不能证明好坏。需要加入人工盲评、身份一致性、结构稳定性、运动平滑度、
首尾帧约束和音视频同步检查。特别是 Spectrum 的数值偏差更大，不等于它一定更差，但它更需要
有针对性的人工审核。

### 10.4 冷启动和生产吞吐不是同一个指标

冷进程 E2E 包含模型准备和第一次 kernel compile；常驻 ComfyUI 的第二个任务可能更快。反过来，
如果用户只生成一个视频，冷启动成本就是用户真实要等的时间。未来应该同时报告：

* cold single-shot latency；
* warmed single-shot latency；
* 连续 N 个 shot 的 mean/p50/p95 throughput；
* GPU 峰值显存和系统 RAM 峰值。

### 10.5 硬件不完全匹配

本机实际是 RTX 4090 Laptop GPU。4090D 复测时，Sage FP8 dispatch、WDDM scheduling、显存压力和
频率策略都可能变化。报告中的排序有参考价值，具体秒数必须重新测。

## 11. 下一轮实验计划

### 11.1 把单次结算升级为小型 benchmark suite

建议至少准备四类 shot：

1. idle/微表情，测试低变化场景的 cache 上限；
2. 小幅动作和慢推镜，测试日常生产场景；
3. 大幅动作或快速镜头，测试预测失效时的退化；
4. 遮挡、复杂背景或多参考语义，测试 reference conditioning 的稳定性。

每类使用 3 个 seed、每个 variant 3 次，报告 mean、median、p95 和失败率。只要预算允许，再加入
一条精确 baseline 和一条 TeaCache threshold sweep，就能把当前的“单点速度”变成可用的决策曲线。

### 11.2 TeaCache 参数扫描

当前只测了 `rel_l1_thresh=0.15`。下一轮应固定 shot/seed，扫描例如 0.05、0.10、0.15、0.20，
并记录：

* 实际 forward/reuse 次数；
* E2E 时间；
* pixel MAE、LPIPS 或视频质量代理指标；
* 人工盲评中身份、手部、脸部和运动连续性的失败率。

如果 0.10 的速度只比 0.15 慢一点，却显著降低质量风险，那么生产默认应该用 0.10，而不是盲目
选择当前最快点。相反，如果多个 shot 上 0.15 都没有可见质量损失，才有理由进一步提高阈值。

### 11.3 分阶段计时

下一版 benchmark 可以在 ComfyUI 节点层写入 stage timestamps，把端到端时间拆成：

* reference staging；
* text encoding；
* model load/offload；
* denoising；
* audio/video VAE；
* MP4 encode。

这样可以验证一个重要推测：TeaCache 的主要收益来自 denoising，Sage 只优化其中 attention 的
一部分，而在小 steps 下 model staging 和 VAE 占比可能足以掩盖 kernel 优势。

### 11.4 解决失败节点，而不是继续盲调参数

FastPath 需要先做 aimdo compatibility matrix；Speed Cache 需要先提交 H3 `FinalLayer` ABI
适配。修复后再测，不要把“失败后耗时较短”写成加速结果。若上游长期不维护，项目应保留失败记录
和 pinned revision，但不继续把它们当作生产候选。

## 12. NSFW library 的下一阶段：从 tag 堆积转向可组合语义

这部分是下一项工作，不与本次运行时提交混在一起。当前 `action.json` 的问题不是“tag 数量不够”，
而是不同抽象层的内容被放在同一个平面里，导致同义重复、组合爆炸和语义冲突同时出现。

### 12.1 先分层，再排列组合

建议把一个 prompt card 拆成以下层次：

| 层 | 回答的问题 | 例子（抽象描述） |
| --- | --- | --- |
| subject/agency | 谁在场、主体是否主动、关系和成人资格是什么 | 单主体、成人虚构角色、主动/被动叙事 |
| action | 主体正在做什么 | 持续、开始、停止、保持、转向 |
| interaction/contact | 动作作用于谁或什么，接触关系是什么 | 自身、伙伴、物体、环境表面 |
| pose | 身体几何怎样摆放 | 站、坐、跪、侧卧、俯卧、靠、蜷缩 |
| prop/tool | 是否存在可见物件、物件类别和握持方式 | 普通道具、专用道具、机械装置 |
| expression | 脸和身体正在表现什么状态 | 视线、眉眼、嘴型、呼吸、脸红、紧张 |
| physiology | 身体可观察到的生理反应 | 出汗、呼吸变化、流泪、唾液、皮肤潮红 |
| camera | 观众从什么角度和距离看到它 | close-up、medium、full body、profile、POV |
| setting | 事件发生在哪里、光线和可见性如何 | 室内、公共空间、私密空间、平面背景 |
| timeline | 动作怎样按时间发生 | 前戏/过渡/高潮/结束/aftercare 等阶段标签 |
| style_effect | 画面额外出现什么视觉或超自然效果 | 眼部 overlay、光晕、粒子、速度线、失焦 |
| audio | 是否有声音、声音来源和节奏 | 静音、环境声、呼吸、拟声、音乐 |

这里最重要的改动是把 `action`、`interaction/contact`、`pose` 和 `prop/tool` 分开。比如“靠在
平面上”和“使用某个道具”不是同一类 tag；前者是 pose/setting 的组合，后者是 prop/tool，真正的
动作仍需要另一个 action 原子。否则同一个概念会被写成几十个看似不同的自然语言短语。

### 12.2 expression 和 effect 的边界

你指出两者容易重复，这个判断是对的。建议采用下面这条边界：

* `expression` 描述角色作为一个人的可见状态：眼神是否聚焦、嘴角是否上扬、是否害羞、是否茫然、
  是否张口呼吸、是否恢复平静。它原则上不改变眼睛的材质和画面渲染规则。
* `physiology` 描述身体反应：呼吸、汗、泪、唾液、皮肤发红、肌肉紧张。这些是角色身体状态，
  但不等于“情绪名称”。
* `style_effect` 描述画面层的视觉变化：瞳孔形状、眼睛高光、虹膜发光、渐变色、圈圈眼、爱心
  瞳孔、催眠环、粒子和光晕。它们可以与 neutral 或 focused expression 同时存在。

这样，“失去高光但眼睛颜色不变”属于 eye-render effect，不是 expression；“眼神变得空洞”属于
expression；“虹膜变成发光粉色”属于 style_effect；“脸红、呼吸加快”属于 physiology。四者
可以分别控制，也可以在 card 层声明组合约束。

### 12.3 二次元表情不应直接堆进一个大数组

用户想要的猫猫嘴、撒娇、傲娇、噘嘴、吐舌、rolling eyes、ahegao 等，至少来自三个不同轴：

1. 嘴型：neutral mouth、small smile、cat mouth、pout、open mouth、tongue visible；
2. 眼睛与视线：direct gaze、side glance、closed eyes、half-lidded、rolling eyes、vacant gaze；
3. 面部与身体反应：blush、embarrassed、focused、dazed、overwhelmed、relaxed。

因此建议保留可读的 canonical expression id，例如：

```text
neutral_composed
playful_cat_mouth
affectionate_pout
tsundere_avoidant_gaze
embarrassed_blush
focused_eye_contact
open_mouth_breathing
rolling_eyes
dazed_vacant
hypnosis_transition
pleasure_overwhelmed
aftercare_relaxed
```

但这些 id 不能直接任意全排列。`rolling_eyes` 与 `focused_eye_contact`、`aftercare_relaxed` 与
`intense_expression` 都应被标成低兼容或互斥；`hypnosis_transition` 则更适合作为 timeline state，
而不是静态 expression。这样比继续往数组里添加同义词更容易控制 H3 的自然语言展开。

### 12.4 眼部 mind-control 视觉效果应独立成族

你提出的四类瞳孔/高光状态，适合做一个单独的 `eye_effect` namespace，而不是塞进 expression：

* catchlight absent：眼睛颜色不变，只移除高光；
* pupil geometry：经典圈圈、简化螺旋、受限圈数，明确禁止过度重复；
* iris emission：粉色/紫色发光，支持纯色与渐变，独立控制强度；
* symbolic pupil：极小爱心或其他符号，控制尺寸、位置和可见性。

每个 eye effect 至少需要 `shape`、`color`、`intensity`、`transition`、`camera_visibility` 五个
字段。camera_visibility 很关键：如果画面不是近景，模型可能无法稳定生成小爱心或虹膜渐变；这不
是 effect 本身失效，而是 camera 没有给它足够像素预算。

### 12.5 组合不是笛卡尔积，而是带约束的图

如果把 1000 个原子全部做笛卡尔积，得到的不是 1000 个能力，而是大量不可能、重复或互相覆盖的
prompt。更合理的做法是把 card 表示为带约束的组合图：

```text
subject
  ├─ agency / relationship
  ├─ action
  │   ├─ target/contact
  │   └─ prop/tool
  ├─ pose
  ├─ expression
  ├─ physiology
  ├─ eye_effect / style_effect
  ├─ camera
  ├─ setting
  ├─ timeline
  └─ audio
```

每个原子需要有 canonical id、自然语言 realization、同义词、父类、互斥项、依赖项和镜头可见性。
例如一个动作原子可能依赖某种接触关系；一个眼部小效果依赖 close-up；一个 timeline transition
依赖前后两个 state；一个 pose 可以与多个 action 兼容，但不是每个 action 都兼容每个 pose。

### 12.6 第二阶段的实际工作顺序

整理 library 时，我建议按下面顺序做，而不是立刻继续新增 tag：

1. 读取 `library/nsfw/imports/action.json`，统计 exact duplicate、近义重复、跨层重复和只在
   natural-language 中不同但语义相同的条目；
2. 建立 canonical namespace 和 alias 表，先减少重复，不改变原始来源记录；
3. 把 action、contact、pose、prop、expression、physiology、effect、camera、setting、timeline、
   audio 做成独立 registry；
4. 给每个原子补 `requires`、`excludes`、`visibility` 和 `risk/age_gate` 元数据；
5. 用小规模组合生成 H3 natural-language prompt，检查是否出现重复描述、互相冲突或 camera 看不见
   目标效果；
6. 最后才把通过 schema 和人工检查的组合注入 `library/nsfw/`，不直接覆盖原始 `action.json`。

本报告不在这一阶段提前把大量露骨动作写进 library。那会把“调研、去重、分层、组合约束”和
“生成 prompt 内容”混成一次不可审计的迁移。下一项工作应该先把 registry 结构和去重结果做出来，
再决定哪些成人向、虚构、明确成年且合规的条目进入可生成集合。

## 13. 总结

这次实验真正解决的不是“找到一个更快的插件”，而是把一个容易被误读的数字还原成了可复现的
工程事实：5 秒 H3 keep 视频在当前 Windows Ada 机器上大约需要 5 分钟，而不是几秒。之前的快数
来自 explore/warm 条件，不能替代 keep E2E。

在这个正确口径下，TeaCache 是唯一同时满足“完成视频、收益明显、接入成本可控”的速度优选；它
把冷进程时间从 303.640 秒降到 228.076 秒，约减少 75.564 秒。SageAttention 的 auto 后端可用，
但只改变 attention 子计算，收益不足以取代 Kitchen；explicit CUDA 和 compile 结果进一步说明
“同一名字下的不同 kernel/编译开关”必须拆开测。Spectrum 有实际收益，但当前参数和 shot 上不及
TeaCache，且数值偏差探针更大。AGSoft 没有显示出值得默认化的收益，FastPath/Speed Cache 则先被
兼容性问题挡住。

默认切换到 TeaCache 是一个可撤销的生产决策，不是对近似质量的永久背书。仓库保留 exact baseline，
并且把 runtime、依赖、节点 revision、测试脚本和完整 keep 结算 JSON 一起提交。下一步如果要把
这个项目沉淀成更有说服力的社区工作，优先级应该是：扩大 shot/seed 样本、记录每一步 forecast
与 reuse、做阈值—质量曲线，再把 NSFW library 从 tag 堆积改造成有类型、有依赖、有可见性约束的
组合系统。

## 参考资料

本文的技术判断以本地 graph、ComfyUI 日志、输出文件和仓库内 benchmark JSON 为主；社区实现的接口
和设计动机参考以下公开项目：

* [ComfyUI-MiniMaxH3-TeaCache](https://github.com/Icyoung/ComfyUI-MiniMaxH3-TeaCache/releases)
* [ComfyUI-Spectrum-MiniMax-H3](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3)
* [ComfyUI-KJNodes Sage implementation](https://github.com/kijai/ComfyUI-KJNodes/blob/main/nodes/model_optimization_nodes.py)
* [comfyui-speed-minimaxH3](https://github.com/linjian-ufo/comfyui-speed-minimaxH3/blob/main/README_EN.md)
* [ComfyUI-MiniMax-H3-FastPath](https://github.com/capitan01R/ComfyUI-MiniMax-H3-FastPath)

写作上的处理遵循 Bubblevan 公开的博客规范：从真实事件和可核验结果开始，区分事实、假设和下一步
计划，避免用空泛的“全面提升”“显著赋能”替代数字与证据。[Bubblevan Agents 写作说明](https://bubblevan.github.io/blog/agents/)
