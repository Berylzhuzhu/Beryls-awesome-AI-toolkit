"""
Fetch detail pages for feeds that need richer content.

Targets:
  (a) is_complete=False from list API (truncated)
  (b) word_count much larger than body length (heuristic truncation)
  (c) /discussion/ URL with empty body (possible missed content)

Skips /feed/ URLs — those are "joined the discussion" system events
with no body by design.

Usage:
    python fetch_details.py [--limit N]

Reads output/feeds.json; writes output/feeds.json in place, adding:
    body_source:    "list_api" | "detail_api" | "dom_fallback" | "deleted" | "empty"
    body_full:      the fuller body if we recovered one
"""
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE = "state.json"
FEEDS_FILE = Path("output/feeds.json")
DOM_FIDS_FILE = Path("output/dom_fids.json")
RAW_DIR = Path("output/details_raw")
API_HOST_RE = re.compile(r"(moomoo\.com|futunn\.com|futu\w*\.com)", re.I)
LOCALE_RE = re.compile(r"moomoo\.com/([a-z]{2}(?:-[a-z]{2})?)/community/", re.I)
# Each entry must be a phrase that only appears when moomoo is showing a deletion
# notice — NOT a bare word like "deleted" that also appears in unrelated footer/UI copy.
DELETE_MARKERS = [
    "削除されています", "已删除", "削除済",
    "This post has been deleted", "This content is no longer available",
]
WAIT_MS = 3000
TRUNCATION_RATIO = 0.5  # body shorter than this * word_count is suspicious

# DOM-fallback metadata parsing (currently JP only; other locales fall through)
JST = timezone(timedelta(hours=9))
JP_JOIN_MARKER = "がディスカッションに参加しました"
JP_DISCLAIMER = "免責事項："
JP_VIEW_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(万)?\s*回閲覧")
TIME_RE = re.compile(
    r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}"
    r"|\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}"
    r"|\d{1,2}:\d{2})"
)


def parse_jp_time_to_epoch(raw, now=None):
    """Convert '2026-04-16 16:00' / '04/16 16:00' / '16:00' → JST unix epoch."""
    now = now or datetime.now(JST)
    raw = raw.strip()
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})", raw)
    if m:
        y, mo, d, h, mi = map(int, m.groups())
        return int(datetime(y, mo, d, h, mi, tzinfo=JST).timestamp())
    m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", raw)
    if m:
        mo, d, h, mi = map(int, m.groups())
        dt = datetime(now.year, mo, d, h, mi, tzinfo=JST)
        if dt > now + timedelta(days=1):  # rollover: Jan parsed while we're in Dec
            dt = dt.replace(year=now.year - 1)
        return int(dt.timestamp())
    m = re.match(r"(\d{1,2}):(\d{2})", raw)
    if m:
        h, mi = map(int, m.groups())
        dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if dt > now + timedelta(hours=1):
            dt -= timedelta(days=1)
        return int(dt.timestamp())
    return None


def parse_dom_post_jp(text):
    """Extract nick / timestamp / body / view_count from JP feed DOM text."""
    out = {"nick_name": None, "timestamp": None, "body": None,
           "browse_count": None, "time_display": None}
    idx = text.find(JP_JOIN_MARKER)
    if idx < 0:
        return out
    before = text[:idx].rstrip()
    prev_lines = [l for l in before.split("\n") if l.strip()]
    if prev_lines:
        out["nick_name"] = prev_lines[-1].strip()
    after = text[idx + len(JP_JOIN_MARKER):]
    tm = TIME_RE.search(after[:200])
    body_start = 0
    if tm:
        out["time_display"] = tm.group(1)
        out["timestamp"] = parse_jp_time_to_epoch(tm.group(1))
        body_start = tm.end()
    rest = after[body_start:]
    disc_idx = rest.find(JP_DISCLAIMER)
    body_text = rest[:disc_idx] if disc_idx >= 0 else rest
    out["body"] = body_text.strip() or None
    after_disc = rest[disc_idx:] if disc_idx >= 0 else rest
    vm = JP_VIEW_RE.search(after_disc)
    if vm:
        try:
            n = float(vm.group(1).replace(",", ""))
            if vm.group(2) == "万":
                n *= 10000
            out["browse_count"] = int(n)
        except ValueError:
            pass
    return out


