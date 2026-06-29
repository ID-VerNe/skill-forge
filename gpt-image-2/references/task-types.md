---
name: Task-Type Templates
description: >-
  包含所有 12 类 GPT Image 2 任务的 Prompt 模板和规则。SKILL.md 的路由表指向这里。
  由 SKILL.md 的 Task Classification Router 按需读取。
---

# Task Type Templates

> 由 SKILL.md 路由按需读取。每个 § 是一个独立的任务类型模板集。

---

## § Text-to-Image

### Template

```text
Create a [visual medium / artifact type] of [core subject].

Scene:
[环境、时间、地点、背景、空间关系、表面材质。]

Subject:
[主体是谁/是什么，正在做什么，大小、姿态、位置、朝向。]

Composition:
[镜头距离、视角、构图、主体位置、留白、前景/中景/背景。]

Lighting:
[光源类型、方向、强度、色温、阴影效果。]

Style and visual language:
[摄影/插画/3D/矢量/水彩/写实/品牌风格等，必须具体。]

Important details:
[材质、纹理、颜色、服装、道具、环境瑕疵、文字、排版。]

Use case:
[这张图用于什么：广告、封面、电商、社媒、演示、教学、UI 原型等。]

Constraints:
[禁止项、必须保留项、文字准确性、无水印、无多余文字、无额外 logo。]
```

**原则：** 根据用户场景删减不必要字段，但不得省略「主体、构图、光线、约束」四类关键信息。

---

## § Image Edit

### 核心结构：Change / Preserve / Constraints

编辑 Prompt 的重点是 **防止模型重绘整张图**。

```text
Change:
[只描述需要改变的内容，越具体越好。]

Preserve:
[明确列出必须保持不变的内容：人物身份、脸、发型、肤色、体型、姿势、手部、背景、相机角度、构图、光线、产品几何、标签文字、品牌元素、布局等。]

Integration:
[要求新元素与原图的光线、阴影、透视、比例、材质、色温自然融合。]

Constraints:
[不要添加额外物体，不要改变未提及区域，不要改变文字，不要改变 logo，不要水印，不要重复文字。]
```

**关键：** 使用 "change only X" 和 "keep everything else exactly the same"。每一轮编辑都要重复关键保留项，不要假设模型会记住上一轮。

---

## § Multi-Image

### 核心结构：给每张图编号 + 说明用途

不要让模型猜哪张图是主体、风格、服装或背景。

```text
Image 1: [base image / main subject / scene to preserve].
Image 2: [style reference / product reference / clothing reference / background reference].
Image 3: [additional reference and its role].

Instruction:
[具体说明如何组合：把 Image 2 的什么元素应用到 Image 1，或把 Image 3 的什么对象放入 Image 1。]

Preserve:
[从基准图中必须保持不变的部分。]

Match:
[要求匹配光线、阴影、透视、比例、色温、材质、清晰度。]

Constraints:
[禁止添加、禁止重绘、禁止改变文字、禁止改变身份、禁止水印。]
```

### Example

```text
Image 1: base portrait to preserve.
Image 2: jacket reference.
Image 3: boots reference.

Dress the person from Image 1 using the jacket from Image 2 and the boots from Image 3.
Preserve the face, identity, body shape, pose, hair, expression, hands, background, camera angle, framing, and lighting from Image 1 exactly.
Fit the garments naturally with realistic folds, drape, occlusion, and contact shadows.
No extra accessories, no logos, no text, no watermark.
```

---

## § Text-in-Image

GPT Image 2 的文字渲染能力较强，但 Agent 仍必须把文字当成「排版任务」来写。

### Rules

1. 所有必须准确出现的文字，用**双引号**包裹
2. 对广告语、标题、按钮文案、包装标签，使用 `EXACT TEXT` 或 `verbatim`
3. 指定文字出现位置：顶部居中、左半区、按钮内、包装正面、海报底部等
4. 指定字体风格：bold sans-serif、condensed serif、handwritten script、宋体风格、现代无衬线等
5. 指定文字出现次数：once only / exactly once
6. 添加禁止项：no extra words, no duplicate text, no garbled text, no watermark
7. 对密集文字、细小文字、信息图、UI 屏幕，建议使用 `quality: high`

### Template

