#!/usr/bin/env python3
"""
Conversation Network Tool (Multi-Client, Persistent, Colored)
-------------------------------------------------------------
Features:
- Multi-client server: listens on a port; displays each incoming message with IP and username.
- Client: connect to a server and chat with a username.
- Main feed shows all messages; per-IP threads maintained; reply to a specific IP from server.
- Encryption (Fernet) optional; settings persisted; auto-install missing deps; colored terminal.
- Saves known peers (ip->username, last_seen) to known_peers.json.
- Decorative startup banner: "Created with ChatGPT".
"""

import os, sys, socket, threading, time, subprocess, json, queue
from datetime import datetime

# ============================
# Dependency Installer
# ============================
def ensure_package(pkg_name):
    import importlib.util
    if importlib.util.find_spec(pkg_name) is None:
        ans = input(f"Module '{pkg_name}' not found. Install it now? (y/n): ").strip().lower()
        if ans.startswith("y"):
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])
                print(f"✅ '{pkg_name}' installed successfully.")
            except Exception as e:
                print(f"❌ Failed to install '{pkg_name}': {e}")
        else:
            print(f"⚠️ '{pkg_name}' not installed — some features may not work.")

for pkg in ["requests", "psutil", "cryptography", "colorama"]:
    ensure_package(pkg)

import requests
import psutil
from cryptography.fernet import Fernet, InvalidToken
from colorama import init as colorama_init, Fore, Style

colorama_init(autoreset=True)

# ============================
# Decorative Banner
# ============================
def show_banner():
    print(Fore.CYAN + "───────────────────────────────────────────────")
    print(Fore.WHITE + Style.BRIGHT + "✨  Conversation Network Tool")
    print(Fore.YELLOW + "   Created with ChatGPT")
    print(Fore.CYAN + "───────────────────────────────────────────────" + Style.RESET_ALL)

# ============================
# Settings & Persistence
# ============================
SETTINGS_FILE = "settings.json"
PEERS_FILE = "known_peers.json"
SETTINGS_DEFAULT = {
    "port": 5000,
    "key_path": None,
    "encryption_enabled": False,
    "last_mode": None,
    "username": None
}

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(Fore.YELLOW + f"⚠️ File '{path}' corrupted. Resetting.")
    return default.copy()

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(Fore.YELLOW + f"⚠️ Failed to save '{path}': {e}")

SETTINGS = load_json(SETTINGS_FILE, SETTINGS_DEFAULT)
PEERS = load_json(PEERS_FILE, {})  # ip -> {"username": str, "last_seen": iso, "messages": int}

BUFFER_SIZE = 4096
SEPARATOR = "<SEPARATOR>"
FERNET = None
ENABLED_ENCRYPTION = SETTINGS.get("encryption_enabled", False)
KEY_PATH = SETTINGS.get("key_path", None)

# Thread-safe structures
MAIN_FEED = queue.Queue()   # tuples: (timestamp, ip, username, text, direction)
THREADS = {}                # ip -> list of (timestamp, username, text, direction)

# ============================
# Utility Functions
# ============================
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

def get_public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        return "Unavailable (no Internet)"

