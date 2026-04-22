"""
Download original-resolution images from every feed's pictures[] array.

Usage:
    python download_images.py

Saves to output/images/<feed_id>/<NN>.<ext>
Resume-safe: skips files already present.
"""
import json
import mimetypes
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

FEEDS_FILE = Path("output/feeds.json")
IMG_DIR = Path("output/images")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"


def guess_ext(url, content_type):
    path = urlparse(url).path
    m = re.search(r"\.(jpe?g|png|gif|webp)(?:$|/|[?#])", path, re.I)
    if m:
        return "." + m.group(1).lower().replace("jpeg", "jpg")
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext
    return ".bin"


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        ext = guess_ext(url, resp.headers.get("Content-Type"))
        if dest.suffix == "":
            dest = dest.with_suffix(ext)
        dest.write_bytes(resp.read())
    return dest


def main():
    feeds = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    total = done = skipped = 0
    failed = []
    for feed in feeds:
        pics = feed.get("pictures") or []
        if not pics:
            continue
        folder = IMG_DIR / str(feed["feed_id"])
        folder.mkdir(exist_ok=True)
        for i, pic in enumerate(pics, 1):
            url = pic.get("original") or pic.get("big") or pic.get("thumb")
            if not url:
                continue
            total += 1
            if list(folder.glob(f"{i:02d}.*")):
                skipped += 1
                continue
            dest = folder / f"{i:02d}"
            try:
                saved = download(url, dest)
                done += 1
                print(f"  {feed['feed_id']} [{i}/{len(pics)}] -> {saved.name}")
            except Exception as e:
                failed.append((feed["feed_id"], i, str(e)))
                print(f"  {feed['feed_id']} [{i}] FAIL: {e}")
            time.sleep(0.3)

    print(f"\nTotal {total}, downloaded {done}, skipped {skipped}, failed {len(failed)}")


if __name__ == "__main__":
    main()
