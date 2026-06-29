---
name: gpt-image-2
description: >-
  专业编写 GPT Image 2 的图像生成/编辑 Prompt。当用户需要生成图片、画图、做海报/封面/Banner/插画/产品图/电商图/UI/App截图/信息图/流程图/Logo/角色设定/换装/换背景/文字图/照片级真实图像，或需要编辑/合成/风格迁移/扩图时，必须使用本 Skill。也适用于讨论绘图策略。将模糊审美词（高级、电影感、真实）转译为具体视觉事实。
---

# GPT Image 2 Prompt Writer

## Purpose

当用户需要生成、编辑、改造、合成、重绘、扩图、制作海报、产品图、UI 图、信息图、角色图、封面、广告图、社交媒体图、照片级真实图像或任何面向 GPT Image 2 的绘图 Prompt 时，必须调用本 Skill。

本 Skill 的目标不是「发挥想象写一段好看的描述」，而是把用户的自然语言需求转化为 **可执行、可控、低歧义** 的图像生成规格。

> **核心信条：** GPT Image 2 是视觉执行系统，不是聊天对象。Prompt 应描述输出画面本身，不是解释意图或抽象愿望。

---

## When to Use This Skill

当用户请求中出现以下意图时，**必须**使用：

- **生成类：** 生成图片、画图、做海报/封面/Banner/插画
- **产品/电商：** 产品图、电商图、白底图、包装图
- **UI/应用：** App 截图、网页设计、仪表盘 mockup
- **信息/教学：** 信息图、图表、流程图、教学图
- **品牌/角色：** Logo、人物设定、角色一致性、故事书
- **编辑类：** 换背景、换装、换天气/光线、去物体、草图→真实
- **文字类：** 图中需要精确中文/英文文字
- **合成类：** 多图参考、风格迁移、商品替换场景
- **讨论类：** 讨论绘图策略、分析 Prompt 好坏

---

## Core Model Understanding

GPT Image 2 的优势：
- 照片级真实感
- 图中文字渲染（中英文）
- 复杂版式/排版
- 产品摄影 / UI Mockup / 信息图
- 编辑保真
- 多图参考与角色一致性

常见限制：
- 复杂请求可能耗时较长
- 小字、密集文字、精确空间布局仍需高质量参数
- 多轮编辑可能发生漂移
- 过度宽泛的 Prompt 会让模型自行发挥

---

## Task Classification Router

写任何 Prompt 前，**先判断任务类型**，然后 **立即 READ 对应的 reference 文件**：

| 任务类型 | 核心原则 | Reference 文件 |
|---|---|---|
| Text-to-Image（从零生成） | 场景+主体+细节+用途+约束 | `references/task-types.md` → §Text-to-Image |
| Image Edit（修改图片） | Change / Preserve / Constraints | `references/task-types.md` → §Image Edit |
| Multi-Image（多图合成） | 给每张图编号+说明角色 | `references/task-types.md` → §Multi-Image |
| Text-in-Image（图中文字） | 精确文案+字体+位置+禁止额外文字 | `references/task-types.md` → §Text-in-Image |
| Photorealism（照片级真实） | 摄影媒介+镜头+光线+纹理+瑕疵 | `references/task-types.md` → §Photorealism |
| Product Photography（产品图） | 几何+材质+标签+光线+阴影 | `references/task-types.md` → §Product Photography |
| UI / Screenshot（界面截图） | 屏幕类型+层级+真实文案+组件布局 | `references/task-types.md` → §UI / Screenshot |
| Infographic（信息图） | 标题+结构+标签+箭头+阅读顺序 | `references/task-types.md` → §Infographic |
| Logo（标志设计） | 原创+简洁+可缩放+非侵权 | `references/task-types.md` → §Logo |
| Character Consistency（角色一致） | 建立角色锚点+重复关键外观 | `references/task-types.md` → §Character Consistency |
| Style Transfer（风格迁移） | 拆解风格元素（色彩/线条/材质/光效） | `references/task-types.md` → §Style Transfer |
| Drawing→Photoreal（草图→真实） | 草图是合同还是灵感 | `references/task-types.md` → §Drawing→Photoreal |

如需 **即用 Prompt 模板**，READ `references/ready-patterns.md`。
如需 **参数建议（size/quality）**，READ `references/parameter-guide.md`。
如需 **完整示例**，READ `references/examples.md`。

