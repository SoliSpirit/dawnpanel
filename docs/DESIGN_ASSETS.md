# DawnPanel visual assets

Generated with the built-in image generation tool on 2026-10-21, then compressed to WebP for the site. Originals are retained in the ignored `private/artwork-originals/` folder. These are conceptual category illustrations, not official brand assets or screenshots.

Published assets: `static/artwork/hero.webp`, `ai.webp`, `social.webp`, `chatgpt.webp`, `gemini.webp`, `claude.webp`. Six images total about 245 KB, with dimensions declared in templates and below-the-fold images lazy loaded.

## Prompt set

### hero.webp
Use case: ads-marketing. Create an exquisite premium digital storefront hero artwork for DawnPanel, an established dark navy and mint Persian digital goods shop selling AI subscriptions and messaging growth services. Wide landscape composition about 3:2. A sculptural floating translucent mint glass four-point intelligence star above a polished graphite pedestal, with three small floating rounded glass tiles suggesting chat bubbles, creative image generation, and a tiny connected network. Elegant restrained luxury product photography rendered in 3D, tactile frosted glass, brushed dark metal, mint rim lighting with a small warm peach accent. Rich deep navy #0c1320 background, soft luminous atmosphere, carefully arranged tangible objects, high visual quality, art directed rather than busy cyberpunk. Main objects centered, generous space around edges so image can be cropped for responsive web. No text, no letters, no numbers, no logos, no watermarks. This is a website artwork, not a screenshot of a website.

### ai.webp
Use case: ads-marketing. Premium digital product category artwork for a dark navy and mint Persian online shop selling AI subscriptions. Landscape 3:2 artwork, a beautiful sculptural iridescent frosted glass intelligence star and rounded open dark notebook beside a glowing translucent chat bubble on a graphite studio surface. Mint green and soft lavender reflections, rich navy #0c1320 backdrop, warm cinematic softbox light, refined 3D product photography, minimal balanced composition, beautiful tactile materials and clear focal subject suitable for a wide store category card. No text, no letters, no numbers, no product logos, no watermark. Not a UI screenshot.

### social.webp
Use case: ads-marketing. Premium category artwork for a Persian digital storefront selling messaging services. Landscape 3:2 composition. Three charming polished glass chat bubbles, one mint, one orange peach and one sky blue, floating as a precise connected sculpture above a dark rounded pedestal, small subtle connection lines and reflective graphite surface. Deep midnight navy #0c1320 background. Luxurious refined contemporary 3D studio product render, soft luminous reflections, crisp crafted forms and tasteful shadows, lots of clean surrounding space. No text, no letters, no numbers, no real product logos, no watermarks. Not a website screenshot.

### chatgpt.webp, gemini.webp, claude.webp
Shared prompt: Use case: product-mockup. A premium landscape 3:2 digital subscription category cover for DawnPanel Persian online shop. Subject: [SUBJECT]. Beautiful tangible luxury 3D studio render on rich dark navy #0c1320 seamless background, softbox lighting, subtle floor reflections, very refined crafted glass and ceramic material, sophisticated restrained composition, single centered arrangement with generous space, crisp beautiful sculptural forms. Coordinated visual family for AI subscription store. This is conceptual category artwork, not an actual boxed product or official brand asset. No text, letters, numbers, logos or watermarks. Not a UI screenshot.

Subjects:
- ChatGPT: a floating emerald frosted glass sculptural interwoven knot with six smooth loops, a tiny clear chat bubble and an elegant dark graphite membership card
- Gemini: an iridescent blue-violet four pointed glass star with a small cyan glass prism and an elegant dark graphite membership card
- Claude: a warm terracotta peach sculptural radial sunburst with rounded tactile spokes, a cream glass chat bubble and an elegant dark graphite membership card


## Day-mode companion images

The built-in image generation editor created six separate day-mode companions, referencing the matching original image: `static/artwork/hero-light.webp`, `ai-light.webp`, `social-light.webp`, `chatgpt-light.webp`, `gemini-light.webp`, `claude-light.webp`. Original generated PNGs are retained in `private/artwork-originals/*-light.png`. Night images are preserved. Total optimized day image payload: 227540 bytes.

Shared edit prompt, applied once per matching reference:

Create a LIGHT DAY MODE counterpart of this existing DawnPanel storefront artwork. Preserve the exact main objects, their count, sculptural shapes, composition, relative positions, materials, camera angle, aspect ratio, framing and brand accent hues. Replace the dark navy environment and dark floor with a refined luminous ivory and pale mint daylight studio. Turn dark graphite pedestal/card elements into pearl white ceramic or pale champagne metal, keep cards blank. Use large soft natural daylight, gentle realistic shadows and beautiful clean glass reflections, retain the colored green/blue/orange/violet sculptural objects with enough saturation for contrast. If rocks are present, make them pale cream natural stone. Sophisticated bright premium ecommerce editorial render; readable objects, subtle depth, no blown highlights. This is a companion image for switching between day and night themes, not a redesign or a screenshot. No text, letters, numbers, additional objects, watermark or new logos.

## Graphite night redesign (2026-10-21)

User requested replacement of the night palette and matching separate photos throughout the store. Six night files in `static/artwork/{hero,ai,social,chatgpt,gemini,claude}.webp` were replaced with built-in image editor outputs. Day companions remain distinct. Optimized night assets total 208836 bytes; original PNG outputs retained privately as `private/artwork-originals/*-night-v2.png`.

Shared prompt, each referencing the corresponding previous night illustration:

Redesign this [NAME] commercial illustration as the NIGHT companion for a premium digital subscription store. Retain recognizable subject identity, but change the arrangement and lighting substantially for a new composition. Premium art-directed 3D product photography, soft neutral graphite charcoal background #202124, matte rounded architectural plinth, floating sculptural objects with satin pearlescent glass and brushed silver, subtle warm champagne rim light and restrained mint reflections. Calm luxurious editorial design, low glare, softly illuminated objects clearly legible, no neon, no navy blue backdrop, no rocky terrain, no water, no tiny busy particles. Hero: landscape 3:2 composition, sculptural pearl four point star left of center with small translucent chat and image tiles, negative space upper right. Other assets: landscape 3:2 composition, large central subject, spacious background, product catalog cover. No text, no letters, no watermark. Keep the subject colors characteristic of the source but muted and refined.

Merchant uploads now have separate day and night slots in product administration, both with the same validation and WebP conversion. A missing slot uses the category illustration for that theme, so a day photo does not leak into the night composition. Product schema, sitemap and social previews use the day image consistently. Logos remain unchanged brand marks in both themes.
