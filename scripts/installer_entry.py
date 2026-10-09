"""SaveIt4U's one-click, self-contained Windows installer."""

import argparse
import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion"))
from saveit4u.installation import default_install_directory, install_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent", action="store_true", help="Developer installation test only")
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--no-register", action="store_true", help="Developer isolation: do not change browser registration")
    parser.add_argument("--result-file", type=Path)
    args = parser.parse_args()
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1] / "build" / "installer"))
    archive = resources / "payload.zip"
    expected = (resources / "payload.sha256").read_text(encoding="ascii").strip()
    destination = args.install_dir or default_install_directory()
    options = {"register": lambda *a, **k: None, "shortcuts": lambda *a: None} if args.no_register else {}
    if args.silent:
        try:
            target = install_payload(archive, destination, expected, **options)
            result = {"ok": True, "directory": str(target)}
            code = 0
        except Exception as error:
            result, code = {"ok": False, "error": str(error)}, 1
        if args.result_file:
            args.result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return code
    root = tk.Tk()
    root.title("Install SaveIt4U")
    root.geometry("590x430")
    root.resizable(False, False)
    root.configure(bg="#101412")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TButton", padding=12, background="#c1f17b", foreground="#16200f", font=("Segoe UI", 11, "bold"))
    tk.Label(root, text="↓  saveit4u", bg="#101412", fg="#c1f17b", font=("Segoe UI", 30, "bold")).pack(anchor="w", padx=30, pady=(26, 8))
    tk.Label(root, text="Your downloads. One simple installation.", bg="#101412", fg="#f0f2e8", font=("Segoe UI", 16)).pack(anchor="w", padx=30)
    tk.Label(root, text="Includes the download engine, video/audio tools and automatic\nChrome / Edge connection. No commands or pairing codes.", justify="left", bg="#101412", fg="#aab49e", font=("Segoe UI", 11)).pack(anchor="w", padx=30, pady=14)
    path = tk.StringVar(value=str(destination))
    tk.Label(root, textvariable=path, bg="#101412", fg="#aab49e", wraplength=520, justify="left").pack(anchor="w", padx=30)
    message = tk.StringVar(value="Click Install. Then add the browser extension if you haven't already.")
    tk.Label(root, textvariable=message, bg="#101412", fg="#d7edc2", wraplength=520, justify="left", font=("Segoe UI", 11)).pack(anchor="w", padx=30, pady=16)
    events = queue.Queue()
    target = {"path": None}
    button = ttk.Button(root, text="Install SaveIt4U")
    button.pack(anchor="w", padx=30, pady=5)
    installing = {"active": False}
    def install():
        installing["active"] = True
        button.configure(state="disabled")
        chosen_path = Path(path.get())
        def work():
            try:
                result = install_payload(archive, chosen_path, expected, progress=lambda value: events.put(("status", value)), **options)
                events.put(("complete", result))
            except Exception as error:
                events.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()
    def launch():
        subprocess.Popen([str(target["path"] / "SaveIt4U.exe")])
        root.destroy()
    button.configure(command=install)
    def drain():
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == "status": message.set(value)
            elif kind == "complete":
                installing["active"] = False
                target["path"] = value
                button.configure(text="Open SaveIt4U", command=launch, state="normal")
                message.set("Installed and paired automatically. Open SaveIt4U to see the connection status and add the extension.")
            else:
                installing["active"] = False
                button.configure(state="normal")
                message.set(value + " If updating, close Chrome, Edge and SaveIt4U first, then retry.")
        root.after(150, drain)
    root.protocol("WM_DELETE_WINDOW", lambda: None if installing["active"] else root.destroy())
    root.after(100, drain)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