def detect_locale(feeds):
    for f in feeds:
        m = LOCALE_RE.search(f.get("url") or "")
        if m:
            return m.group(1)
    return "ja"


def find_full_feed_node(records, feed_id):
    """Search captured JSON responses for the raw feed object matching feed_id."""
    for rec in records:
        stack = [rec.get("body")]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                common = node.get("common")
                if isinstance(common, dict) and str(common.get("feed_id") or "") == str(feed_id):
                    return node
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return None


def feed_from_full_node(node, locale):
    """Mirror extract.py's extract_feed() for a single raw feed node."""
    common = node.get("common") or {}
    user = node.get("user_info") or {}
    summary = node.get("summary") or {}
    feed_id = common.get("feed_id")
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
        "timestamp": common.get("timestamp"),
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


def rich_text_to_plain(rich):
    if not rich:
        return ""
    return "\n".join(
        it["text"] for it in rich if isinstance(it, dict) and it.get("text")
    ).strip()


def needs_detail(feed):
    if feed.get("from_dom_fallback"):
        return "dom_fallback_missing"
    body = feed.get("body") or ""
    wc = feed.get("word_count") or 0
    if feed.get("is_complete") is False:
        return "is_complete_false"
    if wc > 50 and len(body) < wc * TRUNCATION_RATIO:
        return "suspiciously_short"
    if "/discussion/" in (feed.get("url") or "") and not body:
        return "discussion_no_body"
    return None


def extract_from_api_records(records, feed_id):
    """Deep search captured JSON responses for a matching feed's rich_text."""
    for rec in records:
        body = rec.get("body")
        stack = [body]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if str(node.get("feed_id") or "") == str(feed_id):
                    summary = node.get("summary") or {}
                    text = rich_text_to_plain(summary.get("rich_text"))
                    if text and summary.get("is_complete") is not False:
                        return text, summary.get("picture_items") or []
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return None, []


