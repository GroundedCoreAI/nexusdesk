# 企业总工作台 · 逐组件还原表（ui-spec v2.0 §6.2）

> 基准：`docs/design/ui-spec.md` v2.0 × 企业工作台设计稿（1920 折算 1280 CSS px）
> 结论：骨架（Hero → 5 指标卡 → 中部三栏 1.9/.92/1 → 底部三栏 1.2/1/1.15 → 快捷 3×2）与稿子一致，**沿用**；
> 差异全部落在 2.2 皮肤选项 / 3.1 密度档 / 1.4 扩展档，本页声明 `cardSurface: shadow`、`iconStyle: solid`、`heroStyle: light`、`chartLegend: inline`、`density: compact`（已登记于 ui-spec 附录 A）。

| # | 组件 | 规范定义（章:值） | 稿子实测 / 原实现 | 处置 |
|---|---|---|---|---|
| 1 | Hero 高度 | 2.4 内容 + padding 推导 | 118px（badge 22 + 标题 22×1.3 + 副标 13×1.5 + 16×2 padding） | 沿用 |
| 2 | Hero 底色 | 2.2 `heroStyle` | 浅蓝 `--sk-guide-gradient` + 白 radial | 声明 `light`；radial 改 `color-mix(--sk-card 95%)` 消除字面 rgba |
| 3 | Hero 插画 | 2.4 右侧 + 渐隐遮罩 | `hero-city.svg` + mask `#000` | 沿用；mask 属 1.3 已批准遮罩例外（附录 B） |
| 4 | Hero 标题 | 1.4 档位 | compact 档 22px | 降档 `--sk-fs-display-sm`（已登记） |
| 5 | 指标卡 | 2.5 图标容器 + 文字块，高度推导 | 34px 实底图标 + `--sk-fs-h2` 数值 | 沿用；图标字号 17→`--sk-fs-title` |
| 6 | 指标图标 | 2.2 `iconStyle` | 实底语义色 + 白 glyph | 声明 `solid`；`#fff`×3 → `--sk-on-accent` |
| 7 | 卡片表面 | 2.2 `cardSurface` | 无描边 + `--sk-shadow-card` | 声明 `shadow`（原实现已符合） |
| 8 | 面板 padding | 3.1 compact + 1.5 刻度 | 13px → **12px**，11px → **12px** | 归并刻度 |
| 9 | 图表 | 2.7 固定像素高、图例 inline | svg 110px、图例右上 | 沿用（2.7 的 `height:100%` 禁令已满足） |
| 10 | 图表系列色 | 2.7 双系列规范 → 本页 4 系列 | 蓝/紫/橙/青 | 4 系列为页面扩展，色值全走令牌，登记附录 B |
| 11 | 环形 | 2.8 conic + 直径由密度档 | 78px（M 档）/ 92px（XL 档） | 沿用；删 1400 断点，M=78 XL=92 |
| 12 | 快捷入口 | 2.2 `iconStyle: solid` + tint 类 | Filled 图标 + `tint-*` 淡底 | 稿子为实底彩色块 → tint 类改实底：`solid` 构造 |
| 13 | 待办行 | 2.6 列结构页面声明 | 图标+标题+tag+time 单行 | 沿用；tag padding 1px→0 + height 18 |
| 14 | 禁用快捷卡 | 2.9 disabled `opacity:.45` | `opacity:1` 全彩 | **9.1 一次性例外（附录 B 已批准）**，不改全局值 |
| 15 | 断点 | 5.2 只允许 5 档 | `1400/1401` 成对规避值 | **删除**：默认=M 档(compact)，`min-width:1551` = XL 放大 |
| 16 | 裸字号 ×10 | 1.4 只允许令牌档 | 17/10/15/12/21/26/16/18/18/19px | 归并：→title/xs/body/sm/h2/value/h2/display-sm |
| 17 | 非刻度间距 | 1.5 集合 | 5/7/9/11/13/26/30/72px | 归并 4/6/8/12/24/28；占位页 72px 登记例外 |
| 18 | 字面色值 | 1.2.1 | `#fff`×3、`rgba(.95/.85)`、`#000`×2 | `--sk-on-accent` / `color-mix` / 遮罩保留（批准） |
| 19 | 元素选择器 | 7.2 | `h1/h2/b/small/em/strong/p` 直接限定 | 改类（`ep-hero-title` 等）；`ul/li/time/i` 色点为语义/装饰，登记保留 |
| 20 | 类前缀 | 7.1 | `ep-*` | 在附录 A 随页面登记，合法 |

## 迁移后机检预期（ui-spec 8.1）

- 字面色值：仅 `mask-image` 的 `#000` ×2（1.3 批准遮罩）
- 裸 px 字号：0
- 非刻度间距：0（72px 占位页例外登记）
- `!important`：0；断点：1551 / 1100 / 760 + reduced-motion
- 焦点环：`button / a / input` 已覆盖

## 遗留（不在本轮）

- `console-sidebar.css` 深色主题专项（独立皮肤 + `!important` ×11）→ ui-spec 9.2 后续轮次
- AI 助手头像 / hero 插画精细度：素材级差异，还原度已确认，不阻塞
