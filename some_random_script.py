import time
import threading
import numpy as np
import cv2
from PIL import Image
import pyautogui
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import keyboard

pyautogui.FAILSAFE = False

# -----------------------------
# Twitch video loader
# -----------------------------
class TwitchLoader:
    def __init__(self, fps=30):
        self.driver = None
        self.frame = None
        self.running = False
        self.fps = fps
        self.video_element = None

    def start(self, channel=""):
        if self.running:
            return
        opts = Options()
        opts.add_argument("--disable-infobars")
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-extensions")
        # opts.add_argument("--headless=new")  # keep browser visible
        self.driver = webdriver.Chrome(options=opts)
        self.driver.get(f"https://www.twitch.tv/{channel}")
        time.sleep(6)  # allow video to load
        self.video_element = self.driver.find_element(By.TAG_NAME, "video")
        self.running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

    def _capture_loop(self):
        while self.running:
            try:
                png = self.video_element.screenshot_as_png
                img = Image.open(io.BytesIO(png))
                self.frame = np.array(img.convert("RGB"))
            except Exception as e:
                print("Error capturing frame:", e)
            time.sleep(1 / self.fps)

    def get_frame(self):
        return self.frame

# -----------------------------
# Tracker
# -----------------------------
class Tracker:
    def __init__(self, alpha=0.6, expand=10):
        self.pins = []
        self.prev_pos = {}
        self.alpha = alpha
        self.expand = expand
        self.selected_pin = None

    def add_pin(self, x, y, w, h, frame_np):
        x, y, w, h = int(x), int(y), int(w), int(h)
        sub = frame_np[y:y+h, x:x+w]
        avg_color = tuple(np.mean(sub.reshape(-1,3), axis=0))
        pid = len(self.pins)
        if pid >= 3:
            print("Max 3 pins allowed")
            return None
        pin = {"id": pid, "x": x, "y": y, "w": w, "h": h, "color": avg_color, "saved_color": None, "last_frame": None}
        self.pins.append(pin)
        print(f"📍 Added pin {pid} at ({x},{y}) size {w}x{h}")
        return pid

    def update_from_frame(self, frame_np):
        if frame_np is None:
            return self.pins
        h_frame, w_frame = frame_np.shape[:2]
        lab_frame = cv2.cvtColor(frame_np, cv2.COLOR_RGB2LAB)
        updated = []

        for pin in self.pins:
            pid = pin["id"]
            px, py, pw, ph = map(int, (pin["x"], pin["y"], pin["w"], pin["h"]))
            avg_color = np.array(pin["color"])

            if pid != 0:
                updated.append(pin.copy())
                continue

            x0 = max(0, px - self.expand)
            y0 = max(0, py - self.expand)
            x1 = min(w_frame - pw - 1, px + self.expand)
            y1 = min(h_frame - ph - 1, py + self.expand)

            target_lab = cv2.cvtColor(np.uint8([[avg_color]]), cv2.COLOR_RGB2LAB)[0][0]
            best_x, best_y, best_score = px, py, float("inf")

            for xi in range(x0, x1 + 1):
                for yi in range(y0, y1 + 1):
                    sub = lab_frame[yi:yi+ph, xi:xi+pw]
                    if sub.size == 0:
                        continue
                    avg_sub = np.mean(sub.reshape(-1,3), axis=0)
                    dist = np.linalg.norm(avg_sub - target_lab)
                    if dist < best_score:
                        best_score, best_x, best_y = dist, xi, yi

            if pid in self.prev_pos:
                ox, oy = self.prev_pos[pid]
                best_x = self.alpha*best_x + (1-self.alpha)*ox
                best_y = self.alpha*best_y + (1-self.alpha)*oy

            pin["x"], pin["y"] = int(best_x), int(best_y)
            self.prev_pos[pid] = (best_x, best_y)
            updated.append(pin.copy())

        self.pins = updated
        return updated

# -----------------------------
# Mouse controller
# -----------------------------
class MouseController:
    def __init__(self, sensitivity=2.06):
        self.active = False
        self.prev_pos = None
        self.sens = sensitivity

    def set_active(self, v: bool):
        self.active = v

    def update_and_move(self, pos, video_size):
        if pos is None:
            self.prev_pos = None
            return
        vx, vy = pos
        if self.prev_pos is None:
            self.prev_pos = (vx, vy)
            return
        dx, dy = vx - self.prev_pos[0], vy - self.prev_pos[1]
        sx = dx * self.sens * (pyautogui.size()[0] / video_size[0])
        sy = dy * self.sens * (pyautogui.size()[1] / video_size[1])
        if self.active and (abs(sx) >= 1 or abs(sy) >= 1):
            pyautogui.moveRel(sx, sy, duration=0)
        self.prev_pos = (vx, vy)

