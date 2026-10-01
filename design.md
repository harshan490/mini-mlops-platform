# Mini MLOps --- Spatial Dashboard Design Specification

## 1. Design Goal

Recreate the provided Mini MLOps dashboard as closely as possible.

The visual language is:

-   Premium futuristic MLOps command center
-   Dark spatial / sci-fi interface
-   Minimal glassmorphism
-   Deep navy-to-black environment
-   Large cinematic mountain/lake background
-   Electric blue, violet, cyan, teal, and restrained orange accents
-   Thin luminous borders
-   Soft atmospheric bloom
-   High information density without looking cluttered
-   Desktop-first 16:9 composition
-   One primary dashboard page; secondary functionality should live
    behind the left navigation/menu

The reference composition should be treated as the visual source of
truth.

------------------------------------------------------------------------

# 2. Canvas / Layout

## Target viewport

Primary design target:

-   Width: 1664px
-   Height: 936px
-   Aspect ratio: 16:9
-   Desktop application / web dashboard
-   Responsive down to approximately 1280px wide

Use a fluid layout, but preserve the relative proportions of the
reference.

## Global page structure

``` text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Top Header / Brand                                      Date / Search / Bell │
├──────┬───────────────────────────────────────────────────────────────────────┤
│      │                                                                       │
│      │   Hero / Welcome Area + Floating KPI Cards                           │
│ Side │                                                                       │
│ Nav  │   Active Pipeline                                                     │
│      │                                                                       │
│      ├───────────────────────────────────────────────────────────────────────┤
│      │ Model Performance │ Recent Experiments │ System Health               │
│      │                   │                    │                              │
└──────┴───────────────────────────────────────────────────────────────────────┘
```

The left sidebar is approximately 102px wide in the reference.

Main content begins after the sidebar.

------------------------------------------------------------------------

# 3. Background

## Visual direction

Use a cinematic futuristic landscape:

-   Dark mountain range in the center
-   Large planetary / celestial arc partially visible in the upper
    center-left
-   Dark lake or reflective surface in lower center
-   Purple-blue atmospheric lighting
-   Subtle orange/pink horizon light toward the right
-   Thin luminous orbital/data lines around the mountains
-   Very subtle fog
-   Very subtle stars / particles
-   No busy decorative UI behind content

The background must feel like a physical environment rather than a flat
gradient.

## Background layering

Recommended layer stack:

``` text
Layer 1: #020711 / near-black base
Layer 2: cinematic mountain landscape
Layer 3: dark blue atmospheric fog
Layer 4: purple/cyan ambient bloom
Layer 5: subtle orbital light trails
Layer 6: black/blue gradient overlays
Layer 7: glass dashboard cards
Layer 8: UI text/icons
```

## Background treatment

Apply:

-   `background-size: cover`
-   `background-position: center`
-   dark navy overlay around 20--35%
-   stronger darkening behind text/cards
-   mild blur only if required to preserve readability
-   do not completely obscure the mountain image

The image should remain visible through transparent glass cards.

------------------------------------------------------------------------

# 4. Color System

## Core colors

``` css
--bg-0: #020711;
--bg-1: #06101f;
--bg-2: #0a1830;

--surface-glass: rgba(7, 19, 39, 0.58);
--surface-glass-strong: rgba(5, 15, 31, 0.78);

--border-glass: rgba(115, 177, 255, 0.28);
--border-bright: rgba(93, 170, 255, 0.65);

--text-primary: #f3f7ff;
--text-secondary: #aabbd7;
--text-muted: #657895;

--blue: #3185ff;
--cyan: #48d7ff;
--violet: #8b6cff;
--purple: #a66cff;
--teal: #36e0c1;
--green: #2ee6a6;
--orange: #ff9d4d;
--red: #ff5477;
```

## Glow colors

Use glows sparingly:

``` css
blue glow:
rgba(49, 133, 255, 0.35)

cyan glow:
rgba(72, 215, 255, 0.30)

violet glow:
rgba(139, 108, 255, 0.30)

teal glow:
rgba(54, 224, 193, 0.25)
```