def main():
    if not FEEDS_FILE.exists():
        print(f"ERROR: {FEEDS_FILE} not found. Run extract.py first.", file=sys.stderr)
        sys.exit(2)
    if not Path(STATE_FILE).exists():
        print(f"ERROR: {STATE_FILE} not found. Run login.py first.", file=sys.stderr)
        sys.exit(2)

    limit = None
    args = sys.argv[1:]
    if args and args[0] == "--limit" and len(args) > 1:
        limit = int(args[1])

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    by_id = {f["feed_id"]: f for f in feeds}

    # DOM fallback: inject stubs for any fid seen in DOM but missed by list API
    locale = detect_locale(feeds)
    if DOM_FIDS_FILE.exists():
        try:
            dom_fids = json.loads(DOM_FIDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            dom_fids = []
        missing = [fid for fid in dom_fids if fid and fid not in by_id]
        if missing:
            print(f"DOM fallback: {len(missing)} fid(s) not in feeds.json — injecting stubs")
            for fid in missing:
                stub = {
                    "feed_id": fid,
                    "url": f"https://www.moomoo.com/{locale}/community/feed/{fid}",
                    "body": "",
                    "pictures": [],
                    "from_dom_fallback": True,
                }
                feeds.append(stub)
                by_id[fid] = stub

    targets = []
    for f in feeds:
        reason = needs_detail(f)
        if reason:
            targets.append((f, reason))
    if limit:
        targets = targets[:limit]

    print(f"Total feeds: {len(feeds)}  targets needing detail: {len(targets)}")
    for f, reason in targets:
        print(f"  - {f['feed_id']} [{reason}] {f['url']}")

    if not targets:
        # Mark every feed's source as list_api for consistency
        for f in by_id.values():
            f.setdefault("body_source", "list_api" if f.get("body") else "empty")
        FEEDS_FILE.write_text(
            json.dumps(list(by_id.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("Nothing to fetch. feeds.json marked with body_source.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            storage_state=STATE_FILE, viewport={"width": 1280, "height": 900}
        )
        for idx, (feed, reason) in enumerate(targets, 1):
            fid = feed["feed_id"]
            page = ctx.new_page()
            records = []

            def on_response(resp, store=records):
                try:
                    if "json" not in resp.headers.get("content-type", "").lower():
                        return
                    if not API_HOST_RE.search(resp.url):
                        return
                    try:
                        body = resp.json()
                    except Exception:
                        return
                    store.append({"url": resp.url, "body": body})
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                page.goto(feed["url"], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(WAIT_MS)
                (RAW_DIR / f"{fid}.json").write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                # For DOM-fallback stubs, try to grab the FULL feed node so we
                # recover author, timestamp, browse_count, etc. — not just body.
                handled = False
                if reason == "dom_fallback_missing":
                    full = find_full_feed_node(records, fid)
                    if full:
                        filled = feed_from_full_node(full, locale)
                        by_id[fid].update({k: v for k, v in filled.items() if v not in (None, "")})
                        by_id[fid]["body_source"] = "detail_api_full"
                        preview = (by_id[fid].get("body") or "")[:60].replace("\n", " ")
                        try:
                            print(f"[{idx}/{len(targets)}] {fid} [{reason}] -> detail_api_full  {preview}")
                        except UnicodeEncodeError:
                            print(f"[{idx}/{len(targets)}] {fid} [{reason}] -> detail_api_full  <non-ascii>")
                        handled = True
                if not handled:
                    text, pics = extract_from_api_records(records, fid)
                    source = None
                    if text:
                        by_id[fid]["body_full"] = text
                        by_id[fid]["body"] = text
                        source = "detail_api"
                    else:
                        # DOM fallback — capture full body text
                        try:
                            page_text = page.locator("body").inner_text(timeout=3000)
                        except Exception:
                            page_text = ""
                        if any(m in page_text for m in DELETE_MARKERS):
                            source = "deleted"
                        elif page_text:
                            by_id[fid]["body_dom"] = page_text
                            source = "dom_fallback"
                            if locale == "ja":
                                parsed = parse_dom_post_jp(page_text)
                                for k, v in parsed.items():
                                    if v and not by_id[fid].get(k):
                                        by_id[fid][k] = v
                                # If we successfully identified post structure
                                # (nick+time present), replace the noisy full-DOM
                                # body_dom with just the clean post text — avoids
                                # renderers falling back to nav/footer chrome.
                                if parsed["nick_name"] and parsed["timestamp"] is not None:
                                    by_id[fid]["body_dom"] = parsed["body"] or ""
                        else:
                            source = "empty"
                    if pics:
                        by_id[fid]["pictures"] = [
                            {
                                "original": (x.get("org_pic") or {}).get("url"),
                                "big": (x.get("big_pic") or {}).get("url"),
                                "thumb": (x.get("thumb_pic") or {}).get("url"),
                                "description": x.get("pic_description") or "",
                            }
                            for x in pics if isinstance(x, dict)
                        ]
                    by_id[fid]["body_source"] = source
                    preview = (by_id[fid].get("body") or "")[:60].replace("\n", " ")
                    try:
                        print(f"[{idx}/{len(targets)}] {fid} [{reason}] -> {source}  {preview}")
                    except UnicodeEncodeError:
                        print(f"[{idx}/{len(targets)}] {fid} [{reason}] -> {source}  <non-ascii>")
            except Exception as e:
                print(f"[{idx}/{len(targets)}] {fid} ERR {e}")
                by_id[fid]["body_source"] = f"error"
            finally:
                page.close()
            time.sleep(0.8)
        browser.close()

    # Mark everyone who didn't need fetching
    for f in by_id.values():
        if "body_source" not in f:
            f["body_source"] = "list_api" if f.get("body") else "empty"

    merged = sorted(by_id.values(), key=lambda x: int(x.get("timestamp") or 0), reverse=True)
    FEEDS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Updated: {FEEDS_FILE}")


if __name__ == "__main__":
    main()
