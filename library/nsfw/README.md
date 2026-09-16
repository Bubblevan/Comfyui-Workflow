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
  schema/action-atom.schema.json       # compiled source-atom schema
  schema/atom-registry.schema.json     # canonical registry schema
  atoms/registry.yaml                  # dimensions, phrases, and composition constraints
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
    action_atoms_h3.json                # 654 条按维度拆分的 H3 原子记录
    action_audit.json                   # 重复、残余 tag、风险复核统计
```

## 用法

```powershell
# 校验 catalog、全部条目和 recipes
python scripts/nsfw_library.py validate

# 从 imports/action.json 重建 H3 action cards
python scripts/compile_action_library.py

# 从原始记录重建 compositional atoms 和审计报告
python scripts/analyze_action_library.py

# 查看原子库统计和按维度筛选
python scripts/nsfw_library.py atom-info
python scripts/nsfw_library.py atom-list --dimension expression
python scripts/nsfw_library.py atom-list --review blocked
python scripts/nsfw_library.py compose --atoms action.nonsexual_activity,interaction.solo_subject,pose.seated,expression.hypnosis_transition,camera.eye_detail,motion.gradual_transition,effects.loss_of_catchlights,effects.full_iris_glow,effects.concentric_rings,audio.silent --temporal --prompt

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

`atoms/registry.yaml` 是组合层的主干。当前维度顺序是 `subject -> action -> interaction ->
pose -> prop -> appearance -> expression -> physiology -> camera -> setting -> motion -> effects ->
audio`。其中 `expression` 只描述脸、眼、嘴和意图性情绪；`physiology` 描述呼吸、出汗、唾液、
颤抖等身体反应；`effects` 描述高光消失、虹膜发光、有限同心环、爱心高光等风格化/超自然视觉
变化。这样可以避免把“rolling eyes”同时当作表情和特效，也能用 camera 可见性规则约束眼部细节
不要在全身镜头里凭空出现。

眼部 hypnosis transition 已作为组合示例登记：`loss_of_catchlights -> full_iris_glow ->
concentric_rings` 是时间轴上的先后变化，不是同一静态 beat 的冲突叠加；`transition_exceptions`
专门记录这种情况。这个规则也解释了为什么“表情”和“特效”不能只靠一个扁平 tag 表示。

`compiled/action_atoms_h3.json` 是来源字典的结构化注入层：每条记录保留原始字符串，同时给出
canonical dimensions、H3 natural-language fragment、semantic fingerprint 和复核状态。它不把
来源字符串自动视为批准内容：`blocked` 不得自动运行，`manual_review` 必须先人工确认，只有
明确成年、虚构、同意的场景才进入实际生成。

审计中的 semantic duplicate group 只是复核队列，不是强制删除或断言等价。因为同一 fingerprint
可能仍有不同的构图意图，只有人工确认后才应将多个来源折叠为一个 canonical atom。

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
`MiniMaxH3SigmaShift(12/3)`、Comfy Kitchen attention 和 TeaCache approximation。`runtime`
现在是覆盖层；只有明确写 `approximation.method: none` 才回到 keep 基线。Sage、Spectrum、
Speed Cache、FastPath 仍保留为可复现实验路径，并且必须用固定 seed 做质量/稳定性 A/B。