def ping_host(host="8.8.8.8", count=3):
    try:
        import platform
        flag = "-n" if platform.system().lower() == "windows" else "-c"
        result = subprocess.run(["ping", flag, str(count), host], capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return f"Ping failed: {e}"

def check_port_open(public_ip, port):
    try:
        r = requests.get(
            f"https://api.yougetsignal.com/web/sitescan.php?remoteAddress={public_ip}&portNumber={port}",
            timeout=6
        )
        t = r.text.lower()
        if '"open":true' in t:
            return "✅ Port appears OPEN to the Internet"
        elif '"open":false' in t:
            return "❌ Port appears CLOSED (check router forwarding)"
        return "⚠️ Unable to determine port status"
    except Exception:
        return "⚠️ Could not check port (no Internet)"

def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_peer(ip, username):
    PEERS[ip] = {
        "username": username,
        "last_seen": datetime.utcnow().isoformat(),
        "messages": PEERS.get(ip, {}).get("messages", 0)
    }
    save_json(PEERS_FILE, PEERS)

def inc_peer_msg(ip):
    if ip not in PEERS:
        PEERS[ip] = {"username": None, "last_seen": datetime.utcnow().isoformat(), "messages": 0}
    PEERS[ip]["messages"] = PEERS[ip].get("messages", 0) + 1
    PEERS[ip]["last_seen"] = datetime.utcnow().isoformat()
    save_json(PEERS_FILE, PEERS)

# ============================
# Encryption
# ============================
def generate_key_file(path="fernet.key"):
    key = Fernet.generate_key()
    with open(path, "wb") as f:
        f.write(key)
    print(Fore.GREEN + f"🔐 Encryption key generated and saved to {path}")

def load_key_file(path):
    global FERNET, ENABLED_ENCRYPTION, KEY_PATH
    if not os.path.exists(path):
        print(Fore.RED + "❌ Key file not found.")
        return
    try:
        with open(path, "rb") as f:
            key = f.read().strip()
        FERNET = Fernet(key)
        ENABLED_ENCRYPTION = True
        KEY_PATH = path
        SETTINGS["key_path"] = path
        SETTINGS["encryption_enabled"] = True
        save_json(SETTINGS_FILE, SETTINGS)
        print(Fore.GREEN + f"✅ Key loaded from {path}. Encryption ENABLED.")
    except Exception as e:
        print(Fore.RED + f"❌ Failed to load key: {e}")

def encrypt_bytes(data: bytes):
    if ENABLED_ENCRYPTION and FERNET:
        return FERNET.encrypt(data)
    return data

def decrypt_bytes(data: bytes):
    if ENABLED_ENCRYPTION and FERNET:
        try:
            return FERNET.decrypt(data)
        except InvalidToken:
            print(Fore.RED + "[!] Decryption failed (wrong key?)")
            return data
    return data

# ============================
# Message Protocol
# ============================
# Simple text frames: either CHAT or FILE header lines
# CHAT header: "CHAT<SEP><username><SEP><text>"
# FILE header: "FILE<SEP><username><SEP><filename><SEP><filesize>"
# Encrypted if enabled. Username supplied by sender.

def make_chat(username, text):
    return f"CHAT{SEPARATOR}{username}{SEPARATOR}{text}".encode("utf-8")

def parse_chat(frame_text):
    _, username, text = frame_text.split(SEPARATOR, 2)
    return username, text

def make_file_header(username, filename, size):
    return f"FILE{SEPARATOR}{username}{SEPARATOR}{filename}{SEPARATOR}{size}".encode("utf-8")

def parse_file_header(frame_text):
    _, username, filename, size = frame_text.split(SEPARATOR, 3)
    return username, filename, int(size)

# ============================
# Server: Multi-client
# ============================
class ClientHandler(threading.Thread):
    def __init__(self, conn, addr):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr  # (ip, port)
        self.ip = addr[0]

    def run(self):
        try:
            while True:
                frame = self.conn.recv(BUFFER_SIZE)
                if not frame:
                    break
                frame = decrypt_bytes(frame)
                try:
                    text = frame.decode("utf-8", errors="ignore")
                except Exception:
                    continue
                if text.startswith("CHAT" + SEPARATOR):
                    uname, msg = parse_chat(text)
                    log_peer(self.ip, uname)
                    inc_peer_msg(self.ip)
                    # Save to per-IP thread
                    THREADS.setdefault(self.ip, [])
                    THREADS[self.ip].append((timestamp(), uname, msg, "in"))
                    # Main feed
                    MAIN_FEED.put((timestamp(), self.ip, uname, msg, "in"))
                    # Display immediate
                    print(Fore.CYAN + f"\n[{timestamp()}] {self.ip}  {Style.BRIGHT}[{uname}]")
                    print(Fore.WHITE + f"{msg}\n" + Style.RESET_ALL + "You: ", end="")
                elif text.startswith("FILE" + SEPARATOR):
                    uname, filename, size = parse_file_header(text)
                    remaining = size
                    data = b""
                    while remaining > 0:
                        chunk = self.conn.recv(min(BUFFER_SIZE, remaining))
                        if not chunk:
                            break
                        data += chunk
                        remaining -= len(chunk)
                    data = decrypt_bytes(data)
                    os.makedirs("received_files", exist_ok=True)
                    path = os.path.join("received_files", filename)
                    with open(path, "wb") as f:
                        f.write(data)
                    log_peer(self.ip, uname)
                    inc_peer_msg(self.ip)
                    THREADS.setdefault(self.ip, [])
                    THREADS[self.ip].append((timestamp(), uname, f"[file] {filename} ({size} bytes)", "in"))
                    MAIN_FEED.put((timestamp(), self.ip, uname, f"[file] {filename} ({size} bytes)", "in"))
                    print(Fore.MAGENTA + f"\n[{timestamp()}] {self.ip}  {Style.BRIGHT}[{uname}] sent file: {filename}\n" + Style.RESET_ALL + "You: ", end="")
                else:
                    # Unknown frame
                    pass
        except Exception as e:
            print(Fore.YELLOW + f"\n[Server handler error from {self.ip}] {e}")
        finally:
            try:
                self.conn.close()
            except:
                pass

class MultiServer:
    def __init__(self, port, username):
        self.port = port
        self.username = username
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}  # ip -> socket

    def start(self):
        local_ip = get_local_ip()
        public_ip = get_public_ip()
        print(Fore.CYAN + "───────────────────────────────────────────────")
        print(Fore.WHITE + Style.BRIGHT + "✨  Conversation Network Tool")
        print(Fore.YELLOW + "   Created with ChatGPT")
        print(Fore.CYAN + "───────────────────────────────────────────────" + Style.RESET_ALL)

        print(Fore.GREEN + f"\n🖥️ SERVER MODE\nLocal IP : {local_ip}\nPublic IP: {public_ip}")
        print(Fore.YELLOW + f"⚠️ Connection is NOT encrypted unless a key is loaded and enabled.\n")
        print(Fore.BLUE + f"🔍 Checking Internet port {self.port} ...")
        print(check_port_open(public_ip, self.port))

        self.s.bind(("0.0.0.0", self.port))
        self.s.listen(10)
        print(Fore.GREEN + f"📡 Listening on port {self.port} ...")

        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.input_loop()  # main thread handles input

    def accept_loop(self):
        while True:
            conn, addr = self.s.accept()
            ip = addr[0]
            self.clients[ip] = conn
            print(Fore.GREEN + f"\n✅ Incoming connection from {ip}. You can reply with /to {ip} <message>")
            handler = ClientHandler(conn, addr)
            handler.start()

    def input_loop(self):
        help_text = (
            "\nCommands:\n"
            "  /all <message>         - send to all connected clients\n"
            "  /to <ip> <message>     - send to a specific IP\n"
            "  /send <ip> <filepath>  - send a file to specific IP\n"
            "  /peers                 - list known peers\n"
            "  /threads               - list IPs with per-thread counts\n"
            "  /show <ip>             - display conversation with a specific IP\n"
            "  /enc on|off            - toggle encryption\n"
            "  /help                  - show this help\n"
            "  (just type to broadcast to all)\n"
        )
        print(help_text)
        while True:
            try:
                msg = input(Fore.YELLOW + "You: " + Style.RESET_ALL)
            except (EOFError, KeyboardInterrupt):
                print("\nShutting down server input.")
                break
            if not msg:
                continue

            if msg.startswith("/help"):
                print(help_text)
                continue
            if msg.startswith("/peers"):
                if not PEERS:
                    print("No peers yet.")
                else:
                    for ip, meta in PEERS.items():
                        print(f"{ip}  [{meta.get('username')}]  last_seen={meta.get('last_seen')}  messages={meta.get('messages',0)}")
                continue
            if msg.startswith("/threads"):
                if not THREADS:
                    print("No conversations yet.")
                else:
                    for ip, items in THREADS.items():
                        print(f"{ip}: {len(items)} messages")
                continue
            if msg.startswith("/show "):
                ip = msg.split(" ", 1)[1].strip()
                thread = THREADS.get(ip, [])
                if not thread:
                    print(f"No conversation with {ip}.")
                else:
                    print(Fore.CYAN + f"--- Conversation with {ip} ---")
                    for ts, uname, text, direction in thread[-200:]:
                        tag = ">>" if direction == "out" else "<<"
                        print(f"{ts} {tag} [{uname}] {text}")
                    print(Fore.CYAN + "--- End ---" + Style.RESET_ALL)
                continue
            if msg.startswith("/enc "):
                arg = msg.split(" ", 1)[1].strip().lower()
                global ENABLED_ENCRYPTION
                if arg in ("on","true","1"):
                    ENABLED_ENCRYPTION = True
                    SETTINGS["encryption_enabled"] = True
                    save_json(SETTINGS_FILE, SETTINGS)
                    print("Encryption ENABLED.")
                elif arg in ("off","false","0"):
                    ENABLED_ENCRYPTION = False
                    SETTINGS["encryption_enabled"] = False
                    save_json(SETTINGS_FILE, SETTINGS)
                    print("Encryption DISABLED.")
                else:
                    print("Usage: /enc on|off")
                continue
            if msg.startswith("/to "):
                try:
                    _, rest = msg.split(" ", 1)
                    ip, text = rest.split(" ", 1)
                except ValueError:
                    print("Usage: /to <ip> <message>")
                    continue
                conn = self.clients.get(ip)
                if not conn:
                    print(f"Not connected to {ip}.")
                    continue
                frame = make_chat(SETTINGS.get("username","User"), text)
                frame = encrypt_bytes(frame)
                try:
                    conn.sendall(frame)
                    THREADS.setdefault(ip, [])
                    THREADS[ip].append((timestamp(), SETTINGS.get("username","User"), text, "out"))
                    MAIN_FEED.put((timestamp(), ip, SETTINGS.get("username","User"), text, "out"))
                    print(Fore.GREEN + f"Sent to {ip}.")
                except Exception as e:
                    print(Fore.RED + f"Send error to {ip}: {e}")
                continue
            if msg.startswith("/send "):
                try:
                    _, rest = msg.split(" ", 1)
                    ip, path = rest.split(" ", 1)
                except ValueError:
                    print("Usage: /send <ip> <filepath>")
                    continue
                conn = self.clients.get(ip)
                if not conn:
                    print(f"Not connected to {ip}.")
                    continue
                if not os.path.exists(path):
                    print("File not found.")
                    continue
                data = open(path, "rb").read()
                payload = encrypt_bytes(data)
                header = make_file_header(SETTINGS.get("username","User"), os.path.basename(path), len(payload))
                header = encrypt_bytes(header)
                try:
                    conn.sendall(header)
                    time.sleep(0.02)
                    conn.sendall(payload)
                    THREADS.setdefault(ip, [])
                    THREADS[ip].append((timestamp(), SETTINGS.get("username","User"), f"[file] {os.path.basename(path)}", "out"))
                    MAIN_FEED.put((timestamp(), ip, SETTINGS.get("username","User"), f"[file] {os.path.basename(path)}", "out"))
                    print(Fore.GREEN + f"File sent to {ip}.")
                except Exception as e:
                    print(Fore.RED + f"File send error to {ip}: {e}")
                continue

            # Default: broadcast to all
            if self.clients:
                frame = make_chat(SETTINGS.get("username","User"), msg)
                frame = encrypt_bytes(frame)
                dead = []
                for ip, conn in self.clients.items():
                    try:
                        conn.sendall(frame)
                        THREADS.setdefault(ip, [])
                        THREADS[ip].append((timestamp(), SETTINGS.get("username","User"), msg, "out"))
                    except Exception:
                        dead.append(ip)
                for ip in dead:
                    try:
                        self.clients[ip].close()
                    except:
                        pass
                    del self.clients[ip]
                print(Fore.GREEN + f"Broadcast to {len(self.clients)} client(s).")
            else:
                print("No clients connected yet.")