Avoid neon overload.

------------------------------------------------------------------------

# 5. Typography

Use a modern geometric/sci-fi-friendly sans-serif.

Preferred:

1.  Inter
2.  Geist Sans
3.  Manrope
4.  Space Grotesk for selected display text

## Typography hierarchy

### Brand

``` text
Mini MLOps
font-size: 20px
font-weight: 600
letter-spacing: -0.02em
```

### Welcome eyebrow

``` text
WELCOME BACK
font-size: 10–11px
font-weight: 500
letter-spacing: 0.42em
text-transform: uppercase
color: #9fb4d4
```

### Main greeting

``` text
Harshan
font-size: 64–72px
font-weight: 300–400
letter-spacing: -0.045em
color: #f5f8ff
```

### Subtitle

``` text
Build. Train. Deploy. Monitor.
font-size: 19px
font-weight: 400
color: #c1cee4
```

### Supporting text

``` text
font-size: 13–14px
color: #7890b2
```

### Card titles

``` text
font-size: 16–18px
font-weight: 600
color: #eaf1ff
```

### KPI numbers

``` text
font-size: 25–31px
font-weight: 500
color: #f4f8ff
```

------------------------------------------------------------------------

# 6. Sidebar

## Dimensions

``` text
Width: ~102px
Height: 100vh
```

The sidebar is vertically separated from the main page using a very
subtle border.

``` css
border-right: 1px solid rgba(89, 143, 208, 0.16);
background: rgba(2, 8, 18, 0.25);
backdrop-filter: blur(14px);
```

## Brand

Top-left:

-   abstract triangular Mini MLOps logo
-   electric blue gradient
-   logo approximately 43×43px
-   label `Mini MLOps`
-   label sits horizontally to the right of the logo
-   brand block is slightly inset from the page edge

## Navigation icons

Place vertically:

1.  Home
2.  Datasets
3.  Experiments
4.  Models
5.  Deployments
6.  Monitoring
7.  Pipelines
8.  Settings

Icons should be line icons with approximately 20--23px visual size.

Use Lucide / Phosphor / custom SVG icons.

## Active item

The Home icon sits inside a rounded rectangular glass button.

Approximate:

``` text
width: 54px
height: 54px
border-radius: 13px
background: rgba(28, 79, 151, 0.30)
border: 1px solid rgba(66, 156, 255, 0.85)
box-shadow:
  0 0 18px rgba(49, 133, 255, 0.28),
  inset 0 0 18px rgba(49, 133, 255, 0.10)
```

The icon is bright blue-white.

## Bottom avatar

Bottom-left:

-   circular glass orb/avatar
-   approximately 44px
-   blue/violet planetary appearance
-   tiny chevron beside it
-   fixed near bottom

------------------------------------------------------------------------

# 7. Header

The header is visually integrated with the hero rather than appearing as
a separate opaque bar.

## Right side

Elements:

``` text
Date
Time
Search
Notifications
Profile / Orb
```

### Date

Example:

``` text
Sat, 26 Sep 2026
```

Small muted white-blue text.

### Time

``` text
08:24 PM
```

Slightly brighter and larger.

### Search

Rounded square glass button:

``` text
48 × 48px
border-radius: 14px
```

Search icon centered.

### Notification

Same dimensions.

Bell icon with tiny red/pink notification dot.

### Profile orb

Circular futuristic glowing avatar / planet.

Approximately 50px.

------------------------------------------------------------------------

# 8. Hero / Welcome Section

Main hero starts approximately 220px from the left edge of the full
page, accounting for sidebar.

## Left content

``` text
WELCOME BACK

Harshan

Build. Train. Deploy. Monitor.

Your complete MLOps workspace in one place.
```

Below this is the global command/search input.

## Search / command bar

Approximate width:

``` text
370px
height: 52px
```

Rounded pill:

``` css
border-radius: 28px;
background: rgba(7, 21, 43, 0.60);
border: 1px solid rgba(62, 143, 255, 0.70);
box-shadow: 0 0 20px rgba(49, 133, 255, 0.10);
backdrop-filter: blur(16px);
```

