import sys, os, json, platform, subprocess, base64, ctypes
from ctypes import wintypes

# ------------------- Startup dependency check (notify & exit) -------------------
missing = []
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, colorchooser, messagebox
except Exception:
    print("tkinter is required (usually bundled with Python).")
    sys.exit(1)

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False
    missing.append("Pillow")

try:
    # Drag & drop (optional). If missing, we'll disable DnD gracefully.
    import tkinterdnd2 as tkdnd
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False
    missing.append("tkinterdnd2")

if missing:
    # Try to show a popup (fallback to console if Tk can't init)
    try:
        root_tmp = tk.Tk()
        root_tmp.withdraw()
        messagebox.showerror(
            "Missing Dependencies",
            "The following packages are required but not installed:\n\n- " +
            "\n- ".join(missing) +
            "\n\nPlease install them and run the app again."
        )
        root_tmp.destroy()
    except Exception:
        print("Missing dependencies:", ", ".join(missing))
    sys.exit(1)

# ------------------- Constants & utils -------------------
DEFAULT_FILE = "bookmarks.json"
LAST_FILE_STATE = ".bookmark_last.json"
DEFAULT_ICON_PNG = "default_icon.png"
DEFAULT_ICON_ICO = "default_icon.ico"

# tiny blue-folder PNG (32x32) base64; used to create default icon files
DEFAULT_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAACXBIWXMAAAsSAAALEgHS3X78AAA"
    "Gd0lEQVRYw+2XwW7cMBCGv1b5FzqS5g94yXg5Yj1Nw1w9k1Jw5i6qJ2o5F0fC3y0aB9Qy2JbK5b0b8"
    "Zk9C9b0c4jW3dQ7gk0n9E2Z7w0Wm8wqO6mQ2l8oW+v8cO4dH3yQq7Cw7dP0pC8q9J8k3jG1mG7kM6o"
    "u4RC0lI3pGJ7y2cYpGzR3b8d4x2o4aPz6y8pQmF7s2Rj9v0R3yEZD9W2TzYb4v8H3l2H8wGk7c0gk"
    "ZP6l4oV6eC3bB9w4oX4c3u0w8n1m1i0d3G8E8D6bQqKgiGmC8/fh9zM8y1aG8X3lJb0m0p7I2lqk2l"
    "CkAqJYj6Q8WJ1nq3mDkJcL2gk9QopG6yK2hlgQ4CkqXgqgqfY6i6C3d0QxP6cLwq8z7bB4suZ6iQG9"
    "bJg9Wb3kqSxvC8KkFjGJxkGxZJk2oQkQyPVbqZ9e2CwWkUj2mEw2mI4H0m6N0n1J8m3L5Yz7k3C8Jk"
    "R3G1mKf4P8v1r2+K8y2k4Q0n0B9V8f0l6a4aTg8b+o2DqBqD8kqBtH2cE2qC1A7FJf7gY6YFf4J3c/"
    "oC0k2m/9zJ8tQ7Y5aI9GJcCw3l6f3/XKx6p9K4z8mHfX7i6wZC9oC3C0s0B0P0g0g0g0g0g0g0g0g0"
    "g0g0g0g0g0g0g0g0g0g0+8AF3K6b3s3mJQAAAABJRU5ErkJggg=="
)

def ensure_default_icons():
    """Ensure a default PNG and ICO exist in the folder. Convert PNG->ICO if needed."""
    # default PNG
    if not os.path.exists(DEFAULT_ICON_PNG):
        try:
            with open(DEFAULT_ICON_PNG, "wb") as f:
                f.write(base64.b64decode(DEFAULT_PNG_B64))
        except Exception:
            pass
    # default ICO
    if not os.path.exists(DEFAULT_ICON_ICO):
        try:
            if PIL_AVAILABLE and os.path.exists(DEFAULT_ICON_PNG):
                img = Image.open(DEFAULT_ICON_PNG).convert("RGBA")
                img.save(DEFAULT_ICON_ICO, format="ICO", sizes=[(32, 32)])
        except Exception:
            pass

def rel_or_abs(path):
    """Return a relative path if inside CWD; else absolute."""
    try:
        cwd = os.path.abspath(os.getcwd())
        ap = os.path.abspath(path)
        if ap.startswith(cwd):
            return os.path.relpath(ap, cwd)
        return ap
    except Exception:
        return path

