---
name: Examples
description: >-
  4 个完整示例：小红书封面、产品图编辑、多图换装、原始用户对话对应的 Agent 输出。
---

# Examples

> 由 SKILL.md 路由。需要参考完整示例时 READ。

---

## Example 1: 小红书封面

**用户说：** "帮我做一张小红书封面，主题是 30 天早起计划，要有高级感，文字要清楚。"

**Final GPT Image 2 Prompt：**

```text
Create a premium vertical social media cover image for a "30-day early wake-up plan".

Layout:
Vertical poster composition, clean editorial design, generous negative space, central visual of a calm morning desk with a glass of water, a notebook, and soft sunlight.

Main headline (EXACT TEXT, verbatim):
"30天早起计划"

Subtitle (EXACT TEXT, verbatim):
"从混乱作息到清醒人生"

Typography:
Elegant modern Chinese sans-serif, dark navy text, strong hierarchy, headline large and centered in the upper third, subtitle smaller directly below.

Scene:
A quiet morning desk by a window, warm cream background, soft linen texture, subtle shadows, minimal props.

Lighting:
Soft golden morning window light from the left, gentle shadow on the desk, calm and clean atmosphere.

Color palette:
Warm ivory, muted beige, soft gold, dark navy accent.

Use case:
Xiaohongshu-style cover image, premium lifestyle productivity content.

Constraints:
Render all Chinese text exactly once and perfectly legibly. No extra words, no duplicate text, no watermark, no unrelated logos, no clutter.

Suggested settings:
size: 1024x1536
quality: high
format: png
```

---

## Example 2: 产品图编辑（换背景）

**用户说：** "把这张产品图的背景换成大理石浴室台面，产品不要变。"

**Final GPT Image 2 Prompt：**

```text
Change:
Replace only the background with a clean marble bathroom countertop next to a frosted glass window.

Preserve:
Keep the product exactly unchanged, including its geometry, proportions, cap shape, label text, label colors, print sharpness, logo placement, reflections, and product angle.

Integration:
Match the product naturally to the new scene with soft morning light diffused through the frosted glass, realistic contact shadow on the marble surface, and subtle reflections consistent with the original product lighting.

Constraints:
Do not restyle the product. Do not alter the label. Do not change product shape, color, angle, or text. No extra products, no extra logos, no watermark.
```

---

## Example 3: 多图换装

**用户说：** "图 1 是人像，图 2 是衣服，帮我换装，但脸和背景不变。"

**Final GPT Image 2 Prompt：**

```text
Image 1: base portrait to preserve.
Image 2: clothing reference to apply.

Instruction:
Dress the person from Image 1 using the clothing from Image 2.

Preserve:
Keep the person's face, identity, skin tone, body shape, hands, hairstyle, expression, pose, background, camera angle, framing, and lighting exactly the same as Image 1.

Integration:
Fit the clothing naturally to the existing body and pose, with realistic fabric folds, drape, occlusion, seams, and contact shadows. Match the original photo's lighting, color temperature, perspective, and image quality.

Constraints:
Replace only the clothing. Do not add jewelry, bags, logos, text, accessories, extra people, or watermark. Do not change the background or face.
```

---

## Example 4: 照片级真实人像

**用户说：** "帮我生成一张像国家地理杂志风格的老人做面包的照片。"

**Final GPT Image 2 Prompt：**

```text
Create a photorealistic candid documentary photograph of an elderly baker preparing dough before sunrise in a small neighborhood bakery.

Scene:
A narrow bakery kitchen with flour on the wooden counter, trays stacked in the background, and a slightly fogged window.

Subject:
The baker stands at the counter, hands pressing dough, wearing a faded white apron with flour marks.

Composition:
Medium close-up at eye level, 35mm documentary feel, hands and face both visible, background softly out of focus.

Lighting:
Warm overhead tungsten light mixed with cool early morning window light from camera left, soft shadows on the counter.

Important details:
Real skin texture, wrinkles, flour on fingers, worn wooden surface, metal trays with scratches, slight steam in the air.

Use case:
Editorial magazine photograph.

Constraints:
No glamorization, no heavy retouching, no watermark, no extra text, no staged commercial styling.
```
