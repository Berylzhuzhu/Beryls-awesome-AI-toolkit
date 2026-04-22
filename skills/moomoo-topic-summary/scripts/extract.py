"""
Parse output/api_responses.jsonl -> output/feeds.json + feeds_preview.txt.

Extracts each unique feed with key fields: title, body, author, views,
timestamp, pictures (with multiple resolutions), URL.

Auto-detects locale from the first discussion URL found in the API responses,
so the generated detail URLs stay consistent with the source site.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

IN_FILE = Path("output/api_responses.jsonl")
OUT_JSON = Path("output/feeds.json")
OUT_TXT = Path("output/feeds_preview.txt")
LOCALE_RE = re.compile(r"moomoo\.com/([a-z]{2}(?:-[a-z]{2})?)/community/", re.I)


def detect_locale():
    """Read api_responses.jsonl and guess locale from any discussion URL."""
    try:
        with IN_FILE.open(encoding="utf-8") as f:
            for line in f:
                m = LOCALE_RE.search(line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "ja"


def rich_text_to_plain(rich):
    if not rich:
        return ""
    return "\n".join(
        it["text"] for it in rich if isinstance(it, dict) and it.get("text")
    ).strip()


def extract_feed(feed, locale):
    common = feed.get("common") or {}
    user = feed.get("user_info") or {}
    summary = feed.get("summary") or {}
    feed_id = common.get("feed_id")
    ts = common.get("timestamp")
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        dt = None
    body = rich_text_to_plain(summary.get("rich_text"))
    pictures = []
    for p in (summary.get("picture_items") or []):
        if not isinstance(p, dict):
            continue
        pictures.append({
            "original": (p.get("org_pic") or {}).get("url"),
            "big": (p.get("big_pic") or {}).get("url"),
            "thumb": (p.get("thumb_pic") or {}).get("url"),
            "description": p.get("pic_description") or "",
        })
    slug = common.get("url_slugname") or ""
    post_url = (
        f"https://www.moomoo.com/{locale}/community/discussion/{slug}-{feed_id}"
        if slug else f"https://www.moomoo.com/{locale}/community/feed/{feed_id}"
    )
    return {
        "feed_id": feed_id,
        "timestamp": ts,
        "datetime_utc": dt,
        "title": common.get("feed_title") or "",
        "body": body,
        "pictures": pictures,
        "user_id": user.get("user_id"),
        "nick_name": user.get("nick_name"),
        "browse_count": common.get("browse_count"),
        "share_count": common.get("share_count"),
        "is_essence": common.get("is_essence"),
        "is_popular": common.get("is_popular"),
        "word_count": common.get("word_count"),
        "is_complete": summary.get("is_complete"),
        "url_slugname": slug,
        "url": post_url,
    }


def main():
    locale = detect_locale()
    seen = {}
    pages = 0
    with IN_FILE.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "get-feed-list" not in r["url"]:
                continue
            pages += 1
            feeds = (r.get("body") or {}).get("data", {}).get("feed") or []
            for feed in feeds:
                try:
                    item = extract_feed(feed, locale)
                except Exception as e:
                    print(f"[warn] skip feed: {e}")
                    continue
                if item["feed_id"] and item["feed_id"] not in seen:
                    seen[item["feed_id"]] = item

    items = sorted(seen.values(), key=lambda x: int(x["timestamp"] or 0), reverse=True)
    OUT_JSON.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # Preview
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"[{i}] {it['datetime_utc']}  @{it['nick_name']}  views={it['browse_count']}")
        if it["title"]:
            lines.append(f"    title: {it['title']}")
        if it["body"]:
            body = it["body"].replace("\n", " ")
            if len(body) > 120:
                body = body[:120] + "..."
            lines.append(f"    body:  {body}")
        lines.append(f"    url:   {it['url']}")
        lines.append("")
    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print(f"Parsed {pages} pages of get-feed-list responses")
    print(f"Unique feeds: {len(items)} (locale={locale})")
    print(f"Output: {OUT_JSON}")
    print(f"Preview: {OUT_TXT}")


if __name__ == "__main__":
    main()
