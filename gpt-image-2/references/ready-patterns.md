---
name: Ready-to-Use Prompt Patterns
description: >-
  8 个即用型 Prompt 模板：通用高质量生成、照片级人像、产品图、精确文字海报、UI Mockup、图像编辑、多图合成、角色一致性。
---

# Ready-to-Use Prompt Patterns

> 从 SKILL.md 路由。需要即用模板时 READ 此文件。

---

## 1. 通用高质量生成

```text
Create a [visual medium] of [subject].

Scene:
[environment, time of day, background, surface materials.]

Subject:
[main subject, action, pose, scale, placement.]

Composition:
[framing, camera angle, subject position, negative space.]

Lighting:
[light source, direction, color temperature, shadow behavior.]

Style:
[specific visual style with concrete visual cues.]

Important details:
[textures, materials, colors, props, typography if any.]

Use case:
[intended use.]

Constraints:
No watermark, no extra text, no unrelated logos, no unnecessary objects. Keep the image clean, coherent, and visually readable.
```

---

## 2. 照片级真实人像

```text
Create a photorealistic candid portrait of [person/subject] in [environment].

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

Constraints:
No heavy retouching, no plastic skin, no glamorization, no watermark, no extra text.
```

---

## 3. 产品图

```text
Create a professional product photograph of [product].

Scene:
[background and surface.]

Product:
[shape, color, material, label text if any, visible features.]

Composition:
[centered / 45-degree angle / top-down / hero shot], generous padding, clean silhouette.

Lighting:
[studio softbox / window light], realistic highlights, soft contact shadow.

Material fidelity:
[glass / metal / ceramic / fabric / paper / liquid qualities.]

Use case:
[e-commerce listing / landing page hero / social ad.]

Constraints:
Preserve product geometry and label legibility. No extra logos, no watermark, no unrelated props, no distorted text.
```

---

## 4. 精确文字海报

```text
Create a [poster type] for [topic/brand/event].

Visual concept:
[main visual idea.]

Layout:
[vertical / horizontal], [where headline, subject, subtitle, CTA go.]

Headline (EXACT TEXT, verbatim):
"[headline]"

Subtitle (EXACT TEXT, verbatim):
"[subtitle]"

Typography:
[font style, weight, color, alignment, spacing.]

Color and style:
[palette and design language.]

Constraints:
Render all text exactly once and perfectly legibly. No extra words, no duplicate text, no garbled characters, no watermark, no unrelated logos.
```

---

## 5. UI Mockup

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

## 6. 图像编辑

```text
Change:
[exact change.]

Preserve:
[face, identity, pose, body shape, hands, background, camera angle, framing, lighting, product geometry, label text, layout].

Integration:
Match the original image's lighting, shadows, perspective, scale, color temperature, texture, and image quality.

Constraints:
Change only [target]. Keep everything else exactly the same. No extra objects, no watermark, no text changes unless explicitly requested.
```

---

## 7. 多图合成

```text
Image 1: [base scene / subject to preserve].
Image 2: [reference object / style / clothing / product].
Image 3: [additional reference].

Instruction:
[combine or apply specific elements.]

Preserve:
[what stays from Image 1.]

Match:
Lighting, shadows, perspective, scale, color temperature, material realism, and image quality.

Constraints:
No extra objects, no identity drift, no logo drift, no watermark, no unintended text changes.
```

---

## 8. 角色一致性

```text
Continue using the same character from the reference image.

Scene:
[new situation and action.]

Character consistency:
Keep the same face, hairstyle, body proportions, outfit, color palette, signature accessory, and personality.

Style consistency:
Keep the same illustration style, line quality, lighting, and rendering method.

Constraints:
Do not redesign the character. No extra characters unless requested. No text, no watermark.
```