def center_window(win, parent):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    win.geometry(f"+{px + (pw // 2 - w // 2)}+{py + (ph // 2 - h // 2)}")

def open_local(path):
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])
    except Exception as e:
        print("Open failed:", e)

# -------------- Windows title bar coloring via DWM (best effort / silent fail elsewhere) --------------
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def set_windows_titlebar(hwnd, caption_rgb, text_rgb, dark=True):
    try:
        if platform.system() != "Windows":
            return
        dwm = ctypes.WinDLL("dwmapi")
        DwmSetWindowAttribute = dwm.DwmSetWindowAttribute
        DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD]
        DwmSetWindowAttribute.restype = wintypes.HRESULT

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36

        val = wintypes.BOOL(1 if dark else 0)
        DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val))

        def rgb_to_bgra(c):
            r,g,b = c
            return ctypes.c_int((b<<16) | (g<<8) | r)

        caption = rgb_to_bgra(caption_rgb)
        text = rgb_to_bgra(text_rgb)
        DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(caption), ctypes.sizeof(caption))
        DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(text), ctypes.sizeof(text))
    except Exception:
        pass

# ------------------- App -------------------
class BookmarkManager:
    def __init__(self, root):
        self.root = root
        self.file_path = self.load_last_file() or DEFAULT_FILE
        if not os.path.exists(self.file_path):
            self.file_path = DEFAULT_FILE

        base = os.path.splitext(os.path.basename(self.file_path))[0]
        self.root.title(f"📁 Bookmark Manager — {base}")


        ensure_default_icons()

        # Determine which file to open
        self.file_path = self.load_last_file() or DEFAULT_FILE
        if not os.path.exists(self.file_path):
            self.file_path = DEFAULT_FILE

        # Load data, init state
        self.data = self.load_data(self.file_path)
        self.path = []
        self.undo_stack, self.redo_stack = [], []
        self.popup_sizes = self.data.get("_popup_sizes", {})

        # Appearance
        self.theme_color = self.data.get("_theme_color", "#0078D7")
        self.titlebar_color = self.data.get("_titlebar_color", self.theme_color)
        self.bg_color = self.data.get("_bg_color", "#1b1b1d")
        self.text_color = self.data.get("_text_color", "#ffffff")
        self.button_color = self.data.get("_button_color", "#3A3A3D")
        self.font_family = self.data.get("_font_family", "Segoe UI Variable")
        self.font_size = int(self.data.get("_font_size", 10))
        self.icon_path = self.data.get("_icon_path", "")

        # Window size
        size = self.data.get("_window_size", {"width": 960, "height": 680})
        self.root.geometry(f"{size['width']}x{size['height']}")
        self.root.config(bg=self.bg_color)

        # Apply icon: prefer ICO; convert PNG to ICO if needed
        self.apply_icon()

        # Styles & UI
        self.update_styles()
        self.build_ui()
        self.refresh()

        # Apply title bar color (after first layout)
        self.root.after(200, self.apply_titlebar_color)

        # Enable drag & drop on tree if available
        if DND_AVAILABLE:
            try:
                self.root.tk.call('tk', 'scaling')  # ensure Tcl init
                self.tree.drop_target_register('*')
                self.tree.dnd_bind('<<Drop>>', self.on_drop)
            except Exception:
                pass

        # Close handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Save last used file
        self.save_last_file(self.file_path)

    # ------------- Styles -------------
    def update_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        self.font_main = (self.font_family, self.font_size)
        self.font_bold = (self.font_family, self.font_size+1, "bold")

        style.configure("Primary.TButton", font=self.font_bold, padding=8,
                        foreground="white", background=self.theme_color, borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#0A84FF"), ("pressed", "#0063B1")])

        style.configure("Secondary.TButton", font=self.font_main, padding=8,
                        foreground="white", background=self.button_color, borderwidth=0)
        style.map("Secondary.TButton", background=[("active", "#4A4A4D"), ("pressed", "#2D2D30")])

        style.configure("Treeview", background="#252526", fieldbackground="#252526",
                        foreground="white", rowheight=28, font=self.font_main)
        style.map("Treeview", background=[("selected", self.theme_color)])

    def apply_titlebar_color(self):
        if platform.system() == "Windows":
            r,g,b = hex_to_rgb(self.titlebar_color)
            # choose readable text
            lumin = 0.299*r + 0.587*g + 0.114*b
            text = (255,255,255) if lumin < 160 else (32,32,32)
            hwnd = self.root.winfo_id()
            set_windows_titlebar(hwnd, (r,g,b), text, dark=True)

    def apply_icon(self):
        ico_to_use = None
        chosen = self.icon_path

        # If PNG chosen, convert to ICO (Pillow required)
        if chosen:
            ap = os.path.abspath(chosen)
            if ap.lower().endswith(".ico") and os.path.exists(ap):
                ico_to_use = ap
            elif ap.lower().endswith(".png") and os.path.exists(ap) and PIL_AVAILABLE:
                # convert alongside png
                base = os.path.splitext(ap)[0] + ".ico"
                try:
                    Image.open(ap).convert("RGBA").save(base, format="ICO", sizes=[(32,32),(48,48),(64,64)])
                    ico_to_use = base
                except Exception:
                    pass

        if not ico_to_use:
            # fall back to default ico (ensure it exists)
            if not os.path.exists(DEFAULT_ICON_ICO) and PIL_AVAILABLE and os.path.exists(DEFAULT_ICON_PNG):
                try:
                    Image.open(DEFAULT_ICON_PNG).convert("RGBA").save(DEFAULT_ICON_ICO, format="ICO", sizes=[(32,32)])
                except Exception:
                    pass
            if os.path.exists(DEFAULT_ICON_ICO):
                ico_to_use = DEFAULT_ICON_ICO

        try:
            if ico_to_use and platform.system() == "Windows":
                self.root.iconbitmap(ico_to_use)
            else:
                # fallback to png window icon (not taskbar)
                if os.path.exists(DEFAULT_ICON_PNG):
                    img = tk.PhotoImage(file=DEFAULT_ICON_PNG)
                    self.root.iconphoto(True, img)
                    self._icon_ref = img
        except Exception:
            pass

    def update_all_styles(self):
        self.root.config(bg=self.bg_color)
        self.update_styles()
        # repaint simple labels/frames
        for w in self.root.winfo_children():
            if isinstance(w, tk.Frame):
                w.config(bg=self.bg_color)
                for c in w.winfo_children():
                    if isinstance(c, tk.Label):
                        c.config(bg=self.bg_color, fg=self.text_color)
            elif isinstance(w, tk.Label):
                w.config(bg=self.bg_color, fg=self.text_color)
        self.apply_titlebar_color()
        self.refresh()

    # ------------- UI -------------
    def build_ui(self):
        self.header = tk.Label(self.root, text="📚 Bookmark Manager",
                               font=(self.font_family, self.font_size+12, "bold"),
                               fg=self.text_color, bg=self.bg_color)
        self.header.pack(pady=10)

        tb = tk.Frame(self.root, bg=self.bg_color); tb.pack(pady=6)
        ttk.Button(tb, text="➕ Add Link", style="Primary.TButton", command=self.add_link).grid(row=0, column=0, padx=6)
        ttk.Button(tb, text="📁 New Folder", style="Secondary.TButton", command=self.new_folder).grid(row=0, column=1, padx=6)
        ttk.Button(tb, text="📄 Browse File", style="Secondary.TButton", command=self.add_file).grid(row=0, column=2, padx=6)
        ttk.Button(tb, text="📂 Browse Folder", style="Secondary.TButton", command=self.add_folder_shortcut).grid(row=0, column=3, padx=6)
        ttk.Button(tb, text="🗑 Delete", style="Secondary.TButton", command=self.delete_selected).grid(row=0, column=4, padx=6)
        ttk.Button(tb, text="⬅ Back", style="Secondary.TButton", command=self.go_back).grid(row=0, column=5, padx=6)
        ttk.Button(tb, text="💾 Backup", style="Primary.TButton", command=self.create_backup_popup).grid(row=0, column=6, padx=6)

        self.tree = ttk.Treeview(self.root, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)
        self.tree.bind("<Double-1>", self.on_double_click)

        footer = tk.Frame(self.root, bg=self.bg_color); footer.pack(fill=tk.X, pady=(4,8))
        tk.Label(footer,
                 text="💡 Double-click folders to open; links/files to launch. | Ctrl+Z=Undo | Ctrl+Y=Redo",
                 font=(self.font_family, max(self.font_size-1, 8)),
                 fg="#a0a0a0", bg=self.bg_color).pack(side=tk.LEFT, padx=20)

        ttk.Button(footer, text="📂 Load Backup", style="Secondary.TButton",
                   command=self.load_backup).pack(side=tk.RIGHT, padx=6)

        tk.Button(footer, text="⚙️", font=(self.font_family, self.font_size+2),
                  bg=self.button_color, fg="white", bd=0, width=3, height=1,
                  relief="flat", activebackground=self.theme_color,
                  command=self.open_settings).pack(side=tk.RIGHT, padx=8)

        # shortcuts
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())

    # ------------- Data helpers -------------
    def current_dir(self):
        node = self.data
        for p in self.path:
            node = node["folders"][p]
        return node

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        node = self.current_dir()
        for f in sorted(node["folders"].keys()):
            self.tree.insert("", tk.END, text=f"📁 {f}")
        for bm in node["links"]:
            kind = bm.get("kind", "url")
            icon = "🔗" if kind == "url" else ("📄" if kind == "file" else "🗀")
            self.tree.insert("", tk.END, text=f"{icon} {bm['name']}")
        base = os.path.splitext(os.path.basename(self.file_path))[0]  # remove extension
        self.root.title(f"📁 Bookmark Manager — {base}")



    def go_back(self):
        if self.path:
            self.path.pop()
            self.refresh()

    # ------------- Undo/Redo -------------
    def push_state(self):
        self.undo_stack.append(json.loads(json.dumps(self.data)))
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack: return
        self.redo_stack.append(json.loads(json.dumps(self.data)))
        self.data = self.undo_stack.pop()
        self.refresh()

    def redo(self):
        if not self.redo_stack: return
        self.undo_stack.append(json.loads(json.dumps(self.data)))
        self.data = self.redo_stack.pop()
        self.refresh()

    # ------------- Add -------------
    def new_folder(self):
        name = self.input_popup("New Folder", "Folder name:")
        if not name: return
        node = self.current_dir()
        if name in node["folders"]:
            self.message("Error", f"Folder '{name}' already exists.", "error")
            return
        self.push_state()
        node["folders"][name] = {"folders": {}, "links": []}
        self.save(); self.refresh()

    def add_link(self):
        res = self.link_popup()
        if not res: return
        name, url = res
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        self.push_state()
        self.current_dir()["links"].append({"name": name, "url": url, "kind": "url"})
        self.save(); self.refresh()

    def add_file(self):
        p = filedialog.askopenfilename(title="Select a File")
        if not p: return
        self.push_state()
        self.current_dir()["links"].append({"name": os.path.basename(p), "url": rel_or_abs(p), "kind": "file"})
        self.save(); self.refresh()

    def add_folder_shortcut(self):
        p = filedialog.askdirectory(title="Select a Folder")
        if not p: return
        self.push_state()
        name = os.path.basename(p.rstrip("/\\"))
        self.current_dir()["links"].append({"name": name, "url": rel_or_abs(p), "kind": "folder"})
        self.save(); self.refresh()

    # ------------- Delete -------------
    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            self.message("Info", "Select an item to delete.", "info"); return
        txt = self.tree.item(sel[0], "text")
        node = self.current_dir()
        self.push_state()
        if txt.startswith("📁"):
            name = txt[2:].strip()
            if self.confirm(f"Delete folder '{name}' and its contents?"):
                del node["folders"][name]
            else:
                self.undo_stack.pop(); return
        else:
            name = txt[2:].strip()
            if self.confirm(f"Delete item '{name}'?"):
                node["links"] = [l for l in node["links"] if l["name"] != name]
            else:
                self.undo_stack.pop(); return
        self.save(); self.refresh()

    # ------------- Double-click open -------------
    def on_double_click(self, _):
        sel = self.tree.selection()
        if not sel: return
        txt = self.tree.item(sel[0], "text")
        node = self.current_dir()
        if txt.startswith("📁"):
            self.path.append(txt[2:].strip()); self.refresh(); return
        name = txt[2:].strip()
        for bm in node["links"]:
            if bm["name"] == name:
                kind = bm.get("kind", "url"); url = bm.get("url", "")
                if kind == "url":
                    webbrowser_open(url)
                else:
                    open_local(url)
                break

    # ------------- Drag & Drop -------------
    def on_drop(self, event):
        # Works if tkinterdnd2 is installed; event.data may contain one or more paths
        data = event.data
        # typical formats: '{C:/path one/file.txt}' 'C:/path_two.txt' or multiple separated by spaces
        paths = []
        token = ""
        in_brace = False
        for ch in data:
            if ch == "{":
                in_brace = True; token = ""; continue
            if ch == "}":
                in_brace = False; paths.append(token); token = ""; continue
            if ch == " " and not in_brace:
                if token:
                    paths.append(token); token = ""
                continue
            token += ch
        if token: paths.append(token)
        if not paths: return

        node = self.current_dir()
        self.push_state()
        for p in paths:
            if not p: continue
            if os.path.isdir(p):
                name = os.path.basename(p.rstrip("/\\"))
                node["links"].append({"name": name, "url": rel_or_abs(p), "kind": "folder"})
            else:
                name = os.path.basename(p)
                node["links"].append({"name": name, "url": rel_or_abs(p), "kind": "file"})
        self.save(); self.refresh()

    # ------------- Backup (rename popup) -------------
    def create_backup_popup(self):
        key = "backup_rename"
        default_name = f"bookmarks_backup_{__import__('datetime').datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

        pop = tk.Toplevel(self.root)
        pop.title("Create Backup")
        pop.config(bg="#2b2b2b", padx=16, pady=12)
        pop.resizable(True, True)
        pop.grab_set()

        if key in self.popup_sizes:
            s = self.popup_sizes[key]
            pop.geometry(f"{s['width']}x{s['height']}")

        tk.Label(pop, text="Rename backup file if desired:", bg="#2b2b2b", fg="white",
                 font=self.font_main).pack(pady=(2,6))
        entry = ttk.Entry(pop, width=48, font=self.font_main)
        entry.insert(0, default_name)
        entry.pack(pady=(0,8))
        entry.focus()

        def do_save():
            name = entry.get().strip() or default_name
            # store popup size
            self.popup_sizes[key] = {"width": pop.winfo_width(), "height": pop.winfo_height()}
            try:
                with open(name, "w") as f:
                    json.dump(self.data, f, indent=2)
                pop.destroy()
                self.message("Backup Created", f"Saved as:\n{name}", "info")
            except Exception as e:
                self.message("Error", f"Failed to save:\n{e}", "error")

        ttk.Button(pop, text="Save", style="Primary.TButton", command=do_save).pack(pady=(2,4))
        pop.bind("<Return>", lambda e: do_save())
        center_window(pop, self.root)
        pop.wait_window()

    def load_backup(self):
        path = filedialog.askopenfilename(title="Select Backup File",
                                          filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path: return
        if not self.confirm(f"Load backup '{os.path.basename(path)}'?"):
            return
        try:
            self.data = self.load_data(path)
            self.file_path = path
            self.path = []
            self.save()
            self.refresh()
            self.save_last_file(self.file_path)
            self.message("Backup Loaded", f"Now editing:\n{os.path.basename(path)}", "info")
        except Exception as e:
            self.message("Error", f"Failed to load backup:\n{e}", "error")

    # ------------- Settings -------------
    def open_settings(self):
        key = "popup_settings"
        pop = tk.Toplevel(self.root)
        pop.title("Settings")
        pop.config(bg="#2b2b2b", padx=16, pady=12)
        pop.resizable(True, True)
        pop.grab_set()
        if key in self.popup_sizes:
            s = self.popup_sizes[key]
            pop.geometry(f"{s['width']}x{s['height']}")

        # fonts list (all system fonts)
        import tkinter.font as tkfont
        fonts = sorted(set(tkfont.families()))
        if self.font_family not in fonts:
            fonts.insert(0, self.font_family)

        def pick_color(label, attr):
            color = colorchooser.askcolor(title="Pick Color", initialcolor=getattr(self, attr))
            if color and color[1]:
                setattr(self, attr, color[1])
                label.config(bg=color[1])
                self.update_all_styles()

        def update_font_size(delta):
            self.font_size = max(6, min(28, self.font_size + delta))
            size_lbl.config(text=f"Font Size: {self.font_size}")
            self.update_all_styles()

        def choose_icon():
            p = filedialog.askopenfilename(title="Choose App Icon",
                                           filetypes=[("Icon/PNG", "*.ico *.png"), ("All files", "*.*")])
            if not p: return
            self.icon_path = rel_or_abs(p)
            self.apply_icon()
            icon_lbl.config(text=os.path.basename(self.icon_path) if self.icon_path else "Default")

        # Title
        tk.Label(pop, text="Customize Appearance", bg="#2b2b2b", fg="white",
                 font=(self.font_family, self.font_size+2, "bold")).pack(pady=(0,10))

        # Color pickers (Theme, TitleBar, Background, Text, Button)
        for lbl, attr in [("Theme", "theme_color"), ("Title Bar", "titlebar_color"),
                          ("Background", "bg_color"), ("Text", "text_color"), ("Button", "button_color")]:
            row = tk.Frame(pop, bg="#2b2b2b"); row.pack(pady=4, fill="x")
            tk.Label(row, text=f"{lbl} Color:", bg="#2b2b2b", fg="white", font=self.font_main).pack(side=tk.LEFT, padx=5)
            chip = tk.Label(row, bg=getattr(self, attr), width=14, height=1, relief="ridge")
            chip.pack(side=tk.LEFT, padx=8)
            ttk.Button(row, text="Pick", style="Secondary.TButton",
                       command=lambda c=chip, a=attr: pick_color(c, a)).pack(side=tk.LEFT)

        # Font family
        tk.Label(pop, text="Font Family", bg="#2b2b2b", fg="white", font=self.font_main).pack(pady=(10,2))
        font_box = ttk.Combobox(pop, values=fonts, state="readonly", font=self.font_main)
        font_box.set(self.font_family)
        font_box.pack(pady=(0,10))

        # Font size
        size_lbl = tk.Label(pop, text=f"Font Size: {self.font_size}",
                            bg="#2b2b2b", fg="white", font=self.font_main)
        size_lbl.pack(pady=(2,4))
        fs = tk.Frame(pop, bg="#2b2b2b"); fs.pack()
        ttk.Button(fs, text="➕", style="Primary.TButton", command=lambda: update_font_size(+1)).pack(side=tk.LEFT, padx=5)
        ttk.Button(fs, text="➖", style="Secondary.TButton", command=lambda: update_font_size(-1)).pack(side=tk.LEFT, padx=5)

        # Icon
        rowi = tk.Frame(pop, bg="#2b2b2b"); rowi.pack(pady=(12,4), fill="x")
        tk.Label(rowi, text="App Icon:", bg="#2b2b2b", fg="white", font=self.font_main).pack(side=tk.LEFT, padx=5)
        icon_lbl = tk.Label(rowi, text=os.path.basename(self.icon_path) if self.icon_path else "Default",
                            bg="#2b2b2b", fg="white", font=self.font_main)
        icon_lbl.pack(side=tk.LEFT, padx=8)
        ttk.Button(rowi, text="Change", style="Secondary.TButton", command=choose_icon).pack(side=tk.LEFT)

        def apply_changes():
            self.font_family = font_box.get()
            self.popup_sizes[key] = {"width": pop.winfo_width(), "height": pop.winfo_height()}
            self.save()
            pop.destroy()
            self.apply_icon()
            self.update_all_styles()
            self.apply_titlebar_color()

        ttk.Button(pop, text="Apply", style="Primary.TButton", command=apply_changes).pack(pady=(12,4))
        center_window(pop, self.root)
        pop.wait_window()

    # ------------- File I/O -------------
    def save(self):
        self.data.update({
            "_popup_sizes": self.popup_sizes,
            "_window_size": {"width": self.root.winfo_width(), "height": self.root.winfo_height()},
            "_theme_color": self.theme_color,
            "_titlebar_color": self.titlebar_color,
            "_bg_color": self.bg_color,
            "_text_color": self.text_color,
            "_button_color": self.button_color,
            "_font_family": self.font_family,
            "_font_size": self.font_size,
            "_icon_path": self.icon_path
        })
        with open(self.file_path, "w") as f:
            json.dump(self.data, f, indent=2)

    def load_data(self, path):
        if not os.path.exists(path):
            return {
                "folders": {}, "links": [],
                "_window_size": {"width": 960, "height": 680},
                "_popup_sizes": {},
                "_theme_color": "#0078D7",
                "_titlebar_color": "#0078D7",
                "_bg_color": "#1b1b1d",
                "_text_color": "#ffffff",
                "_button_color": "#3A3A3D",
                "_font_family": "Segoe UI Variable",
                "_font_size": 10,
                "_icon_path": ""
            }
        with open(path, "r") as f:
            data = json.load(f)
        data.setdefault("folders", {})
        data.setdefault("links", [])
        data.setdefault("_popup_sizes", {})
        return data

    def save_last_file(self, path):
        try:
            with open(LAST_FILE_STATE, "w") as f:
                json.dump({"last": rel_or_abs(path)}, f)
        except Exception:
            pass

    def load_last_file(self):
        try:
            if os.path.exists(LAST_FILE_STATE):
                with open(LAST_FILE_STATE, "r") as f:
                    return json.load(f).get("last")
        except Exception:
            return None

    # ------------- Popups -------------
    def input_popup(self, title, prompt):
        pop = tk.Toplevel(self.root)
        pop.title(title)
        pop.config(bg="#2b2b2b", padx=16, pady=12)
        pop.grab_set()
        tk.Label(pop, text=prompt, bg="#2b2b2b", fg="white", font=self.font_main).pack(pady=(4,6))
        e = ttk.Entry(pop, width=44, font=self.font_main); e.pack(pady=(0,8)); e.focus()
        v = tk.StringVar()
        def ok(): v.set(e.get().strip()); pop.destroy()
        ttk.Button(pop, text="OK", style="Primary.TButton", command=ok).pack(pady=(2,4))
        pop.bind("<Return>", lambda _: ok())
        center_window(pop, self.root); pop.wait_window()
        return v.get()

    def link_popup(self):
        pop = tk.Toplevel(self.root)
        pop.title("Add Link")
        pop.config(bg="#2b2b2b", padx=16, pady=12)
        pop.grab_set()
        tk.Label(pop, text="Link Name:", bg="#2b2b2b", fg="white", font=self.font_main).pack()
        name_e = ttk.Entry(pop, width=44, font=self.font_main); name_e.pack(pady=(0,6))
        tk.Label(pop, text="URL (http/https):", bg="#2b2b2b", fg="white", font=self.font_main).pack()
        url_e = ttk.Entry(pop, width=44, font=self.font_main); url_e.pack(pady=(0,8))
        name_e.focus()
        out = [None, None]
        def add():
            n, u = name_e.get().strip(), url_e.get().strip()
            if n and u: out[:] = [n,u]; pop.destroy()
        ttk.Button(pop, text="Add", style="Primary.TButton", command=add).pack(pady=4)
        pop.bind("<Return>", lambda _: add())
        center_window(pop, self.root); pop.wait_window()
        return out if out[0] else None

    def message(self, title, msg, level="info"):
        pop = tk.Toplevel(self.root); pop.title(title)
        pop.config(bg="#2b2b2b", padx=16, pady=12); pop.grab_set()
        color = self.theme_color if level!="error" else "#E81123"
        tk.Label(pop, text=title, font=(self.font_family, self.font_size+2, "bold"),
                 bg="#2b2b2b", fg=color).pack()
        tk.Label(pop, text=msg, font=self.font_main, bg="#2b2b2b", fg="white",
                 wraplength=380, justify="center").pack(pady=4)
        ttk.Button(pop, text="OK", style="Secondary.TButton", command=pop.destroy).pack(pady=4)
        center_window(pop, self.root); pop.wait_window()

    def confirm(self, msg):
        pop = tk.Toplevel(self.root); pop.title("Confirm")
        pop.config(bg="#2b2b2b", padx=16, pady=12); pop.grab_set()
        res = tk.BooleanVar(master=pop, value=False)
        tk.Label(pop, text="Confirm Action", font=(self.font_family, self.font_size+1, "bold"),
                 bg="#2b2b2b", fg="#FFD700").pack(pady=(2,4))
        tk.Label(pop, text=msg, font=self.font_main, bg="#2b2b2b", fg="white",
                 wraplength=380, justify="center").pack(pady=4)
        btns = tk.Frame(pop, bg="#2b2b2b"); btns.pack(pady=4)
        ttk.Button(btns, text="Yes", style="Primary.TButton",
                   command=lambda: [res.set(True), pop.destroy()]).grid(row=0, column=0, padx=8)
        ttk.Button(btns, text="No", style="Secondary.TButton",
                   command=pop.destroy).grid(row=0, column=1, padx=8)
        center_window(pop, self.root); pop.wait_window()
        return res.get()

    # ------------- Close -------------
    def on_close(self):
        self.save()
        self.save_last_file(self.file_path)
        self.root.destroy()

# small helper so webbrowser.open is imported only when needed
def webbrowser_open(url):
    import webbrowser
    webbrowser.open(url)

# ------------------- Run -------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = BookmarkManager(root)
    root.mainloop()





