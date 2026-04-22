---
name: moomoo-topic-summary
version: 1.1.0
description: "抓取 moomoo 社区话题下所有参与帖子并生成中日双语分析总结报告。当用户提供 moomoo community discussion URL（如 https://www.moomoo.com/ja/community/discussion/xxx、/en/ /zh/ 等 locale 均支持）并想要分析话题讨论内容、生成帖子汇总、总结用户观点时使用。"
metadata:
  requires:
    bins: ["python"]
    python_packages: ["playwright"]
---

# moomoo 话题分析工作流

## 适用场景

- "帮我总结下这个 moomoo 话题下大家在聊什么：<URL>"
- "分析这个讨论帖 <URL>"
- "爬一下这个话题的所有参与内容"
- 凡是用户提供了 `https://www.moomoo.com/<locale>/community/discussion/...` 链接并想做内容分析的场景

## 前置条件

1. **Python 3.10+** 已安装
2. **Playwright + Chromium**：
   ```bash
   python -m pip install playwright
   python -m playwright install chromium
   ```
3. **登录态**：工作目录下存在 `state.json`（首次使用需运行 `login.py` 手动登录一次）

## 工作目录约定

为每个话题建一个独立工作目录，避免数据混淆：

```
<workspace>/moomoo-scraper/<slug>/
  state.json                  # 登录态（可复用同一份）
  output/
    api_responses.jsonl       # 原始 API dump
    dom_fids.json             # 页面 DOM 里能看到的全部 fid（列表 API 兜底用）
    details_raw/<fid>.json    # 详情页捕获的 API 响应（debug 用）
    feeds.json                # 解析后的结构化帖子
    feeds_preview.txt         # 人读预览
    images/<feed_id>/NN.ext   # 下载的帖子图片
    report.html               # 带图可浏览报告
    summary.html              # 分析总结报告（中日双语，核心交付物）
```

`<slug>` 从 URL 最后一段取，例如：
`.../discussion/demo-trading-contest-s-p500-challenge-is-here-share-your-2052587553` → `slug = s-p500-challenge`（任意短可读名即可）。

## 工作流

### 第 0 步：定位 skill scripts 目录

scripts 位于本 skill 旁边。在 bash/PowerShell 里用这个路径变量（根据用户家目录动态解析）：

