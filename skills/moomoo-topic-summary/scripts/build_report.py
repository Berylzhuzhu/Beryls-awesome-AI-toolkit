"""
Build a single-page HTML browsing report: every post with images inline.

Usage:
    python build_report.py

Reads output/feeds.json and output/images/<feed_id>/*.
Writes output/report.html — double-click to open in a browser.
"""
import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

FEEDS_FILE = Path("output/feeds.json")
IMG_ROOT = Path("output/images")
OUT_FILE = Path("output/report.html")


def local_images_for(feed_id):
    folder = IMG_ROOT / str(feed_id)
    if not folder.is_dir():
        return []
    return sorted(folder.iterdir(), key=lambda p: p.name)


def format_time(ts):
    try:
        # display in local time of viewer - use UTC; many moomoo audiences are JST
        dt = datetime.fromtimestamp(int(ts), tz=timezone(timedelta(hours=9)))
        return dt.strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return ""


def render(feed):
    fid = feed["feed_id"]
    title = html.escape(feed.get("title") or "")
    body_text = feed.get("body") or feed.get("body_dom") or ""
    body = html.escape(body_text).replace("\n", "<br>")
    nick = html.escape(feed.get("nick_name") or "")
    ts = format_time(feed.get("timestamp"))
    views = feed.get("browse_count") or 0
    url = feed.get("url") or ""
    tags = []
    if feed.get("is_essence"):
        tags.append('<span class="tag">精华</span>')
    if feed.get("is_popular"):
        tags.append('<span class="tag hot">热门</span>')
    imgs = local_images_for(fid)
    img_html = ""
    if imgs:
        items = [f'<a href="images/{fid}/{p.name}" target="_blank"><img src="images/{fid}/{p.name}" loading="lazy"></a>' for p in imgs]
        img_html = f'<div class="imgs">{"".join(items)}</div>'
    title_html = f'<h2>{title}</h2>' if title else ''
    body_html = f'<div class="body">{body}</div>' if body else ''
    return f"""<article>
  <div class="meta">
    <span class="nick">@{nick}</span>
    <span class="time">{ts}</span>
    <span class="views">{views:,} views</span>
    {" ".join(tags)}
    <a class="link" href="{html.escape(url)}" target="_blank">Source &rarr;</a>
  </div>
  {title_html}
  {body_html}
  {img_html}
</article>
"""


def main():
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    real = [f for f in feeds if f.get("body") or f.get("body_dom") or local_images_for(f["feed_id"])]
    real.sort(key=lambda x: int(x.get("timestamp") or 0), reverse=True)
    total_imgs = sum(len(local_images_for(f["feed_id"])) for f in real)
    articles = "\n".join(render(f) for f in real)
    html_doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Topic Report</title><style>
body {{ font-family: -apple-system, "Hiragino Sans", "Yu Gothic UI", sans-serif; max-width: 820px; margin: 20px auto; padding: 0 16px; background: #fafafa; color: #222; line-height: 1.6; }}
header {{ border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 20px; }}
header h1 {{ margin: 0 0 4px; font-size: 22px; }}
header .sub {{ color: #666; font-size: 13px; }}
article {{ background: #fff; border: 1px solid #e3e3e3; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }}
article h2 {{ margin: 8px 0; font-size: 17px; }}
.meta {{ font-size: 13px; color: #666; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
.meta .nick {{ font-weight: 600; color: #1368d6; }}
.meta .link {{ margin-left: auto; color: #1368d6; text-decoration: none; }}
.tag {{ display: inline-block; font-size: 11px; padding: 1px 6px; background: #eef; color: #336; border-radius: 3px; }}
.tag.hot {{ background: #fee; color: #c33; }}
.body {{ white-space: pre-wrap; word-wrap: break-word; margin: 8px 0; font-size: 15px; }}
.imgs {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
.imgs img {{ max-width: 240px; max-height: 240px; object-fit: cover; border-radius: 6px; border: 1px solid #ddd; cursor: zoom-in; }}
</style></head><body>
<header><h1>Topic posts</h1><div class="sub">{len(real)} posts · {total_imgs} images · generated {datetime.now().strftime("%Y-%m-%d %H:%M")}</div></header>
{articles}
</body></html>
"""
    OUT_FILE.write_text(html_doc, encoding="utf-8")
    print(f"Built: {OUT_FILE}  ({len(real)} posts, {total_imgs} images)")


if __name__ == "__main__":
    main()
