# MiniMax H3 本地 NSFW library 原子化审计报告

日期：2026-09-16

## 摘要

本轮目标不是删除用户提供的 action.json，也不是把逗号分隔字符串原样搬到另一处，而是建立一层可审计的 H3 组合表示：

source record -> normalized evidence -> canonical dimensions -> H3 natural-language fragment

原始文件继续作为证据层保存，新的 compiled/action_atoms_h3.json 作为注入层保存。每条记录都保留
原始值、归一化标签、维度原子、语义指纹、H3 片段和复核状态，因此后续人工折叠重复项时仍可以
回溯到来源。

## 数据完整性与重复审计

输入文件为 library/nsfw/imports/action.json，共 654 条 object-map 记录。审计得到：

| 指标 | 数值 | 含义 |
| --- | ---: | --- |
| 原始记录数 | 654 | 不改动来源规模 |
| 完整字符串唯一数 | 651 | 只有 3 个完全重复的额外记录 |
| 归一化字符串唯一数 | 649 | 去除权重括号、大小写和空白差异后，额外重复 5 条 |
| 语义指纹唯一数 | 419 | 在当前规则下，多个来源记录落入相同维度组合 |
| 语义重复组 | 62 | 仅作为人工复核队列，不直接判定等价 |
| 语义重复额外记录 | 235 | 说明扁平来源存在明显的组合复用和编号变体 |
| 未映射标签种类 | 850 | 仍需后续扩展外观、角色、道具细节或人工命名 |
| 画质/LoRA 噪声出现次数 | 56 | 已记录为来源噪声，不进入场景动作原子 |

这里的语义指纹只由当前维度映射结果组成。例如同一个动作的不同姿势、视角或道具如果被成功
识别，会得到不同指纹；而未能识别的细节会被压缩到同一复核组。因此“62 组”不是可以安全删除
的数据量，而是值得逐组检查的候选集合。

## 维度统计

当前编译器为每条记录写入以下维度：

- subject：角色数量和角色关系的结构化信息；
- action：场景级正在发生的事情；
- interaction：solo、partner、group、prop contact 和 restraint-roleplay；
- pose：身体支撑与几何排列，不把姿势误当成动作；
- prop：软支撑、成人道具、家用物、科幻机器、幻想附肢和支撑面；
- appearance：身体细节、服装、裸露状态、头发/身份细节；
- expression：脸、眼、嘴、视线和意图性情绪；
- physiology：呼吸、出汗、唾液、颤抖以及其他身体反应；
- camera：镜头关系和可见性；
- setting：卧室、浴室、室内、车辆、桌面、户外和虚构实验室；
- motion：连续节奏、呼吸、渐变和 aftercare settle；
- effects：虹膜、catchlight、同心环、爱心高光、蒸汽和稀疏运动线；
- audio：默认静音，未来可单独引入环境声或对话。

主要统计如下：

- action：partner intimacy 329，self-directed intimacy 58，aftercare 16，nonsexual activity 4，
  review-required 247；
- interaction：partner contact 321，solo subject 292，group contact 41，prop contact 316，
  restraint-roleplay 33；
- pose：未明确姿势 406，seated 70，legs raised 65，lying on back 52，straddling 35，
  standing 34，其他为 all-fours、kneeling、arms-behind、leaning 等；
- expression：neutral fallback 513，embarrassed blush 65，focused eye contact 56，
  dazed/vacant 17，anticipatory smile 17，ahegao 14，tongue-out 26，rolling-eyes 6；
- setting：593 条来源没有明确可用的场景词，说明 setting 不能从 action 标签可靠推断，应该
  由 shot 或 recipe 显式提供。

“未明确姿势 406 条”是一个重要信号：缺失信息不能被默认成 standing，否则会把未知误写成事实。
因此当前注入层使用 pose.unspecified，并要求后续人工或 shot recipe 补全。

## 为什么 expression 应该单独存在

expression 与 effects 的边界现在明确为：

| 层 | 负责什么 | 示例 |
| --- | --- | --- |
| expression | 肌肉、眼球、嘴型、视线和意图性情绪 | neutral composed、anticipatory smile、embarrassed blush、pout、cat mouth、tsundere-defiant、rolling eyes、tongue out、ahegao |
| physiology | 身体反应和可观察的生理连续性 | breathing、perspiration、saliva、trembling |
| effects | 风格化、超自然或后处理式视觉变化 | loss of catchlights、pink/purple iris glow、limited concentric rings、small heart highlight |

