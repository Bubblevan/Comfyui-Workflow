# Local NSFW library for MiniMax H3 Ref2VA

这是一个角色无关、可追溯的本地成人向 prompt-card library。它服务于当前仓库的
`character manifest -> shot YAML -> H3 prompt compiler` 链路，不替代正式的
`shots/` 目录，也不自动下载或复制第三方素材。

## 当前边界

- 只收录明确为成年人的虚构角色；
- 所有成人向情境必须以明确同意的 roleplay / fantasy 为前提；
- 禁止未成年人、年龄模糊角色、真人性化、非自愿性行为和性暴力语境；
- 第一批条目故意从非露骨的视觉状态与镜头语言开始，先建立可复用的 H3 时间轴语法；
- 每个条目都保留 `compatibility`、`provenance` 和 `review`，以后导入模型卡、workflow 或 Civitai
  样例时不能只抄 prompt 文本而丢掉参数。

## 目录

```text
library/nsfw/
  catalog.yaml                         # 入口、策略、条目索引
  sources.yaml                         # 调研来源与使用备注
  schema/entry.schema.json             # prompt card schema
  entries/
    effects/                           # 可观察的状态变化
    poses/                             # 构图/姿态卡
    camera/                            # 镜头卡
  recipes/
    hypnosis_eye_transition.yaml       # 可直接物化为正式 shot 的 recipe
  workflows/
    stefan_h3_v22/                      # 用户提供的 workflow 原样快照
    registry.yaml                       # hash、节点能力与兼容性登记
  imports/
    action.json                         # 从 IsekaiStory 原样迁移的动作字典
    registry.yaml                       # 迁移文件 hash 与条目数
  compiled/
    action_cards_h3.json                # 654 张转换后的 H3 prompt cards
```

## 用法

```powershell
# 校验 catalog、全部条目和 recipes
python scripts/nsfw_library.py validate

# 从 imports/action.json 重建 H3 action cards
python scripts/compile_action_library.py

# 列出本地条目
python scripts/nsfw_library.py list

# 查看一张卡
python scripts/nsfw_library.py show effect.hypnosis.loss_of_catchlights

# 把 recipe 物化为正式 shot；默认不覆盖已有文件
python scripts/nsfw_library.py materialize shot_hypnosis_eye_transition --character nun --references primary,face --out shots/nun/shot04_hypnosis_eye_transition.yaml

# 物化后再走现有 harness 的校验和 prompt 编译
python scripts/h3.py validate
python scripts/h3.py prompt shots/nun/shot04_hypnosis_eye_transition.yaml
```

## 条目规则

条目用自然语言和时间轴描述可观察结果，不使用没有时间语义的 tag soup。一个条目只测一个
主要变量，例如“高光消失”或“虹膜出现同心环”，避免同时混入 reference 偏置、姿态变化和
成人动作，方便 A/B 与失败归因。

`recipes/` 是最终 shot 的组合层。v1 只提供显式 recipe，不自动把多个条目的 beats 粗暴拼接，
因为不同卡的时间轴可能冲突。确认一个组合稳定后，再把它固化为 recipe 并记录实验结果。

## 来源与许可证

`sources.yaml` 只记录调研入口、参数线索和 provenance，不把第三方模型、workflow、图片或视频
复制进仓库。下载任何 LoRA、workflow 或 sample 前，仍需单独检查作者许可证、平台规则与模型兼容性。

## Workflow 快照

`workflows/stefan_h3_v22/` 保存了你提供的四份 JSON 原样快照。当前推荐重点研究：

- `Minimax H3 Ref2V.json`：9 张图、3 个参考视频、3 个独立音频参考，以及 Cache / Sage / LoRA 旁路；
- `Minimax H3 Ref2V Prompt generator.json`：把自由描述扩写为 H3 六段式 prompt 的参考实现。

快照只作为可追溯参考，不会自动替换当前 harness 的 deterministic compiler，也不会自动启用其中的
Heretic encoder、成人示例文本或第三方 LoRA。

`imports/action.json` 按原始 JSON object map 保存 654 个动作名与 prompt 字符串，大小和 key 大小写
均保持不变；迁移索引见 `imports/registry.yaml`。

`compiled/action_cards_h3.json` 才是实际注入 library 的可用层：每条记录把原始 action 转成 H3
六段式 prompt 和可合并的 `shot_fragment`。使用 `action-show` 时默认显示转换后的 H3 prompt，
需要回看原始 tag 才加 `--raw`。

## 主流程 runtime profile

shot 可以按需加入 `runtime`，把参考 workflow 的运行参数接入 canonical API graph：

```yaml
runtime:
  ref_image_size: match
  sampler: euler
  scheduler: simple
  attention:
    backend: kitchen       # default / kitchen / sage
  cache:
    enabled: true
    profile: Balanced
```

不写 `runtime` 时使用已合入主干的 H3 默认值：`match` reference-size、`euler + simple`、
`MiniMaxH3SigmaShift(12/3)` 和 Comfy Kitchen attention。`runtime` 现在是覆盖层，而不是
主流程的能力开关；`sage` 与 `cache` 仍需显式指定，因为它们在参考 workflow 中是 bypass 的
实验路径，且需要用固定 seed 做质量/稳定性 A/B。