# ============================
# Client
# ============================
def client_mode(server_ip, port, username):
    print(Fore.CYAN + "───────────────────────────────────────────────")
    print(Fore.WHITE + Style.BRIGHT + "✨  Conversation Network Tool")
    print(Fore.YELLOW + "   Created with ChatGPT")
    print(Fore.CYAN + "───────────────────────────────────────────────" + Style.RESET_ALL)

    print(Fore.GREEN + f"\n💻 CLIENT MODE\nConnecting to {server_ip}:{port}")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server_ip, port))
    print(Fore.GREEN + "✅ Connected. Type messages; use /send <filepath> to send files. /quit to exit.")
    # Receiver thread
    def rx():
        try:
            while True:
                frame = s.recv(BUFFER_SIZE)
                if not frame:
                    break
                frame = decrypt_bytes(frame)
                text = frame.decode("utf-8", errors="ignore")
                if text.startswith("CHAT" + SEPARATOR):
                    uname, msg = parse_chat(text)
                    print(Fore.CYAN + f"\n[{timestamp()}] [{uname}]")
                    print(Fore.WHITE + f"{msg}\n" + Style.RESET_ALL + "You: ", end="")
                elif text.startswith("FILE" + SEPARATOR):
                    uname, filename, size = parse_file_header(text)
                    data = b""
                    remaining = size
                    while remaining > 0:
                        chunk = s.recv(min(BUFFER_SIZE, remaining))
                        if not chunk:
                            break
                        data += chunk
                        remaining -= len(chunk)
                    data = decrypt_bytes(data)
                    os.makedirs("received_files", exist_ok=True)
                    with open(os.path.join("received_files", filename), "wb") as f:
                        f.write(data)
                    print(Fore.MAGENTA + f"\n[{timestamp()}] [{uname}] sent file: {filename}\n" + Style.RESET_ALL + "You: ", end="")
        except Exception as e:
            print(Fore.YELLOW + f"\n[Client receiver error] {e}")
        finally:
            try:
                s.close()
            except:
                pass
    threading.Thread(target=rx, daemon=True).start()

    while True:
        try:
            msg = input(Fore.YELLOW + "You: " + Style.RESET_ALL)
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if msg.strip().lower() == "/quit":
            break
        if msg.startswith("/send "):
            path = msg.split(" ", 1)[1].strip()
            if not os.path.exists(path):
                print("File not found.")
                continue
            data = open(path, "rb").read()
            payload = encrypt_bytes(data)
            header = make_file_header(username, os.path.basename(path), len(payload))
            header = encrypt_bytes(header)
            try:
                s.sendall(header); time.sleep(0.02); s.sendall(payload)
                print(Fore.GREEN + f"File sent: {os.path.basename(path)}")
            except Exception as e:
                print(Fore.RED + f"File send error: {e}")
            continue
        # normal message
        frame = make_chat(username, msg)
        frame = encrypt_bytes(frame)
        try:
            s.sendall(frame)
        except Exception as e:
            print(Fore.RED + f"Send error: {e}")
            break

