import keyboard
import threading
import time

pressing = False
target_key = None

def press_loop():
    """Continuously press the key while it's held down."""
    global pressing, target_key
    while pressing:
        keyboard.press(target_key)
        keyboard.release(target_key)
        time.sleep(5)

def on_key_down(event):
    """Start auto pressing when any key is pressed (except ESC)."""
    global pressing, target_key
    if event.name == "esc":  # Escape exits
        keyboard.unhook_all()
        print("\n[!] Exiting...")
        return
    if not pressing:
        target_key = event.name
        pressing = True
        print(f"[+] Holding '{target_key}' — auto pressing started.")
        threading.Thread(target=press_loop, daemon=True).start()

def on_key_up(event):
    """Stop auto pressing when the key is released."""
    global pressing
    if event.name == target_key:
        pressing = False
        print(f"[-] Released '{target_key}' — stopped.")

if __name__ == "__main__":
    print("Press and hold any key to start auto pressing it.")
    print("Release the key to stop. Press ESC to exit.\n")
    keyboard.on_press(on_key_down)
    keyboard.on_release(on_key_up)
    keyboard.wait("esc")