Left icon:

-   sparkle / AI icon
-   bright blue-white

Placeholder:

``` text
Ask or search anything...
```

Right:

-   circular arrow button
-   subtle blue background

------------------------------------------------------------------------

# 9. Floating KPI Cards

Four floating cards sit over the mountain scene.

Cards:

1.  Datasets
2.  Experiments
3.  Models
4.  Deployments

They are connected visually to the mountain scene using vertical glowing
lines and a subtle orbital ring.

## Card dimensions

Approximately:

``` text
150–180px wide
88–105px tall
```

## Card style

``` css
background: rgba(11, 29, 55, 0.58);
border: 1px solid rgba(110, 173, 255, 0.55);
border-radius: 15px;
backdrop-filter: blur(18px);
box-shadow:
  0 12px 35px rgba(0,0,0,0.25),
  inset 0 0 25px rgba(75,130,255,0.05);
```

## Card contents

Left icon in a small glowing rounded square.

Example:

``` text
[ database ]   Datasets
                12    ↑ +3
```

KPI number is larger.

Change indicator:

``` text
↑ +3
```

Use green/cyan.

## Individual accent

Datasets: - blue

Experiments: - violet

Models: - teal

Deployments: - orange

------------------------------------------------------------------------

# 10. Orbital Data Visualization

Behind/under the KPI cards:

Create a thin glowing elliptical path around the mountain.

Visual behavior:

-   perspective ellipse
-   electric blue/cyan/violet gradient
-   1--2px line
-   soft glow
-   several bright points where cards connect
-   vertical light beams connect KPI cards to the orbital path

The orbital line should feel like an ML data-flow visualization.

Example conceptual structure:

``` text
             [ Experiments ]
                   │
                   │
        [Datasets] │       [Models]
             \     │      /
              \    │     /
               ╲   │    ╱
                ╲  │   ╱
        ────────────────
       /                  \
      /     MOUNTAINS      \
     /______________________\
                         │
                  [Deployments]
```

Keep this elegant and subtle.

------------------------------------------------------------------------

# 11. Active Pipeline Card

Position:

-   lower-left of hero
-   overlaps the background scene
-   above the bottom analytics row

Approximate dimensions:

``` text
440 × 195px
```

## Header

``` text
Active Pipeline                         >
```

## Pipeline status

``` text
●  exp-26     LSTM     • Training
```

Green status dot.

## Progress bar

``` text
██████████████░░░░░░ 68%
```

Use a cyan/blue gradient.

## Metrics

Three columns:

``` text
Epoch       Loss       ETA
68 / 100    0.312      12m
```

Muted labels with brighter values.

## Card style

Same glass system, slightly stronger opacity than KPI cards.

------------------------------------------------------------------------

# 12. Bottom Analytics Row

Three large cards occupy the lower section.