# ============================
# Instructions & Tests
# ============================
def connection_test():
    print(Fore.CYAN + "\n🌐 Connection Test")
    public_ip = get_public_ip()
    local_ip = get_local_ip()
    print(Fore.WHITE + f"Local IP : {local_ip}\nPublic IP: {public_ip}")
    print("\nTesting ping to 8.8.8.8 ...")
    print(ping_host("8.8.8.8", 3))

def show_instructions():
    print(Fore.WHITE + """
📘 INSTRUCTIONS
---------------
SERVER (multi-client):
  • Start server and share your public IP and port.
  • Each incoming message shows IP and username, then the message on the next line.
  • Reply to a specific IP with:   /to <ip> <message>
  • Send a file to an IP:          /send <ip> <path>
  • Broadcast to everyone: just type a message.
  • Conversations are tracked per IP; use /show <ip> to view a thread.
  • Known peers are stored in known_peers.json.

CLIENT:
  • Connect to the server IP and port.
  • Your username prefixes every message.
  • Send files with: /send <path>
  • Exit with: /quit

SECURITY:
  • Use encryption by loading a shared Fernet key on both sides.
  • Toggle encryption with: /enc on|off (server) or menu option (client pre-connection).
  • Warning: without encryption, traffic is plain text.
""")

# ============================
# Menu
# ============================
def main_menu():
    global ENABLED_ENCRYPTION
    show_banner()  # Show decorative "Created with ChatGPT" banner on startup

    # Username prompt
    if not SETTINGS.get("username"):
        name = input("Enter your username: ").strip() or "User"
        SETTINGS["username"] = name
        save_json(SETTINGS_FILE, SETTINGS)
    else:
        print(Fore.CYAN + f"Hello, {SETTINGS['username']}!")

    while True:
        print(Fore.BLUE + "\nConversation Network Tool (Multi-Client, Persistent, Colored)")
        print(Fore.BLUE + "================================================================")
        print("1) Start Server")
        print("2) Start Client")
        print("3) Generate Encryption Key File")
        print("4) Load Encryption Key File")
        print(f"5) Toggle Encryption On/Off (Currently {'ON' if ENABLED_ENCRYPTION else 'OFF'})")
        print("6) Connection Test")
        print("7) Show Instructions")
        print("8) Exit")
        choice = input("Select option (1-8): ").strip()

        if choice == "1":
            try:
                port = int(input(f"Enter port (default {SETTINGS.get('port',5000)}): ") or SETTINGS.get("port",5000))
            except Exception:
                port = SETTINGS.get("port",5000)
            SETTINGS["port"] = port
            SETTINGS["last_mode"] = "server"
            save_json(SETTINGS_FILE, SETTINGS)
            MultiServer(port, SETTINGS["username"]).start()

        elif choice == "2":
            ip = input("Enter server IP: ").strip()
            try:
                port = int(input(f"Enter port (default {SETTINGS.get('port',5000)}): ") or SETTINGS.get("port",5000))
            except Exception:
                port = SETTINGS.get("port",5000)
            SETTINGS["port"] = port
            SETTINGS["last_mode"] = "client"
            save_json(SETTINGS_FILE, SETTINGS)
            client_mode(ip, port, SETTINGS["username"])

        elif choice == "3":
            path = input("Enter key file path (default fernet.key): ").strip() or "fernet.key"
            generate_key_file(path)

        elif choice == "4":
            path = input("Enter key file path to load: ").strip()
            load_key_file(path)

        elif choice == "5":
            ENABLED_ENCRYPTION = not ENABLED_ENCRYPTION
            SETTINGS["encryption_enabled"] = ENABLED_ENCRYPTION
            save_json(SETTINGS_FILE, SETTINGS)
            print("Encryption " + ("ENABLED." if ENABLED_ENCRYPTION else "DISABLED."))

        elif choice == "6":
            connection_test()

        elif choice == "7":
            show_instructions()

        elif choice == "8":
            print("👋 Goodbye.")
            save_json(SETTINGS_FILE, SETTINGS)
            break

        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main_menu()