---

## Universal Principles（所有任务通用）

### 1. 永远把模糊审美翻译成视觉事实

以下词语 **只能辅助，不能作为 Prompt 主体**：

> 高级、好看、震撼、史诗、电影感、真实、专业、精致、漂亮、潮流、大片感、艺术感、极致、顶级、爆款

**翻译对照：**

| 模糊词 | 视觉事实 |
|---|---|
| 高级感 | 低饱和配色、留白充足、精细排版、柔和阴影、哑光材质、克制的无衬线字体、单一主视觉、无杂乱背景 |
| 电影感 | 宽画幅构图、低角度侧光、浅景深、暖冷对比光、空气透视、细微胶片颗粒、主体偏离中心、背景层次明显 |
| 真实 | 自然皮肤纹理、衣物褶皱、表面磨损、环境杂物、真实光源方向、合理阴影、普通相机视角、不做过度修饰 |
| 干净专业 | 白色或浅灰背景、清晰主体轮廓、柔和摄影棚灯光、细微接触阴影、无额外道具、无水印、无多余文字 |

### 2. 默认使用结构化 Prompt

简单请求用自然语言；复杂请求必须使用标签结构：

```text
Create [artifact type / visual medium].

Scene:
[环境、时间、地点、背景、空间关系、表面材质]

Subject:
[主体、身份、对象、产品、人物、动作、姿态]

Composition / Lighting / Style:
[根据任务类型补充对应字段]

Use case:
[这张图的用途]

Constraints:
[禁止项、保留项]
```

### 3. 中文任务的处理

中文任务可以用中文写 Prompt；如果调用环境更偏英语模型表现，也可以输出英文 Prompt。**结构必须清晰，语言不限制。**

---

## Agent Prompt Construction Workflow

每次写 Prompt 前，按以下流程执行：

1. **识别任务类型** → READ 对应 reference 文件
2. **提取必须要素**：主体、场景、风格、用途、尺寸、文字、参考图、禁止项
3. **翻译模糊审美**：把抽象描述转为具体视觉事实
4. **补默认值**：如果缺关键信息，不要过度追问，根据用途补合理默认值并在 Prompt 中明确
5. **处理文字**：如果有文字，单独列为 exact / verbatim（READ `references/task-types.md §Text-in-Image`）
6. **编辑任务**：必须写 Change / Preserve / Constraints（READ `references/task-types.md §Image Edit`）
7. **多图任务**：必须标注 Image 1 / Image 2 / Image 3 的角色（READ `references/task-types.md §Multi-Image`）
8. **输出最终 Prompt**：优先给「可直接复制使用」的版本
9. **附带建议参数**：size、quality（READ `references/parameter-guide.md`）
10. **不要混淆解释与 Prompt**：不要把推理、免责声明混入最终 Prompt

---

## Recommended Output Format

```text
Final GPT Image 2 Prompt:
[可直接复制的 Prompt]

Suggested settings:
size: [recommended size]
quality: [low / medium / high / auto]
```

多版本需求时，输出 3 个完整方向，每个必须可执行。

编辑任务时，优先输出编辑 Prompt，不要生成与参考图无关的新 Prompt。

---

## Common Mistakes to Avoid

- 只用形容词堆砌，不描述画面事实
- 编辑任务只改不保（没写 Preserve）
- 多图场景不标注各图角色
- 要求文字准确但不给具体文字、位置、字体
- 图中文字不加引号
- Logo 写「像某知名品牌」
- 产品图忽略标签保真和几何保真
- UI 图不提供真实文案
- 信息图塞太多小字且不设层级
- 多轮编辑时省略关键保留项

---

## Prompt Repair Rules

当生成不理想时，**不要全部重写**，进行单点修复：

| 问题 | 修复策略 |
|---|---|
| 文字错误 | 只修复文字渲染，保留其他一切不变 |
| 主体跑偏 | 恢复主体，保持风格/光线/构图不变 |
| 编辑影响不该变的地方 | 撤销非目标改动，只改目标 |
| 图太假 | 加自然瑕疵、真实阴影、普通环境细节 |
| 构图混乱 | 简化构图，一个主体+留白+干净背景 |
| 信息图不可读 | 加大文字、减少标签、加留白 |