因此 rolling eyes 是眼球运动/表情，不能与 loss of catchlights 混成一个眼睛特效；
ahegao 是面部状态，不能直接推出任何虹膜颜色变化；heart highlight 是视觉效果，不能替代
脸部表情。眼部 effects 还必须满足 camera visibility rule，在 eye_detail 或 face_closeup
下才有意义。

## 组合规则

组合层位于 library/nsfw/atoms/registry.yaml。它不枚举笛卡尔积，而是使用：

1. 每个 shot 在 action、interaction、pose、expression、camera、setting、motion、audio 中通常
   选择一个主原子；
2. effects、physiology、prop 可以按需重复；
3. requires 描述可见性、成年、虚构、同意、支撑面等先决条件；
4. excludes 和 conflict_rules 防止同一静态 beat 产生相互矛盾的状态；
5. transition_exceptions 允许时间轴上的先后变化。

现有的 hypnosis eye transition 已登记为组合示例。其含义是：

loss_of_catchlights -> full_iris_glow -> concentric_rings

这是三个连续 beat 的状态变化，而不是同一个静态画面同时要求“自然 catchlight 消失”和“整
个虹膜发光”。这正是 H3 natural-language prompt 比扁平 tag 更需要时间语义的地方。

## H3 注入方法

编译器不会把 canonical id 直接输出给模型，而是从 registry 的 h3_phrase 渲染自然语言。
例如一个自导向成人场景的原子记录会变成：

- 明确成年的虚构主体；
- 一个 private, self-directed intimate action；
- solo subject interaction；
- 明确的 pose / camera / motion；
- adult-only、fictional-only、explicit-consent 约束；
- 若来源含风险标记，附带 manual review 或 blocked 说明。

输出不是新的安全批准。source.raw_value 只表示来源曾提供过这个字符串；实际生成仍须经过
成年、虚构、明确同意和人工复核要求。

## 复核状态

当前 654 条记录分为：

- candidate：334 条，没有触发当前规则中的额外复核标记；
- manual_review：307 条，通常是来源主体/年龄表达不完整、含 restraint、第三方 LoRA 或动作
  语义不确定；
- blocked：13 条，触发非自愿、强迫、窒息/溺水或同类来源标记，不得自动运行。

这套状态是导入治理状态，不是对角色或作品的价值判断。尤其是 candidate 也不等于最终可
生成；实际 shot 仍要提供明确成年和同意上下文。

## 局限

当前编译器是可重复的规则系统，不是完整的自然语言理解模型。主要局限有：

- 同义词和拼写变体仍会落到 unmapped_tags；
- 复杂原始描述可能同时表达多个 action，当前只选择一个主 action；
- 未明确出现的姿势、镜头和 setting 不能从标签可靠反推；
- semantic fingerprint 会把“未识别细节不同”的记录暂时聚到一起；
- audio 当前全部默认 silent，因为来源没有可靠的音频语义；
- 第三方 LoRA、模型卡和工作流的许可证仍需在真正使用前单独确认。

## 下一步

1. 逐个处理 62 个 semantic duplicate groups，人工确认哪些只是编号变体，哪些需要保留为
   不同 pose / camera / prop atom；
2. 把 850 个 residual tags 按 appearance、identity、prop、setting 和 style 分桶，不把角色
   名称、画质词和动作词混在一起；
3. 为确认过的安全组合添加可物化 recipe，而不是自动生成所有笛卡尔积；
4. 用固定角色、固定参考图、固定 seed 做 expression/effects/camera 的小规模 A/B；
5. 将审核通过的组合回填到正式 shots/，保留 source id、atom ids 和实验结果。

重建命令：

    python scripts/analyze_action_library.py
    python scripts/nsfw_library.py validate
    python scripts/nsfw_library.py atom-info
    python scripts/nsfw_library.py atom-show "masturbation" --prompt

本报告、审计 JSON、原子 JSON 和 registry 共同构成这轮迁移的可追溯结果。
