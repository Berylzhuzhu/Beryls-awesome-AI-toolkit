"""
Scrape a moomoo community discussion topic: open the page, auto-scroll
to load all replies, capture every JSON API response for later extraction.

Usage:
    python scrape.py <discussion_url>

Outputs (relative to CWD):
    output/api_responses.jsonl    one JSON record per line
    output/page_final.html        final rendered HTML (fallback)

Requires state.json in CWD (run login.py first).
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE_FILE = "state.json"
OUT_DIR = Path("output")
API_DUMP = OUT_DIR / "api_responses.jsonl"
PAGE_HTML = OUT_DIR / "page_final.html"
DOM_FIDS_FILE = OUT_DIR / "dom_fids.json"
API_HOST_RE = re.compile(r"(moomoo\.com|futunn\.com|futu\w*\.com)", re.I)
LOCALE_RE = re.compile(r"https?://(?:[^/]+)/([a-z]{2}(?:-[a-z]{2})?)/community/", re.I)
# URLs we always try to decode as JSON even if content-type header is funky
FEED_API_RE = re.compile(r"/discuss/|get-feed-list|get-feed-detail", re.I)


def detect_locale(url):
    m = LOCALE_RE.search(url)
    return m.group(1) if m else "ja"


def ensure_locale_in_url(url, locale="ja"):
    """moomoo accepts URLs without a locale segment but the redirect chain
    can take 60+ seconds. Inject /<locale>/ after the host so the goto is
    instant. Safe no-op if the URL already has a locale."""
    if LOCALE_RE.search(url):
        return url
    # Match https://host/path -> https://host/<locale>/path
    m = re.match(r"(https?://[^/]+)/(community/.+)", url, re.I)
    if m:
        patched = f"{m.group(1)}/{locale}/{m.group(2)}"
        print(f"[locale] no locale in URL; retrying as {patched}")
        return patched
    return url


def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape.py <discussion_url>", file=sys.stderr)
        sys.exit(2)
    url = ensure_locale_in_url(sys.argv[1])
    if not Path(STATE_FILE).exists():
        print(f"ERROR: {STATE_FILE} not found. Run login.py first.", file=sys.stderr)
        sys.exit(2)

    OUT_DIR.mkdir(exist_ok=True)
    if API_DUMP.exists():
        API_DUMP.unlink()

    locale = detect_locale(url)
    captured = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            storage_state=STATE_FILE,
            locale=f"{locale}-JP" if locale == "ja" else locale,
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        def on_response(resp):
            nonlocal captured
            try:
                if not API_HOST_RE.search(resp.url):
                    return
                ct = resp.headers.get("content-type", "").lower()
                is_feed_api = bool(FEED_API_RE.search(resp.url))
                # Be permissive for feed endpoints — some come back with
                # application/javascript or no content-type at all.
                if "json" not in ct and not is_feed_api:
                    return
                try:
                    body = resp.json()
                except Exception:
                    return
                with API_DUMP.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "url": resp.url, "status": resp.status,
                        "method": resp.request.method, "body": body,
                    }, ensure_ascii=False) + "\n")
                captured += 1
            except Exception:
                pass

        page.on("response", on_response)

        print(f"Opening: {url}")
        # IMPORTANT: use 'domcontentloaded' not 'networkidle' - moomoo has endless tracking pings
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1500)

        print("Auto-scrolling...")
        last_height = 0
        same_count = 0
        for i in range(300):
            page.evaluate("""
                () => {
                    window.scrollBy(0, window.innerHeight * 0.9);
                    document.querySelectorAll('*').forEach(el => {
                        const s = getComputedStyle(el);
                        if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                            && el.scrollHeight > el.clientHeight) {
                            el.scrollTop = el.scrollTop + el.clientHeight * 0.9;
                        }
                    });
                }
            """)
            page.wait_for_timeout(1200)
            height = page.evaluate("document.body.scrollHeight")
            scroll_y = page.evaluate("window.scrollY + window.innerHeight")
            print(f"  step {i+1}: height={height} pos={scroll_y} captured={captured}")
            if height == last_height:
                same_count += 1
                if same_count >= 6:
                    print(f"Height stable, stop scrolling")
                    break
            else:
                same_count = 0
                last_height = height

        PAGE_HTML.write_text(page.content(), encoding="utf-8")
        print(f"Saved HTML: {PAGE_HTML}")
        print(f"Captured {captured} JSON responses: {API_DUMP}")

        # Dump unique feed IDs present in the rendered DOM so downstream
        # fetch_details.py can detect feeds the list API didn't surface.
        try:
            dom_fids = page.evaluate(
                "() => Array.from(new Set("
                "Array.from(document.querySelectorAll('[fid]'))"
                ".map(e => e.getAttribute('fid'))"
                ".filter(Boolean)))"
            )
        except Exception as e:
            dom_fids = []
            print(f"DOM fid scan failed: {e}")
        DOM_FIDS_FILE.write_text(
            json.dumps(dom_fids, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"DOM fids captured: {len(dom_fids)} -> {DOM_FIDS_FILE}")
        browser.close()


if __name__ == "__main__":
    main()
