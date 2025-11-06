# discord_members_tracker_edge_presence.py
# Track selected members (entered one-by-one, type "done") and show presence:
# online / idle / dnd / offline / mobile
#
# Presence is inferred from badges and aria-labels in the members panel.
# Refreshes every second. Stop with Ctrl+C.

import time
import os
from typing import List, Dict, Tuple

from selenium.webdriver import Edge
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# App structure (locale-agnostic)
SERVERS_SIDEBAR = 'nav[role="navigation"]'
CHANNELS_PANEL  = 'div[role="tree"], nav[role="tree"]'
MEMBERS_PANEL   = 'aside [role="list"], div[aria-label][role="list"], div[role="list"]'
MEMBER_ITEM     = f'{MEMBERS_PANEL} [role="listitem"]'

# Inside a member row, these often exist (Discord tweaks classes; we rely on roles/labels)
# We'll look for presence via aria-label/title, or small status icons.
CANDIDATE_STATUS_SELECTORS = [
    # Status dot / badge containers near the avatar
    '[aria-label*="Online" i], [title*="Online" i]',
    '[aria-label*="Idle" i], [title*="Idle" i]',
    '[aria-label*="Do Not Disturb" i], [title*="Do Not Disturb" i], [aria-label*="DND" i], [title*="DND" i]',
    # Mobile badge sometimes has "Mobile" in its aria-label or title
    '[aria-label*="Mobile" i], [title*="Mobile" i]',
    # Generic status role regions sometimes exposed:
    '[role="img"][aria-label], [role="img"][title]',
]

REFRESH_SECONDS = 1.0

def open_edge():
    opts = EdgeOptions()
    opts.add_argument("--start-maximized")
    # Optional persistent profile to avoid logging in every time:
    # opts.add_argument(r'--user-data-dir=C:\Users\YourName\AppData\Local\EdgeDiscordProfile')
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = EdgeService()
    driver = Edge(options=opts, service=service)
    driver.get("https://discord.com/app")
    return driver

def wait_in_app(driver, timeout=180):
    w = WebDriverWait(driver, timeout)
    w.until(EC.any_of(
        EC.presence_of_element_located((By.CSS_SELECTOR, SERVERS_SIDEBAR)),
        EC.presence_of_element_located((By.CSS_SELECTOR, CHANNELS_PANEL)),
        EC.url_contains("/channels/"),
        EC.url_contains("/app"),
    ))
    time.sleep(1.0)

def read_visible_member_rows(driver, timeout=3):
    """Return list of WebElement rows for currently visible members."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, MEMBERS_PANEL))
        )
    except Exception:
        return []
    return driver.find_elements(By.CSS_SELECTOR, MEMBER_ITEM)

def extract_display_name_from_row(row) -> str:
    # Prefer row.text first line; fallback aria-label
    txt = (row.text or row.get_attribute("aria-label") or "").strip()
    if not txt:
        return ""
    return txt.splitlines()[0].strip()

def extract_presence_from_row(row) -> str:
    """
    Heuristic:
    - Search for elements in the row that carry presence in aria-label/title.
    - Normalize to: 'mobile', 'online', 'idle', 'dnd', else 'online' if hint found.
    - If no hints at all, return 'offline' (either off-screen or no badge).
    """
    # Try direct aria-label/title on the row
    for attr in ("aria-label", "title"):
        val = (row.get_attribute(attr) or "").lower()
        if "mobile" in val: return "mobile"
        if "do not disturb" in val or "dnd" in val: return "dnd"
        if "idle" in val: return "idle"
        if "online" in val: return "online"

    # Inspect common badge/icon children
    for sel in CANDIDATE_STATUS_SELECTORS:
        for el in row.find_elements(By.CSS_SELECTOR, sel):
            a = ((el.get_attribute("aria-label") or "") + " " + (el.get_attribute("title") or "")).lower()
            if not a:
                continue
            if "mobile" in a:
                return "mobile"
            if "do not disturb" in a or "dnd" in a:
                return "dnd"
            if "idle" in a:
                return "idle"
            if "online" in a:
                return "online"

    # Sometimes the status dot has no text; try color hints via computed role=img with label
    # (Already covered by role="img"[aria-label], but if nothing matches:)
    return "offline"

def snapshot_visible_presence(driver) -> Dict[str, str]:
    """
    Returns {display_name: presence} for rows currently visible in the members panel.
    Presence one of: online/idle/dnd/mobile/offline.
    """
    rows = read_visible_member_rows(driver)
    seen = {}
    for r in rows:
        name = extract_display_name_from_row(r)
        if not name:
            continue
        if name in seen:
            continue
        seen[name] = extract_presence_from_row(r)
    return seen

def normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())

def clear_console():
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass

def print_table(targets: List[str], presences: Dict[str, str]):
    # Normalize keys for faster lookup
    norm_map = {normalize(k): v for k, v in presences.items()}
    name_w = max(6, min(40, max((len(n) for n in targets), default=6)))
    print(f"{'User'.ljust(name_w)} | Visible | Presence")
    print("-" * (name_w + 22))
    for name in targets:
        n = normalize(name)
        if n in {normalize(k) for k in presences.keys()}:
            presence = norm_map.get(n, "online")  # default to online if present but no tag read
            print(f"{name.ljust(name_w)} |   y     | {presence}")
        else:
            print(f"{name.ljust(name_w)} |   n     | offline")

def main():
    driver = open_edge()
    print("\n1) Log in to Discord if needed.")
    print("2) Click a server so the right-side members list is visible.")
    print("   (We infer presence from that members panel.)")
    wait_in_app(driver)

    # Collect target names interactively
    targets: List[str] = []
    print("\nEnter the names to track one by one. Type 'done' when finished.")
    while True:
        name = input("> ").strip()
        if not name:
            continue
        if name.lower() == "done":
            break
        targets.append(name)

    if not targets:
        print("No names entered. Exiting.")
        return

    print("\nTracking:")
    for t in targets:
        print(" -", t)
    print("\nStarting 1s refresh loop. Press Ctrl+C to stop.\n")

    try:
        while True:
            presences = snapshot_visible_presence(driver)
            clear_console()
            print("Discord Members Tracker (visible-panel presence)\n")
            print_table(targets, presences)
            print("\nTips:")
            print(" - Scroll the members panel if your target users might be off-screen.")
            print(" - 'mobile' shows when Discord displays the phone badge for that member.")
            print(" - If a user isn’t visible in the panel, they’ll show as offline here.")
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        pass  # driver.quit() if you want it to close automatically

if __name__ == "__main__":
    main()