# -----------------------------
# Toggle Manager
# -----------------------------
class ToggleManager:
    def __init__(self, change_threshold=0.85, debounce=0.59):
        self.change_threshold = change_threshold
        self.debounce = debounce
        self.last_toggle = 0
        self.move_state = False
        self.click_state = False

    def pixels_changed_ratio(self, frame_np, pin):
        h_frame, w_frame = frame_np.shape[:2]
        x0 = max(0, int(pin["x"]))
        y0 = max(0, int(pin["y"]))
        x1 = min(int(pin["x"]+pin["w"]), w_frame)
        y1 = min(int(pin["y"]+pin["h"]), h_frame)

        sub = frame_np[y0:y1, x0:x1]
        if sub.size == 0 or pin["last_frame"] is None:
            pin["last_frame"] = sub.copy()
            return 0.0

        diff = np.abs(sub.astype(int) - pin["last_frame"].astype(int))
        changed_pixels = np.sum(np.any(diff > 10, axis=2))
        total_pixels = sub.shape[0] * sub.shape[1]
        pin["last_frame"] = sub.copy()
        return changed_pixels / total_pixels if total_pixels > 0 else 0.0

    def check(self, frame_np, pins):
        now = time.time()
        if len(pins) > 0 and self.pixels_changed_ratio(frame_np, pins[0]) > self.change_threshold:
            if now - self.last_toggle > self.debounce:
                self.move_state = not self.move_state
                self.last_toggle = now
        if len(pins) > 2 and self.pixels_changed_ratio(frame_np, pins[2]) > self.change_threshold:
            if now - self.last_toggle > self.debounce:
                self.click_state = True
                self.last_toggle = now
        else:
            self.click_state = False
        return self.move_state, self.click_state

# -----------------------------
# Main App
# -----------------------------
class App:
    def __init__(self):
        self.window_name = "Twitch Tracker"
        self.loader = TwitchLoader()
        self.tracker = Tracker()
        self.mouse = MouseController()
        self.toggle = ToggleManager()
        self.frame_np = None
        self.running = False
        self.menu_visible = False

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, 1280, 720)
        cv2.setMouseCallback(self.window_name, self.on_mouse)

        self.dragging_pin = None
        self.drag_offset = (0,0)
        self.new_pin_start = None

    def on_mouse(self, event, x, y, flags, param):
        if self.frame_np is None:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            for pin in self.tracker.pins:
                if pin["x"] <= x <= pin["x"]+pin["w"] and pin["y"] <= y <= pin["y"]+pin["h"]:
                    self.dragging_pin = pin
                    self.tracker.selected_pin = pin
                    self.drag_offset = (x-pin["x"], y-pin["y"])
                    return
            if len(self.tracker.pins) < 3:
                self.new_pin_start = (x,y)
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging_pin:
            self.dragging_pin["x"] = x - self.drag_offset[0]
            self.dragging_pin["y"] = y - self.drag_offset[1]
        elif event == cv2.EVENT_LBUTTONUP:
            if self.dragging_pin:
                self.dragging_pin = None
            elif self.new_pin_start and len(self.tracker.pins) < 3:
                x0, y0 = self.new_pin_start
                w, h = max(5, x - x0), max(5, y - y0)
                self.tracker.add_pin(x0, y0, w, h, self.frame_np)
                self.new_pin_start = None

    def draw_menu(self, frame):
        # Simple top menu
        menu_text = "RIGHT CTRL: Toggle Menu | CTRL+A+R: Reset Pins"
        cv2.putText(frame, menu_text, (10,25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

    def start(self):
        ch = input("Enter Twitch channel: ").strip() or "kanekolumi"
        self.loader.start(ch)
        self.running = True
        self.loop()

    def loop(self):
        while self.running:
            frame = self.loader.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue
            self.frame_np = frame
            pins = self.tracker.update_from_frame(frame)
            move_state, click_state = self.toggle.check(frame, pins)
            self.mouse.set_active(move_state)
            if click_state:
                pyautogui.click()

            if len(pins) > 0:
                p0 = pins[0]
                cx, cy = p0["x"] + p0["w"]/2, p0["y"] + p0["h"]/2
                self.mouse.update_and_move((cx, cy), (frame.shape[1], frame.shape[0]))

            display = frame.copy()
            colors = [(0,255,0),(0,0,255),(255,0,0)]
            for pin in pins:
                x, y, w, h = map(int, (pin["x"], pin["y"], pin["w"], pin["h"]))
                color = colors[pin["id"]%len(colors)]
                cv2.rectangle(display, (x,y), (x+w,y+h), color, 2)
                if pin == self.tracker.selected_pin:
                    cv2.rectangle(display, (x,y), (x+w,y+h), (0,255,255), 2)
                cv2.putText(display, f"Pin {pin['id']}", (x,y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            if self.menu_visible:
                self.draw_menu(display)

            cv2.putText(display, f"Move {'ON' if move_state else 'OFF'} | Click {'ON' if click_state else 'OFF'}",
                        (10,50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
            cv2.imshow(self.window_name, cv2.cvtColor(display, cv2.COLOR_RGB2BGR))

            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # ESC
                self.running = False
                self.loader.stop()
                break
            elif key == 0xA3:  # Right Ctrl
                self.menu_visible = not self.menu_visible

            # Ctrl + A + R to reset all pins
            if keyboard.is_pressed('ctrl') and keyboard.is_pressed('a') and keyboard.is_pressed('r'):
                self.tracker.pins = []
                self.tracker.selected_pin = None
                print("🗑️ All pins cleared. You can add new pins now.")
                time.sleep(0.5)

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    import io
    app = App()
    app.start()