```text
Text requirements:
Render the following text exactly, verbatim, with no extra characters:
"[exact text]"

Typography:
[字体风格、字号感、粗细、颜色、对齐、字距。]

Placement:
[文字位于哪里，与主体的空间关系。]

Constraints:
The text must appear exactly once, be perfectly legible, and contain no extra words, no duplicate text, no distorted characters, and no watermark.
```

### Chinese Text Example

```text
Create a premium vertical poster for a tea brand.

Main headline (EXACT TEXT, verbatim):
"一盏春山"

Subtitle (EXACT TEXT, verbatim):
"明前绿茶 · 清香回甘"

Typography:
Elegant modern Chinese serif style, dark forest green, generous spacing, high contrast against a warm ivory background.

Placement:
Headline centered in the upper third, subtitle directly below it, tea product centered in the lower half.

Constraints:
Render all Chinese text exactly once and perfectly legibly. No extra words, no duplicate text, no watermark, no unrelated logos.
```

---

## § Photorealism

当用户要「真实照片」「像手机拍的」「像摄影作品」时。

### Required Elements

**摄影媒介：** documentary photograph、editorial photo、product photography、candid phone photo、studio portrait

**镜头与构图：** close-up、medium shot、wide shot、eye-level、top-down、low angle、50mm feel、35mm documentary feel

**光线：** soft window light from camera left、overcast daylight、golden hour low sun、fluorescent kitchen light、mixed warm and cool light、studio softbox

**真实纹理：** pores、wrinkles、fabric folds、scratched metal、wet pavement、dust、fingerprints、worn edges、uneven surface

**普通环境细节：** 背景中自然存在的物件、轻微杂乱、合理瑕疵

**禁止过度修饰：** no heavy retouching、no plastic skin、no over-stylized cinematic grading、no glamorization

### Template

```text
Create a photorealistic candid documentary photograph of [subject].

Scene:
[realistic location with ordinary details.]

Subject:
[age range, clothing, expression, pose, gaze, action.]

Composition:
[close-up / medium shot / full body], eye-level, [lens feel], natural framing.

Lighting:
[specific light source and direction], realistic shadows, natural color balance.

Details:
Real skin texture, natural hair, fabric folds, subtle imperfections, believable background objects.

Mood:
[grounded emotional tone, not exaggerated.]

Use case:
Editorial magazine photograph / candid documentary photo.

Constraints:
No heavy retouching, no plastic skin, no glamorization, no watermark, no extra text.
```

---

## § Product Photography

产品图的核心：**产品几何、材质、标签、光线、边缘、阴影和用途**。

### Template

```text
Create a professional product photograph of [product].

Scene:
[背景、台面、道具、环境。]

Product:
[产品形状、颜色、材质、标签文字、logo 或图案要求。]

Composition:
[居中、三分法、俯拍、45 度角、留白、展示角度。]

Lighting:
[摄影棚柔光、窗光、反射、高光、接触阴影。]

Material fidelity:
[玻璃、金属、塑料、纸盒、布料、液体、磨砂质感等。]

Use case:
[E-commerce hero image / Amazon-style product image / social media ad / catalog / landing page.]

Constraints:
Preserve product geometry, label legibility, and print sharpness. No extra logos, no watermark, no unrelated props.
```

### White-Background E-commerce Example

```text
Create a clean studio product photograph of a matte black ceramic coffee mug.

Scene:
Plain warm white opaque background.

Product:
The mug is centered, handle angled slightly to the right, matte ceramic surface with subtle texture.

Composition:
Three-quarter view, generous padding, product fills about 70 percent of the frame.

Lighting:
Large softbox from upper left, soft fill from the right, subtle realistic contact shadow below the mug.

Use case:
E-commerce product listing image.

Constraints:
Crisp silhouette, no halos, no extra objects, no text, no watermark, no logo, no background pattern.
```

---

## § UI / Screenshot

UI 图像不能写成「做一个好看的 App」。Agent 必须像产品经理 + UI 设计师一样定义界面结构。

### Required Elements

**屏幕类型：** mobile app screen、desktop dashboard、browser window、checkout page、settings page、onboarding screen

**产品名称：** 如果是虚构产品，明确说明 fictional app，避免真实品牌混入

**页面状态：** 登录页、空状态、已完成任务、报错状态、仪表盘有数据等

**真实文案：** 标题、按钮、标签、列表项、数值

**布局：** 顶部导航、卡片、列表、图表、底部栏、按钮位置

**视觉系统：** 背景色、主色、字体、圆角、间距、阴影、图标风格