``` text
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Model Performance│ │Recent Experiments│ │  System Health   │
│                  │ │                  │ │                  │
│     chart        │ │ experiment list  │ │ CPU RAM GPU      │
│                  │ │                  │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

Use approximately:

``` text
Left:  31%
Center: 31%
Right:  38%
```

with consistent 18--22px gaps.

------------------------------------------------------------------------

# 13. Model Performance Card

## Header

``` text
Model Performance                       [ Accuracy ▼ ]
```

## Chart

Dark transparent plotting area.

Chart contains four smooth lines:

-   Random Forest --- blue
-   XGBoost --- violet
-   LSTM --- green/teal
-   BERT --- orange

The lines should be smooth rather than jagged.

Use:

-   thin 1.5--2px strokes
-   subtle glow
-   very low-opacity grid
-   no heavy chart borders

Y axis:

``` text
1.0
0.5
0.0
```

X axis:

``` text
0
10
20
30
40
50
```

## Highlight

At approximately x=35--38:

-   vertical guide line
-   highlighted point
-   floating tooltip

Tooltip:

``` text
0.892
```

Small rounded dark glass rectangle.

## Legend

Bottom:

``` text
● Random Forest
● XGBoost
● LSTM
● BERT
```

Use the line colors as dots.

------------------------------------------------------------------------

# 14. Recent Experiments Card

## Header

``` text
Recent Experiments                  [ View All → ]
```

## List

Rows:

``` text
● exp-28     Random Forest       0.914      2h ago
● exp-27     XGBoost             0.892      5h ago
● exp-26     LSTM                0.861      1d ago
● exp-25     BERT                0.928      2d ago
● exp-24     YOLOv8              0.901      2d ago
```

Each row:

-   7--9px status dot
-   experiment ID
-   model name
-   metric
-   timestamp

Rows separated by ultra-subtle horizontal lines.

The metric is right-aligned.

------------------------------------------------------------------------

# 15. System Health Card

## Header

``` text
System Health                         [ Last 24 hours ▼ ]
```

Three circular gauges:

``` text
CPU          RAM          GPU
42%          68%          35%
```

## Circular gauge

Use SVG / CSS conic-gradient.

Outer ring:

-   dark navy
-   1px subtle border

Progress:

-   CPU: blue
-   RAM: violet
-   GPU: teal

Center:

``` text
42%
```

Large white text.

Label:

``` text
CPU
```

above number.

## Mini charts

Under each circular gauge:

-   tiny area/sparkline chart
-   100px × 35px approximately
-   transparent background
-   smooth waveform
-   matching accent color
-   subtle glow

------------------------------------------------------------------------

# 16. Glassmorphism System

Every major UI surface must follow a shared glass system.

## Base glass

``` css
.glass {
  background:
    linear-gradient(
      135deg,
      rgba(20, 43, 77, 0.60),
      rgba(5, 15, 32, 0.54)
    );

  border:
    1px solid rgba(113, 171, 239, 0.26);

  backdrop-filter:
    blur(18px) saturate(125%);

  -webkit-backdrop-filter:
    blur(18px) saturate(125%);

  box-shadow:
    0 18px 45px rgba(0,0,0,0.25),
    inset 0 1px 0 rgba(255,255,255,0.06);
}
```

## Hover

On interactive cards:

``` css
transform: translateY(-2px);
border-color: rgba(104, 178, 255, 0.50);
box-shadow:
  0 18px 50px rgba(0,0,0,0.30),
  0 0 24px rgba(49,133,255,0.12);
```

Use 180--250ms easing.

------------------------------------------------------------------------

# 17. Border Language

Do not use thick white borders.

Preferred:

``` text
1px
low-opacity blue/white
soft outer glow
soft inner highlight
```

Cards should appear illuminated by the environment.

------------------------------------------------------------------------

# 18. Corner Radius

Use a consistent radius system:

``` text
small controls: 10–12px
buttons: 12–14px
cards: 18–20px
large panels: 20–24px
pills: 999px
```

------------------------------------------------------------------------

# 19. Shadows

Avoid traditional black web shadows.

Use atmospheric shadows:

``` css
box-shadow:
  0 20px 60px rgba(0, 0, 0, 0.35);
```

For illuminated objects:

``` css
filter:
  drop-shadow(0 0 12px rgba(50, 140, 255, 0.30));
