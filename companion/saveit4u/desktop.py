"""Native desktop dashboard; no terminal, Python installation or ID entry for users."""

import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .ipc import request, MaintenanceError
from .runtime import install_directory

BG, SURFACE, TEXT, MUTED, ACCENT = "#101412", "#1c241c", "#f0f2e8", "#a7b09f", "#c1f17b"


def bytes_text(value):
    if value is None:
        return "Unknown"
    units = ("B", "KB", "MB", "GB", "TB")
    value = max(0, value)
    index = 0
    while value >= 1024 and index < 4:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


def eta_text(value):
    if value is None:
        return "Calculating…"
    minutes, seconds = divmod(int(value), 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m {seconds}s"


def open_extension_folder():
    folder = install_directory() / "extension"
    if os.name == "nt":
        os.startfile(str(folder))
    else:
        subprocess.Popen(["open" if os.sys.platform == "darwin" else "xdg-open", str(folder)])


class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"SaveIt4U {__version__}")
        self.root.geometry("1050x760")
        self.root.minsize(840, 660)
        self.root.configure(bg=BG)
        self.events = queue.Queue()
        self.stopped = threading.Event()
        self.jobs = {}
        self.rate_minutes = False
        self.last_snapshot = None
        self.progress_running = False
        self.configure_styles()
        self.build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.monitor, daemon=True).start()
        self.root.after(100, self.drain)

    def configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 11))
        style.configure("TButton", background="#303d26", foreground=TEXT, padding=(14, 9), borderwidth=0, font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#485b36")], foreground=[("disabled", "#727e67")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG)
        style.map("Accent.TButton", background=[("active", "#ddffa7")], foreground=[("disabled", "#66785a")])
        style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, padding=9)
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, rowheight=42, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background="#2d3828", foreground=ACCENT, padding=9)
        style.map("Treeview", background=[("selected", "#425b30")])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#2a3524", borderwidth=0)
        style.configure("TCombobox", fieldbackground=SURFACE, foreground=TEXT)

    def build(self):
        frame = ttk.Frame(self.root, padding=28)
        frame.pack(fill="both", expand=True)
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="↓  saveit4u", font=("Segoe UI", 29, "bold"), foreground=ACCENT).pack(side="left")
        self.connection = tk.Label(top, text="● Connecting", bg=BG, fg=ACCENT, font=("Segoe UI", 12, "bold"))
        self.connection.pack(side="right")
        self.message = ttk.Label(frame, text="Starting your download engine…", foreground=MUTED, wraplength=960)
        self.message.pack(anchor="w", pady=(8, 20))
        stats = ttk.Frame(frame)
        stats.pack(fill="x", pady=(0, 22))
        self.stat_values = {}
        for index, (key, label) in enumerate((("speed", "DOWNLOAD SPEED"), ("data", "DOWNLOADED / TOTAL"), ("eta", "TIME REMAINING"), ("network", "SYSTEM RECEIVE"))):
            block = tk.Frame(stats, bg=SURFACE, padx=14, pady=14)
            block.grid(row=0, column=index, sticky="nsew", padx=(0, 10 if index < 3 else 0))
            stats.columnconfigure(index, weight=1)
            tk.Label(block, text=label, bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
            value = tk.Label(block, text="—", bg=SURFACE, fg=TEXT, font=("Segoe UI", 16, "bold"))
            value.pack(anchor="w", pady=(5, 0))
            self.stat_values[key] = value
        link = ttk.Frame(frame)
        link.pack(fill="x", pady=(0, 18))
        self.url = ttk.Entry(link)
        self.url.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url.bind("<Return>", lambda event: self.inspect())
        self.find_button = ttk.Button(link, text="Choose quality", style="Accent.TButton", command=self.inspect)
        self.find_button.pack(side="right")
        self.table = ttk.Treeview(frame, columns=("title", "status", "progress", "speed", "eta"), show="headings", selectmode="browse", height=6)
        for key, label, width in (("title", "VIDEO", 360), ("status", "STATUS", 110), ("progress", "PROGRESS", 95), ("speed", "SPEED", 110), ("eta", "ETA", 105)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=60, stretch=key == "title")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", lambda event: self.update_selected())
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill="x", pady=(15, 8))
        self.details = ttk.Label(frame, text="Open a YouTube video; the extension shows quality choices automatically.", foreground=MUTED, wraplength=950)
        self.details.pack(anchor="w")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(15, 20))
        self.buttons = {}
        for action, label in (("pause", "Pause"), ("resume", "Resume / retry"), ("cancel", "Cancel"), ("open_folder", "Open folder")):
            button = ttk.Button(actions, text=label, command=lambda action=action: self.control(action))
            button.pack(side="left", padx=(0, 8))
            self.buttons[action] = button
        ttk.Button(actions, text="MB/s ↔ MB/min", command=self.toggle_units).pack(side="right")
        lower = ttk.Frame(frame)
        lower.pack(fill="x")
        ttk.Button(lower, text="Install / locate extension", command=self.extension_help).pack(side="left")
        ttk.Button(lower, text="Choose download folder", command=self.choose_folder).pack(side="left", padx=8)
        ttk.Button(lower, text="Clear finished", command=lambda: self.async_action("clear_finished")).pack(side="right")
        self.folder = ttk.Label(frame, text="", foreground=MUTED, font=("Segoe UI", 9), wraplength=950)
        self.folder.pack(anchor="w", pady=(12, 0))
        self.update_selected()

    def monitor(self):
        delay = 1
        while not self.stopped.is_set():
            try:
                state = request("snapshot")
                self.events.put(("snapshot", state))
                delay = 1
            except MaintenanceError as error:
                self.events.put(("updating", str(error)))
                return
            except Exception as error:
                self.events.put(("connection_error", f"{error} Retrying automatically in {delay}s."))
                delay = min(30, delay * 2)
            self.stopped.wait(delay)

    def async_action(self, action, **values):
        def work():
            try:
                result = request(action, **values)
                self.events.put(("inspect" if action == "inspect" else "action", result))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def drain(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "snapshot":
                self.render(value)
            elif kind == "connection_error":
                self.connection.configure(text="● Connection Error", fg="#ffae98")
                self.message.configure(text=value)
                for key in ("speed", "eta", "network"):
                    self.stat_values[key].configure(text="Unavailable")
            elif kind == "inspect":
                self.find_button.configure(state="normal")
                self.quality_dialog(value)
            elif kind == "error":
                self.find_button.configure(state="normal")
                messagebox.showerror("SaveIt4U", value, parent=self.root)
            elif kind == "action":
                self.message.configure(text="Your request was applied. Downloads continue in the background.")
            elif kind == "updating":
                self.close()
                return
        if not self.stopped.is_set():
            self.root.after(150, self.drain)

    def render(self, state):
        self.last_snapshot = state
        status = state["connection"]["state"] if state["ready"] else "Connection Error"
        self.connection.configure(text=f"● {status}", fg=ACCENT if status == "Connected" else MUTED if status == "Disconnected" else "#ffae98")
        self.message.configure(text=state["connection"]["message"] if state["ready"] else "A bundled component is missing. Reinstall SaveIt4U to repair it.")
        self.jobs = {job["id"]: job for job in state["jobs"]}
        for item in self.table.get_children():
            if item not in self.jobs:
                self.table.delete(item)
        for job in sorted(state["jobs"], key=lambda item: item["created"], reverse=True):
            values = (job["title"], job["status"].capitalize(), f"{job['percent']:.1f}%" if job["percent"] is not None else "Estimating…", self.rate(job["speed"]), eta_text(job["eta"]) if job["status"] == "downloading" else "—")
            if self.table.exists(job["id"]):
                self.table.item(job["id"], values=values)
            else:
                self.table.insert("", "end", iid=job["id"], values=values)
        if not self.table.selection() and state["jobs"]:
            active = next((job for job in state["jobs"] if job["status"] == "downloading"), state["jobs"][-1])
            self.table.selection_set(active["id"])
        network = state["network"]
        self.stat_values["network"].configure(text=self.rate(network["receive_rate"]) if network["available"] else "Unavailable")
        self.folder.configure(text=f"All new downloads save to: {state['output_dir']}  •  System receive includes traffic from other apps.")
        self.update_selected()

    def rate(self, value):
        return bytes_text((value or 0) * (60 if self.rate_minutes else 1)) + ("/min" if self.rate_minutes else "/s")

    def update_selected(self):
        selection = self.table.selection()
        job = self.jobs.get(selection[0]) if selection else None
        for action, button in self.buttons.items():
            allowed = bool(job)
            if action == "pause": allowed = job and job["status"] in {"queued", "downloading", "processing", "merging"}
            if action == "resume": allowed = job and job["status"] in {"paused", "failed"}
            if action == "cancel": allowed = job and job["status"] not in {"complete", "cancelled"}
            button.configure(state="normal" if allowed else "disabled")
        if not job:
            return
        self.stat_values["speed"].configure(text=self.rate(job["speed"]))
        total = ("~" if job.get("total_estimated") else "") + bytes_text(job["total"]) if job["total"] else "Estimating"
        self.stat_values["data"].configure(text=f"{bytes_text(job['downloaded'])} / {total}", font=("Segoe UI", 12, "bold"))
        self.stat_values["eta"].configure(text=eta_text(job["eta"]) if job["status"] == "downloading" else job["status"].capitalize())
        if job["percent"] is None and job["status"] == "downloading":
            if not self.progress_running:
                self.progress.configure(mode="indeterminate")
                self.progress.start(20)
                self.progress_running = True
        else:
            if self.progress_running:
                self.progress.stop()
                self.progress_running = False
            self.progress.configure(mode="determinate")
            self.progress["value"] = job["percent"] or 0
        detail = job.get("error") or job.get("warning") or (", ".join(job["files"]) if job["files"] else job["title"])
        self.details.configure(text=detail)

    def toggle_units(self):
        self.rate_minutes = not self.rate_minutes
        if self.last_snapshot:
            self.render(self.last_snapshot)

    def control(self, action):
        selected = self.table.selection()
        if selected:
            self.async_action(action, job_id=selected[0])

    def inspect(self):
        self.find_button.configure(state="disabled")
        self.message.configure(text="Reading available qualities and sizes…")
        self.async_action("inspect", url=self.url.get())

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Save all downloads here")
        if folder:
            selected = Path(folder)
            if selected.name.lower() != "saveit4u":
                selected /= "SaveIt4U"
            self.async_action("configure", output_dir=str(selected))

    def extension_help(self):
        open_extension_folder()
        messagebox.showinfo("Install the browser extension", "The extension folder is now open.\n\nIn Chrome or Edge, open Extensions → Manage extensions. Enable Developer mode, choose Load unpacked, and select this folder.\n\nNo commands or ID entry are needed. SaveIt4U connects automatically.\n\nWeb Store installation will replace these steps when the extension is published.", parent=self.root)

    def quality_dialog(self, metadata):
        window = tk.Toplevel(self.root)
        window.title("Choose quality — SaveIt4U")
        window.configure(bg=BG)
        window.geometry("600x460")
        ttk.Label(window, text=metadata["title"], wraplength=550, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=22, pady=20)
        choices = ttk.Treeview(window, columns=("quality", "format", "size"), show="headings", height=7, selectmode="browse")
        for key, label in (("quality", "QUALITY"), ("format", "FORMAT"), ("size", "SIZE")):
            choices.heading(key, text=label)
            choices.column(key, width=170)
        for index, quality in enumerate(metadata.get("qualities", [])):
            size = ("~" if quality["estimated"] else "") + bytes_text(quality["size"]) if quality["size"] else "Unknown"
            choices.insert("", "end", iid=str(index), values=(quality["label"], quality["container"].upper(), size))
        choices.pack(fill="both", expand=True, padx=22)
        ttk.Label(window, text="Select a quality and click Download. Existing files are never overwritten.", foreground=MUTED, wraplength=550).pack(padx=22, pady=12)
        def start():
            selected = choices.selection()
            if not selected:
                return
            quality = metadata["qualities"][int(selected[0])]
            self.async_action("enqueue", request={"url": metadata["url"], "quality": str(quality["height"]), "container": quality["container"], "mode": "video"})
            window.destroy()
        ttk.Button(window, text="↓ Download", style="Accent.TButton", command=start).pack(pady=(0, 18))
        choices.bind("<Double-1>", lambda event: start())

    def close(self):
        self.stopped.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    Dashboard().run()


if __name__ == "__main__":
    main()
