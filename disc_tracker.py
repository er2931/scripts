# discord_members_tracker_edge_inputloop.py
# Opens Discord in Edge, waits for login, lets you enter names one by one.
# Type "done" when finished. Then it refreshes every second and shows who is visible.

import time
import os
from selenium.webdriver import Edge
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SERVERS_SIDEBAR = 'nav[role="navigation"]'
CHANNELS_PANEL  = 'div[role="tree"], nav[role="tree"]'
MEMBERS_PANEL   = 'aside [role="list"], div[aria-label][role="list"], div[role="list"]'
MEMBER_ITEM     = f'{MEMBERS_PANEL} [role="listitem"]'

REFRESH_SECONDS = 1.0

def open_edge():
    opts = EdgeOptions()
    opts.add_argument("--start-maximized")
    # Optional: keep session (uncomment & change to your path)
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

def read_visible_members(driver, timeout=3):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, MEMBERS_PANEL))
        )
    except Exception:
        return []
    names = []
    for row in driver.find_elements(By.CSS_SELECTOR, MEMBER_ITEM):
        txt = (row.text or row.get_attribute("aria-label") or "").strip()
        if txt:
            names.append(txt.splitlines()[0].strip())
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out

def normalize(name):
    return " ".join(name.strip().lower().split())

def clear_console():
    os.system("cls" if os.name == "nt" else "clear")

def print_table(targets, visible):
    name_w = max(6, min(40, max((len(n) for n in targets), default=6)))
    print(f"{'User'.ljust(name_w)} | Present")
    print("-" * (name_w + 10))
    for name in targets:
        present = "y" if normalize(name) in visible else "n"
        print(f"{name.ljust(name_w)} | {present}")

def main():
    driver = open_edge()
    print("\n1) Log in to Discord if needed.")
    print("2) Click a server so the member list (right side) is visible.")
    wait_in_app(driver)

    targets = []
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
            visible_list = read_visible_members(driver)
            visible_norm = {normalize(n) for n in visible_list}
            clear_console()
            print("Discord Members Tracker\n")
            print_table(targets, visible_norm)
            print("\nPress Ctrl+C to stop.")
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        pass  # driver.quit() if you want it to close automatically

if __name__ == "__main__":
    main()