- macOS / Linux: `~/.claude/skills/moomoo-topic-summary/scripts/`
- Windows: `C:\Users\<user>\.claude\skills\moomoo-topic-summary\scripts\` 或 `$HOME\.claude\skills\moomoo-topic-summary\scripts\`

后续命令里用 `<SCRIPTS_DIR>` 代指。

### 第 1 步：准备工作目录

```bash
mkdir -p <workspace>/moomoo-scraper/<slug>
cd <workspace>/moomoo-scraper/<slug>
```

### 第 2 步：确认登录态

```bash
# 检查 state.json 是否存在
ls state.json
```

如果不存在，**引导用户执行登录**（这是交互步骤，agent 不能代做）：

> 第一次用需要登录一次。请在 PowerShell/terminal 里运行：
> `python "<SCRIPTS_DIR>/login.py" ja`（或 `en` / `zh` 匹配目标 URL 的 locale）
> 浏览器打开后自己点 "Login" 登录，登录成功回到终端按回车。

**提示用户登录完成后告诉你继续**，然后再走下一步。

### 第 3 步：抓取列表

```bash
python "<SCRIPTS_DIR>/scrape.py" <URL>
```

会弹出浏览器自动滚动翻页，1-3 分钟。产物 `output/api_responses.jsonl`。

### 第 4 步：解析为 feeds.json

```bash
python "<SCRIPTS_DIR>/extract.py"
```

从 `api_responses.jsonl` 抽出帖子结构。

### 第 5 步：补齐被截断或缺失的详情

```bash
python "<SCRIPTS_DIR>/fetch_details.py"
```

此脚本**自动**判断哪些帖子需要访问详情页：
- `is_complete=False`（列表 API 显式标记截断）
- `word_count > 50` 且 body 长度 < word_count * 0.5（启发式判断）
- `/discussion/` URL 但 body 为空
- `from_dom_fallback=True`：`scrape.py` 从 DOM 里发现的 fid 但列表 API 没返回（通过 `dom_fids.json` 对比注入）

⚠️ 会跳过所有 `/feed/` URL ——那些是"某用户加入话题"系统事件，**本身就没有正文**。

每条帖子都会被标记 `body_source`：
- `list_api`：列表 API 直接给了完整 body
- `detail_api`：详情页 API 返回了完整 rich_text
- `detail_api_full`：DOM-fallback 贴在详情页 API 响应里找到了完整 feed 节点（连元数据一起回填）
- `dom_fallback`：详情页 API 没返回 feed 结构，从 DOM inner_text 里救回的正文（**仅日文 locale 下会附加 nick/timestamp/views**，见下方局限）
- `deleted`：详情页显示帖子已被删除
- `empty`：什么都没救回来
- `list_api_truncated`：列表 API 标记了 is_complete=False 但详情页也救不回完整版，保留截断文本

### DOM-fallback 的局限（重要）

部分帖子不出现在列表 API 响应里（moomoo 的分页/过滤行为），只能靠 DOM 扫描救回。这类帖子存在以下限制，**写 summary 时必须明确提及**：

1. **仅日文 locale（`/ja/`）支持元数据解析**：`fetch_details.py` 的 `parse_dom_post_jp()` 按日文页面布局（`<nick> がディスカッションに参加しました · <time>`、`免責事項：`、`N 回閲覧`）抽 nick/timestamp/views。EN/ZH locale 目前只能拿到正文文本，元数据字段为 null。
2. **无法恢复的字段**：`is_essence`（精华）、`is_popular`（热门）、图片列表（pictures）——这些靠详情页 API 获取，DOM-fallback 贴取不到。
3. **时间戳仅精确到分钟**：DOM 里时间显示是 `04/16 16:00` 或 `16:00` 格式，解析后转 JST epoch 但秒位填 0。
4. **正文清洗后覆盖 body_dom**：若 JP 解析成功，原始 `body_dom`（含导航/页脚）会被替换为干净正文，方便渲染。若解析失败（非日文或结构异常），`body_dom` 保留原始 DOM 文本。

### 第 6 步：下载帖子图片

```bash
python "<SCRIPTS_DIR>/download_images.py"
```

断点续下，把所有帖子里 `pictures[].original` 的原图存到 `output/images/<feed_id>/NN.<ext>`。

### 第 7 步：生成可浏览报告

```bash
python "<SCRIPTS_DIR>/build_report.py"
```

产物 `output/report.html`——图片内联在每条帖子下，浏览器双击打开。

### 第 8 步（核心）：生成**中日双语**分析总结 summary.html

**这一步由 agent 完成，不是运行脚本。**

#### 8.1 读取与计算

1. **读取 `output/feeds.json`**
2. **计算统计指标**：
   - 总 feed 数、有正文的条数、系统事件数（URL 含 `/feed/`）
   - 正文长度分布（推荐分桶：≤5 / 6-20 / 21-100 / >100 字）
   - 浏览量 min/median/p90/max
   - 发帖最多的用户 top 10
   - 带图片帖子数
   - 各 `body_source` 的计数（特别是 `dom_fallback` 占比——影响数据品质说明）
3. **读取内容并识别主题**：
   - 按字数降序取前 10 条长帖，通读正文
   - 按浏览量降序取前 15 条，分析曝光 vs 质量错配
   - 关键词扫描（根据话题自选词表：股票代码、公司名、事件名等）

#### 8.2 双语 summary.html 结构要求

**单个 HTML 文件，包含两个完整语言版本**，顺序 **日本語 → 中文**（日文在前，中文在后），顶部放语言切换锚点。两版内容必须对等（不是一版详细一版简略），但各自用目标语言的自然表达——不是机翻。

必需章节（两种语言各一份）：
- TL;DR（结论一句话）
- 数据总览表（含各 `body_source` 分布）
- 正文品质分布（附用户发帖动机分析）
- 主要话题与观点（附原文引用 blockquote；**原文不翻译，保留日文原样**，两版共用同一 blockquote，只是外层解说语言不同）
- 高频关键词
- 头部用户（Top 5）
- 浏览量 vs 品质错配分析
- 推荐阅读 Top 5（按信息密度排序）
- 其他观察（社区文化、活动设计反馈等）
- **数据品质注记**：若存在 `dom_fallback` 贴，必须说明其缺 `is_essence`/`is_popular`/图片元数据，以及非日文 locale 下连 nick/timestamp/views 也缺。

#### 8.3 HTML 样式约定

- 参考 `output/report.html` 的字体/配色，让两个报告视觉一致。
- 顶部放两个语言锚：`<a href="#jp">日本語</a> | <a href="#cn">中文</a>`。
- 两个语言区分别用 `<section id="jp" lang="ja">` 与 `<section id="cn" lang="zh-CN">` 包裹，方便屏幕阅读器和未来拆分。
- 日文区字体栈优先 `"Hiragino Sans", "Yu Gothic UI", sans-serif`；中文区优先 `"PingFang SC", "Microsoft YaHei", sans-serif`。

## 关键坑位（必须注意）

### 1. Windows 控制台中文/日文乱码

Python 脚本的 `print` 在 Windows GBK 控制台会报 `UnicodeEncodeError`。两种方式：
- 设环境变量：`set PYTHONIOENCODING=utf-8`（PowerShell: `$env:PYTHONIOENCODING='utf-8'`）
- 或用 `type` 查看输出文件内容

### 2. 不要用 `wait_until="networkidle"`

moomoo 页面有无限的 analytics/tracking 请求，`networkidle` 永远触发不了。统一用 `domcontentloaded` + 固定 `wait_for_timeout`。

### 3. `/feed/` vs `/discussion/` URL 区别

- `/community/discussion/<slug>-<feed_id>` → **真实帖子**，有正文
- `/community/feed/<feed_id>` → **系统事件**（"某某加入了话题"），无正文
- 统计和分析时必须区分这两类

### 4. 图片字段路径

帖子图片在 `summary.picture_items[].org_pic.url`，**不是** `picture_items[].url`。每张图有 `org_pic/big_pic/mid_pic/small_pic/thumb_pic` 多种尺寸，下载用 `org_pic`（原图）。

### 5. 被作者删除的帖子

详情页会显示 `削除されています` / `已删除` / `This post has been deleted` / `This content is no longer available` 等字样时，`fetch_details.py` 会把 `body_source` 标记为 `deleted`。标识词都是**完整短语**，不是裸词——早期版本用过 `"deleted"` 单词导致页脚命中误报，已收紧。

### 6. 登录态可能过期

如果 `scrape.py` 抓不到任何 `get-feed-list` 响应（API_DUMP 里只有 config/tracker 接口），极可能是 cookie 过期，让用户重跑 `login.py`。

## 输出示例路径

```
output/
  feeds.json              # 结构化数据
  report.html             # 可浏览报告（图片内联）
  summary.html            # 分析总结（核心交付物）
  images/                 # 原图
```

最后把 `report.html` 和 `summary.html` 的绝对路径告知用户，双击即可在浏览器查看。