### Template

```text
Create a realistic [mobile / desktop] UI screenshot for a fictional app called "[app name]".

Screen:
[page type and state.]

Content:
[exact titles, buttons, labels, list items, numbers.]

Layout:
[header, cards, navigation, chart, form, spacing.]

Visual design:
[background color, accent color, typography, radius, shadows, icon style.]

Use case:
Product design mockup.

Constraints:
All text must be legible. No real brand logos, no watermark, no placeholder gibberish, no extra UI elements.
```

---

## § Infographic

信息图最容易出错：文字太小、箭头混乱、层级不清。

### Required Elements

- **标题：** 精确文字
- **受众：** 小学生、高中生、管理层、客户、开发者等
- **结构：** 几栏、几步、时间线、流程、循环、矩阵、对比
- **必须出现的标签：** 列出关键术语
- **视觉语言：** 清晰白底、扁平图标、一致线条、足够留白
- **阅读顺序：** 从左到右、从上到下、中心向外等

### Template

```text
Create a clean educational infographic titled "[title]" for [audience].

Structure:
A [left-to-right / top-down / center-out] [process / timeline / comparison] with [N] main steps.

Required labels:
[label 1], [label 2], [label 3], ...

Visual style:
White background, flat friendly illustration, [color palette], clear arrows, consistent icon style, large readable labels.

Layout:
Title at the top, [diagram type] in the center, small summary box at the bottom.

Constraints:
All labels must be legible. Avoid tiny text, extra decoration, incorrect arrows, duplicate labels, watermark, or unrelated objects.
```

---

## § Logo

Logo 生成要强调 **原创、简洁、可缩放、非侵权、单一标志**。

```text
Create an original, non-infringing logo for [brand name], a [business type].

Brand personality:
[温暖、可靠、科技、自然、手工、未来感等。]

Visual direction:
[图形隐喻、几何形状、线条、负空间、图标与文字关系。]

Style:
Clean vector-like shapes, strong silhouette, balanced negative space, simple enough to read at small sizes.

Color:
[主色、辅助色、是否单色可用。]

Output:
A single centered logo on a plain background with generous padding.

Constraints:
Original design only, no trademarks, no real brand references, no watermark, no mockup scene, no complex illustration.
```

---

## § Character Consistency

### Role Anchor Template（第一张图 / 角色设定）

```text
Create a character reference image for an original [style] character.

Character:
[年龄、性格、体型、脸部特征、发型、服装、颜色、标志性道具。]

Style:
[儿童书水彩、日系赛璐璐、3D 玩具、像素风、写实电影概念等。]

Reference layout:
Front view, side view, three facial expressions, and one small pose vignette.

Constraints:
Original character only, no copyrighted characters, no text unless requested, no watermark.
```

### Extension Template（后续延展）

```text
Continue using the same character from the reference image.

Scene:
[新场景和动作。]

Character consistency:
Keep the same face, hairstyle, outfit, color palette, body proportions, signature accessory, and personality.

Style consistency:
Keep the same illustration style, line quality, lighting, and color treatment.

Constraints:
Do not redesign the character. No text, no watermark, no unrelated characters.
```

---

## § Style Transfer

不要只写「使用同样风格」。**必须拆解参考风格。**

### To Describe

- **色彩：** limited arcade palette、muted earth tones、pastel colors
- **线条：** soft outlines、thick black contour、clean vector edges
- **材质：** cold-pressed paper texture、film grain、pixelated blocks、oil paint impasto
- **构图：** centered icon, editorial negative space, poster layout
- **光效：** glow accents, soft diffuse light, dramatic rim light

### Template

```text
Use the visual language of the reference image: [色彩], [线条], [材质], [构图], [光效].

Generate a new scene of [new subject].

Preserve:
Only the style cues from the reference image, not the original subject.

Constraints:
White background, no watermark, no extra text, no real brand logos.
```

---

## § Drawing → Photoreal

草图是「合同」还是「灵感」？如果用户要保留结构，必须写 preserve exact layout。

```text
Turn this drawing into a photorealistic image.

Preserve:
The exact layout, proportions, perspective, horizon line, object placement, camera angle, and spatial relationships from the drawing.

Realism:
Choose realistic materials, lighting, textures, shadows, and environmental details consistent with the sketch.

Constraints:
Do not add new major objects, do not change the composition, do not add text, no watermark.
```
