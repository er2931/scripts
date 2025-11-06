# discord_members_min_edge.py
# Minimal Selenium (Edge) script:
# - Opens Discord web
# - Waits for the app UI
# - On Enter, reads VISIBLE members from the current guild page and prints them

import time
from selenium.webdriver import Edge
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Locale-agnostic selectors (avoid English-specific aria-labels)
SERVERS_SIDEBAR = 'nav[role="navigation"]'                         # left server rail
CHANNELS_PANEL  = 'div[role="tree"], nav[role="tree"]'             # channels list area
MEMBERS_PANEL   = 'aside [role="list"], div[aria-label][role="list"], div[role="list"]'
MEMBER_ITEM     = f'{MEMBERS_PANEL} [role="listitem"]'

def open_edge():
    opts = EdgeOptions()
    opts.add_argument("--start-maximized")
    # Optional: keep session so you don't log in every time
    # opts.add_argument(r'--user-data-dir=C:\Users\YourName\AppData\Local\EdgeDiscordProfile')
    # Reduce Edge/Chromium console spam
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = EdgeService()
    driver = Edge(options=opts, service=service)
    driver.get("https://discord.com/app")
    return driver

def wait_in_app(driver, timeout=180):
    w = WebDriverWait(driver, timeout)
    # Any of these means we're inside the app UI (works across locales)
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
    # Remove dups while keeping order
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n); out.append(n)
    return out

def main():
    driver = open_edge()
    print("\n1) If needed, log in to Discord in the Edge window.")
    print("2) Click any server (guild) so its member list is visible on the right.")
    print("3) Return here and press ENTER to read the visible members.")
    wait_in_app(driver)

    while True:
        try:
            input("\nPress ENTER to read visible members (or Ctrl+C to quit)… ")
        except KeyboardInterrupt:
            break

        members = read_visible_members(driver)
        if not members:
            print("No members detected. Make sure the right-side members panel is visible for the current server.")
        else:
            print(f"\nMembers visible ({len(members)}):")
            for m in members:
                print(" -", m)

    print("\nDone. You can close the Edge window.")
    # driver.quit()  # uncomment if you want it to close automatically

if __name__ == "__main__":
    main()