```

------------------------------------------------------------------------

# 20. Micro-Animations

Animations should be slow, premium, and restrained.

## Background

-   slow atmospheric movement
-   subtle parallax
-   no constant aggressive motion

## Orbital path

-   slow light particle moving around the ellipse
-   5--10 second loop

## KPI cards

-   subtle floating motion
-   4--7 second loop
-   each card offset slightly

## Active pipeline

-   progress bar can animate when training is active
-   green status dot softly pulses

## System gauges

-   animate only when values change

## Hover

Cards lift by 2px.

Icons can brighten slightly.

------------------------------------------------------------------------

# 21. Spatial Depth

The UI should have three depth planes.

### Plane 1 --- Environment

Mountain landscape, lake, sky, atmospheric glow.

### Plane 2 --- Data visualization

Orbital paths, beams, KPI cards, floating information.

### Plane 3 --- Interface

Navigation, search, pipeline, analytics cards.

The environment should remain visible behind all three planes.

------------------------------------------------------------------------

# 22. Responsive Behavior

At width \> 1440px:

-   Full reference composition.

At 1280--1440px:

-   reduce hero typography
-   reduce KPI card spacing
-   reduce gaps between analytics cards

At 1024--1280px:

-   collapse sidebar labels
-   preserve icons
-   reduce background details
-   analytics cards may stack 2 + 1

At mobile:

-   do not attempt to preserve the desktop composition literally
-   convert sidebar to bottom/tab navigation
-   floating KPI cards become horizontal scroll cards
-   analytics become vertical cards
-   preserve the same glass/spatial visual language

------------------------------------------------------------------------

# 23. Component Architecture

Recommended component tree:

``` text
App
├── SpatialBackground
├── Sidebar
│   ├── Brand
│   ├── NavItem
│   ├── NavItem
│   ├── NavItem
│   └── UserOrb
│
├── Header
│   ├── DateTime
│   ├── SearchButton
│   ├── NotificationButton
│   └── ProfileOrb
│
├── Dashboard
│   ├── WelcomeHero
│   │   ├── Eyebrow
│   │   ├── Greeting
│   │   ├── Subtitle
│   │   └── CommandSearch
│   │
│   ├── SpatialMetrics
│   │   ├── DatasetCard
│   │   ├── ExperimentCard
│   │   ├── ModelCard
│   │   └── DeploymentCard
│   │
│   ├── OrbitalVisualization
│   ├── ActivePipelineCard
│   │
│   └── AnalyticsGrid
│       ├── ModelPerformanceCard
│       ├── RecentExperimentsCard
│       └── SystemHealthCard
```

------------------------------------------------------------------------

# 24. Suggested Technology

For a modern implementation:

``` text
Framework:
Next.js / React

Styling:
Tailwind CSS + CSS variables

Icons:
Lucide React

Charts:
Recharts or custom SVG

Animations:
Framer Motion

Background:
Optimized WebP/AVIF image

Effects:
CSS backdrop-filter
CSS gradients
SVG glow filters
```

Avoid excessive third-party UI libraries because the visual identity
depends on custom styling.

------------------------------------------------------------------------

# 25. Important Visual Rules

## DO

-   Keep the background dark.
-   Keep cards translucent.
-   Let the landscape remain visible.
-   Use blue/violet/cyan as the dominant light language.
-   Keep text crisp and bright.
-   Use subtle glow.
-   Use generous spacing.
-   Use thin borders.
-   Use smooth curves.
-   Make the dashboard feel like a spatial control system.

## DON'T

-   Do not use flat solid cards.
-   Do not use pure black cards.
-   Do not use white backgrounds.
-   Do not use excessive gradients inside every component.
-   Do not use thick borders.
-   Do not use excessive neon.
-   Do not make every element glow.
-   Do not overcrowd the screen.
-   Do not use generic SaaS dashboard styling.
-   Do not make charts look like default Chart.js/Recharts examples.

------------------------------------------------------------------------

# 26. Exact Visual Composition Reference

The final desktop dashboard should visually read in this order:

``` text
                         DATE       SEARCH  BELL  PROFILE
Mini MLOps
    │
    │              WELCOME BACK
    │
HOME                Harshan
    │               Build. Train. Deploy. Monitor.
DATASETS
    │               [ Ask or search anything... ]
EXPERIMENTS
    │
MODELS                       [Experiments]
    │                             │
DEPLOYMENTS              [Datasets]│[Models]
    │                          ╲   │   ╱
MONITORING                    ═══════════
    │                         MOUNTAINS
PIPELINES                       LAKE
    │
