# moomoo-topic-summary

[日本語](#日本語) | [中文](#中文)

---

<a id="日本語"></a>

## 日本語

moomoo コミュニティの話題（discussion）ページから全投稿を取得し、画像を保存して、閲覧用レポートと**日中バイリンガル分析サマリー**を生成します。

### 何ができるか

話題 URL（locale は `/ja/` `/en/` `/zh/` いずれも可）を agent に渡すと、以下を自動実行します。

1. 話題下の全投稿をスクロール取得（列表 API + DOM フォールバックの二重捕捉）
2. 切り詰められた長文や列表 API に載らない投稿を、詳細ページから補完
3. 投稿内の原寸画像をダウンロード
4. **閲覧可能な HTML レポート**（画像を各投稿直下にインライン表示）
5. **バイリンガル分析サマリー**（日本語 → 中文 の順で同一ファイルに収録）

### 初回セットアップ

#### 1. 配置場所

skill は Claude Code がデフォルトでスキャンするパス下に置きます。

- **ユーザー階層（推奨）**: `~/.claude/skills/moomoo-topic-summary/`
  - Windows: `C:\Users\<you>\.claude\skills\moomoo-topic-summary\`
- **プロジェクト階層**: `<repo>/.claude/skills/moomoo-topic-summary/`

ディレクトリ構成：

```
moomoo-topic-summary/
├── SKILL.md             # agent 用ワークフロー
├── README.md            # このファイル
└── scripts/
    ├── login.py         # 手動ログイン→ state.json 保存
    ├── scrape.py        # 自動スクロールで列表 API キャプチャ + DOM fid 記録
    ├── extract.py       # 構造化された feeds.json に整形
    ├── fetch_details.py # 切り詰めや DOM フォールバックを詳細ページで補完
    ├── download_images.py # 原寸画像ダウンロード
    └── build_report.py  # 閲覧用 HTML レポート生成
```

#### 2. Python 依存インストール

```bash
python -m pip install playwright
python -m playwright install chromium
```

Python 3.10+ が必要。

#### 3. skill が認識されているか確認

Claude Code で「利用可能な skill は？」と聞いて、`moomoo-topic-summary` が一覧に出ていれば OK。

### 使い方

#### 通常の使い方

URL を agent に渡すだけ：

> この moomoo の話題で何が話されているかまとめて：
> `https://www.moomoo.com/ja/community/discussion/xxx-xxx-2052587553`

agent がフローを全部走らせて、最後に `report.html`（閲覧用）と `summary.html`（バイリンガル分析）の絶対パスを返します。ダブルクリックでブラウザ表示。

#### 初回のみログインが必要

agent がターミナルで以下の実行を案内します：

```bash
python ~/.claude/skills/moomoo-topic-summary/scripts/login.py ja
```

（末尾の `ja` は URL の locale に合わせる：`en` / `zh` / `ja` ...）

ブラウザが立ち上がったら手動でログイン、完了後ターミナルで Enter を押せば `state.json` が保存されます。以降は同 locale の全話題で再利用可。切れたら再実行するだけ。

#### 作業ディレクトリ

各話題ごとに現在の作業ディレクトリ直下に独立した子ディレクトリを作ります（例：`moomoo-scraper/<話題slug>/`）。成果物は全てその `output/` 内に収まり、話題間で汚染しません。

### 成果物

```
output/
├── api_responses.jsonl   # 原始 API dump（debug 用）
├── dom_fids.json         # 画面 DOM に見えた全 fid（列表 API のフォールバック根拠）
├── details_raw/<fid>.json # 詳細ページで捕捉した API 応答（debug 用）
├── feeds.json            # 構造化投稿データ（コア中間成果物）
├── feeds_preview.txt     # 人間向けプレビュー
├── images/<feed_id>/*    # 各投稿の原寸画像
├── report.html           # 閲覧用レポート：全投稿＋インライン画像
└── summary.html          # **バイリンガル分析サマリー**（最終成果物）
```

### 既知の制限

1. **DOM フォールバック投稿の制限**：列表 API に載らず DOM テキストから救出した投稿には以下の欠落があります。
   - 画像メタデータなし（詳細ページ API に流れないため）
   - `is_essence`（精華）・`is_popular`（人気）フラグなし
   - **nick/timestamp/views の解析は現在日本語 locale のみ対応**（EN/ZH locale では正文のみ回収、メタデータは null）
2. **時刻精度**：DOM から拾った時刻は `04/16 16:00` のような分単位表示。秒位は 0 埋め、JST epoch に変換。
3. **削除判定の短語指定**：削除メッセージは locale 別の完全フレーズで判定（裸単語 `deleted` は UI チーム footer と誤衝突するため除外）。

### よくある質問

**Q: 取得が数件で止まる**
ログイン切れの可能性大。`login.py` を再実行して `state.json` を上書き。

**Q: Windows コンソールで文字化け**
`set PYTHONIOENCODING=utf-8`（PowerShell: `$env:PYTHONIOENCODING='utf-8'`）。

**Q: 長文の本文が冒頭数行しか取れない**
`fetch_details.py` が自動で補完します。手動トリガーしたい場合は話題の作業ディレクトリで再実行。

**Q: 分析サマリーは不要、閲覧用レポートだけ欲しい**
`build_report.py` までで停止。`summary.html` はその後 agent が `feeds.json` から別途生成する成果物。

**Q: 非日本語サイト対応は？**
URL は任意 locale 対応。ただし **DOM フォールバック投稿のメタデータ解析は現在日本語ページ専用**。EN/ZH ページでは DOM フォールバック投稿の nick/timestamp/views が null になります（正文は回収可）。

### 設計メモ

- **手動ログインを一度だけ行う理由**：moomoo の列表 API はログイン必須。自動ログインは reCAPTCHA リスクがあり、一度の手動ログイン → 長期再利用可能な `state.json` の方が安定。
- **`networkidle` を使わない理由**：moomoo は analytics/tracking 系の永続リクエストがあり `networkidle` は発火しない。`domcontentloaded` + 固定待機に統一。
- **`/feed/` vs `/discussion/`**：前者は「某ユーザーが話題に参加しました」のシステムイベント（本文なし）、後者が実投稿。`fetch_details.py` は `/feed/` をスキップし、統計も両者を区別します。
- **DOM fid フォールバックの存在理由**：列表 API のページングには漏れがあり、画面上見える投稿が API では返らないケースがある。`scrape.py` が DOM 上の全 `fid="..."` を `dom_fids.json` に書き出し、`fetch_details.py` で差分を詳細ページから補完します。

詳しいワークフローと注意点は `SKILL.md` を参照。

---

<a id="中文"></a>

## 中文

抓取 moomoo 社区话题（discussion）页下所有参与帖子，下载图片，产出可浏览报告 + **中日双语分析总结**。

### 能做什么

给 agent 一个 moomoo 话题 URL（任意 locale：`/ja/` `/en/` `/zh/` 均可），它会：

1. 自动翻页抓取话题下全部帖子（列表 API + DOM fallback 双重捕获）
2. 对被截断的长帖、或列表 API 没返回的帖子，访问详情页补齐
3. 下载每条帖子里的原图
4. 生成**可浏览的 HTML 报告**（图片内联在正文下）
5. 生成**中日双语分析总结报告**（日本語 → 中文 同文件收录）

### 首次安装

#### 1. 放对位置

skill 应放在 Claude Code 默认扫描的路径下：

- **用户级（推荐）**：`~/.claude/skills/moomoo-topic-summary/`
  - Windows: `C:\Users\<你>\.claude\skills\moomoo-topic-summary\`
- **项目级**：`<repo>/.claude/skills/moomoo-topic-summary/`

目录结构：

```
moomoo-topic-summary/
├── SKILL.md             # 给 agent 读的工作流
├── README.md            # 你正在看的这份
└── scripts/
    ├── login.py         # 手动登录一次，产出 state.json
    ├── scrape.py        # 自动滚动翻页抓列表 API + 记录 DOM fid
    ├── extract.py       # 解析为结构化 feeds.json
    ├── fetch_details.py # 补全被截断或 DOM-only 的帖子
    ├── download_images.py # 下载原图
    └── build_report.py  # 出可浏览 HTML 报告
```

#### 2. 安装 Python 依赖

```bash
python -m pip install playwright
python -m playwright install chromium
```

Python 需要 3.10+。

#### 3. 验证 skill 被识别

在 Claude Code 里问一句 "有哪些 skills 可用"，列表里应该出现 `moomoo-topic-summary`。

### 使用

#### 日常用法（给 agent 的话）

直接把 URL 丢给 agent：

> 帮我总结下这个 moomoo 话题下大家在聊什么：
> `https://www.moomoo.com/ja/community/discussion/xxx-xxx-2052587553`

agent 会走完全流程，最后把 `report.html`（可浏览）和 `summary.html`（中日双语分析）的绝对路径告诉你，双击打开即可。

#### 第一次使用需要登录

Agent 会引导你在终端运行：

```bash
python ~/.claude/skills/moomoo-topic-summary/scripts/login.py ja
```

（末尾的 `ja` 换成目标 URL 的 locale：`en` / `zh` / `ja` ...）

浏览器弹出后自己点登录，登录完回终端按回车，`state.json` 就保存下来了。以后同一个 locale 下的所有话题都能复用这份登录态，过期了再重跑一次就行。

#### 工作目录

每个话题会在当前工作目录下建一个独立子目录（比如 `moomoo-scraper/<话题slug>/`），所有产物都在它的 `output/` 里，互不污染。

### 产物说明

```
output/
├── api_responses.jsonl   # 原始 API dump（debug 用）
├── dom_fids.json         # 页面 DOM 里能看到的所有 fid（列表 API 兜底依据）
├── details_raw/<fid>.json # 详情页捕获的 API 响应（debug 用）
├── feeds.json            # 结构化帖子数据（核心中间产物）
├── feeds_preview.txt     # 人读预览
├── images/<feed_id>/*    # 每条帖子的原图
├── report.html           # 可浏览报告：所有帖子 + 内联图片
└── summary.html          # **中日双语分析总结报告**（最终交付物）
```

### 已知局限

1. **DOM fallback 帖子的局限**：对列表 API 没返回、靠 DOM 文本救回的帖子，以下字段缺失：
   - 图片元数据无法恢复（详情页 API 不返回）
   - `is_essence`（精华）、`is_popular`（热门）标志无法恢复
   - **nick/timestamp/views 的解析目前仅支持日文 locale**（EN/ZH locale 下这些字段为 null，正文仍可回收）
2. **时间精度**：从 DOM 抽的时间是 `04/16 16:00` 这种分钟级显示，秒位填 0，转成 JST epoch。
3. **删除判定用完整短语**：删除标记按 locale 分别列出完整短语（早期版本用裸单词 `deleted` 会与页脚 UI 文案误匹配，已收紧）。

### 常见问题

**Q: 抓取只有几条数据就停了？**
多半是登录态过期。重跑 `login.py` 覆盖 `state.json`。

**Q: Windows 控制台输出乱码？**
`set PYTHONIOENCODING=utf-8`（PowerShell: `$env:PYTHONIOENCODING='utf-8'`）。

**Q: 长帖正文只有前几行？**
`fetch_details.py` 会自动补齐。如果想手动触发，进到话题工作目录再跑一遍该脚本。

**Q: 可以只要报告不要总结吗？**
可以，跑到 `build_report.py` 这一步停下即可；`summary.html` 是 agent 基于 `feeds.json` 另外生成的。

**Q: 支持非日文站吗？**
URL 任意 locale 都支持。**但 DOM fallback 帖子的元数据解析目前仅限日文页面**。EN/ZH 页面里 DOM fallback 帖子的 nick/timestamp/views 会是 null（正文仍可回收）。

### 设计说明

- **为什么要手动登录一次**：moomoo 的列表 API 需要登录态；自动化登录涉及验证码风险，不如一次人工登录换来长期可复用的 `state.json` 稳定。
- **为什么不用 `networkidle`**：moomoo 有持续不断的 analytics / tracking 请求，`networkidle` 永远触发不了，改用 `domcontentloaded` + 固定等待。
- **`/feed/` vs `/discussion/`**：前者是"某用户加入了话题"的系统事件（无正文），后者才是真实帖子。`fetch_details.py` 会跳过 `/feed/`，统计分析时也要区分。
- **为什么要有 DOM fid 兜底**：moomoo 列表 API 分页有时会漏帖（画面上能看到但 API 不返回）。`scrape.py` 把 DOM 里所有 `fid="..."` 记到 `dom_fids.json`，`fetch_details.py` 对比列表 API 的覆盖，为缺失的 fid 造 stub 并访问详情页补全。

更详细的工作流和注意事项请看 `SKILL.md`。
