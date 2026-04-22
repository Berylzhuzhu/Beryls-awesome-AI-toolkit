"""
Manual login helper. Opens a visible browser, user logs in manually,
then saves the login state to state.json in the current working dir.

Usage:
    python login.py             # opens https://www.moomoo.com (site picks locale)
    python login.py ja          # opens https://www.moomoo.com/ja
    python login.py <full-url>  # opens custom entry URL
"""
import sys
from playwright.sync_api import sync_playwright

STATE_FILE = "state.json"


def resolve_url(arg):
    if not arg:
        return "https://www.moomoo.com/"
    if arg.startswith("http"):
        return arg
    return f"https://www.moomoo.com/{arg.strip('/')}/"


def main():
    url = resolve_url(sys.argv[1] if len(sys.argv) > 1 else None)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(url)
        print("=" * 60)
        print(f"Browser opened: {url}")
        print("Please complete login (find the Login/ログイン button).")
        print("After you see your avatar, return here and press Enter.")
        print("=" * 60)
        input("Press Enter to save state > ")
        context.storage_state(path=STATE_FILE)
        print(f"Saved: {STATE_FILE}")
        browser.close()


if __name__ == "__main__":
    main()