SETTINGS
    │
    │      ┌──── Active Pipeline ────┐
    │      │ exp-26 LSTM Training    │
    │      │ ███████████░░ 68%       │
    │      └─────────────────────────┘
    │
    │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐
    │  │ Model        │ │ Recent       │ │ System         │
    │  │ Performance  │ │ Experiments  │ │ Health         │
    │  │              │ │              │ │                │
    │  │    CHART     │ │    LIST      │ │ CPU RAM GPU    │
    │  │              │ │              │ │   RINGS        │
    │  └──────────────┘ └──────────────┘ └────────────────┘
```

This hierarchy is more important than individual pixel measurements.

------------------------------------------------------------------------

# 27. Data Model for Initial UI

Use realistic placeholder data.

``` js
const dashboardStats = {
  datasets: 12,
  datasetsChange: 3,

  experiments: 28,
  experimentsChange: 5,

  models: 6,
  modelsChange: 2,

  deployments: 3,
  deploymentsChange: 1
};

const activePipeline = {
  id: "exp-26",
  model: "LSTM",
  status: "Training",
  progress: 68,
  epoch: "68 / 100",
  loss: "0.312",
  eta: "12m"
};

const systemHealth = {
  cpu: 42,
  ram: 68,
  gpu: 35
};
```

Experiments:

``` js
[
  { id: "exp-28", model: "Random Forest", score: 0.914, age: "2h ago" },
  { id: "exp-27", model: "XGBoost", score: 0.892, age: "5h ago" },
  { id: "exp-26", model: "LSTM", score: 0.861, age: "1d ago" },
  { id: "exp-25", model: "BERT", score: 0.928, age: "2d ago" },
  { id: "exp-24", model: "YOLOv8", score: 0.901, age: "2d ago" }
]
```

------------------------------------------------------------------------

# 28. Accessibility

Despite the futuristic visual style:

-   maintain readable contrast
-   all icon-only buttons need accessible labels
-   keyboard navigation must work
-   focus states should use a subtle blue outline
-   animations should respect `prefers-reduced-motion`
-   charts should provide accessible text summaries

------------------------------------------------------------------------

# 29. Performance

Because the page contains a cinematic background:

-   use WebP/AVIF
-   lazy-load secondary imagery
-   avoid huge uncompressed PNG backgrounds
-   use CSS/SVG for orbital effects instead of video
-   keep animations GPU-friendly
-   animate `transform` and `opacity` rather than layout properties
-   avoid dozens of simultaneous blur filters
-   use `backdrop-filter` selectively

------------------------------------------------------------------------

# 30. Final Acceptance Checklist

The implementation is visually acceptable only when all of these are
true:

-   [ ] Full-screen cinematic mountain/lake environment
-   [ ] Dark navy spatial atmosphere
-   [ ] Left vertical navigation
-   [ ] Mini MLOps brand in top-left
-   [ ] Large `Harshan` welcome heading
-   [ ] `Build. Train. Deploy. Monitor.` subtitle
-   [ ] AI/search command bar
-   [ ] Four floating KPI cards
-   [ ] Orbital glowing data path
-   [ ] Vertical beams connecting KPI cards to visualization
-   [ ] Active Pipeline glass card
-   [ ] Three bottom analytics cards
-   [ ] Model Performance chart
-   [ ] Recent Experiments list
-   [ ] CPU/RAM/GPU circular gauges
-   [ ] Mini system health charts
-   [ ] Glassmorphism throughout
-   [ ] Thin luminous borders
-   [ ] Blue/violet/cyan accent language
-   [ ] Subtle bloom/glow
-   [ ] No generic SaaS appearance
-   [ ] No excessive neon
-   [ ] Desktop composition closely matches the supplied reference

------------------------------------------------------------------------

# 31. Reference Image

Use the supplied reference image as the primary visual reference during
implementation.

Reference file:

``` text
ChatGPT Image Sep 28, 2026, 08_37_20 PM.png
```

When implementing, compare screenshots against the reference at
approximately:

``` text
1664 × 936
```

Prioritize:

1.  Overall composition
2.  Background treatment
3.  Card placement
4.  Typography scale
5.  Glass transparency
6.  Lighting/glow
7.  Spacing
8.  Charts and data density
9.  Iconography
10. Micro-details
