#!/usr/bin/env python3
"""PalmClix for Windows — the original 1990s camera-shaped interface.

A frameless, camera-shaped window drawn from the original artwork. Every
option lives in the right-click menu (File / Edit / View / Go / Camera /
Window) and in keyboard shortcuts, mirroring the macOS menu bar.

USB work is done by the same read-only Python backend used on macOS
(palmclix.py), run as a child process so the window never freezes.
"""
from __future__ import annotations

import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import tkinter as tk
import uuid
from datetime import datetime
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

APP_VERSION = "1.1.0"
W, H = 538, 480
IS_WINDOWS = os.name == "nt"
KEY = (255, 0, 254)  # transparent "chroma key" color outside the camera body
KEY_HEX = "#ff00fe"

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BUNDLE = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(sys.executable).parent))
    ASSETS = BUNDLE / "Assets"
    ICON_PNG = BUNDLE / "Artwork" / "PalmClix_icon_1024.png"
    APP_DIR = pathlib.Path(sys.executable).parent
else:
    REPO = pathlib.Path(__file__).resolve().parent.parent
    ASSETS = REPO / "Sources" / "PalmClix" / "Assets"
    ICON_PNG = REPO / "Artwork" / "PalmClix_icon_1024.png"
    APP_DIR = REPO

BUTTONS = [  # name, x, y (top-left in artwork pixels), w, h — identical to macOS
    ("About", 466, 134, 36, 37),
    ("Minimize", 36, 170, 36, 37),
    ("Exit", 466, 176, 36, 37),
    ("Download", 173, 393, 42, 36),
    ("Save", 269, 393, 42, 36),
    ("Twain", 223, 393, 42, 36),
    ("SelectAll", 319, 399, 26, 24),
    ("ImageAdjust", 347, 399, 26, 24),
    ("PreviousPage", 61, 407, 87, 32),
    ("NextPage", 391, 407, 87, 32),
]
TIPS = {
    "Download": "Import photographs directly from PalmClix (Ctrl+D)",
    "Save": "Save selected photographs to a folder (Ctrl+S)",
    "ImageAdjust": "Open selected photographs in your image viewer (Ctrl+O)",
    "SelectAll": "Select or deselect every photograph (Ctrl+A)",
    "PreviousPage": "Previous gallery page (Ctrl+[)",
    "NextPage": "Next gallery page (Ctrl+])",
    "Twain": "About the legacy Windows TWAIN feature",
    "About": "About PalmClix",
    "Minimize": "Minimize PalmClix",
    "Exit": "Quit PalmClix (Alt+F4)",
}
FORMATS = [("png", "PNG · lossless"), ("jpeg", "JPEG · compact"), ("both", "PNG + JPEG · both")]
PROFILES = [("dsc-matched", "DSC-matched · improved"), ("legacy", "Original v0.4 · legacy")]


def settings_path() -> pathlib.Path:
    base = pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home() / ".config")
    return base / "PalmClix" / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict):
    try:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def default_pictures() -> pathlib.Path:
    return pathlib.Path.home() / "Pictures"


def display_path(path: pathlib.Path) -> str:
    home = str(pathlib.Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home) else text


def load_font(size: int):
    for name in ("consolab.ttf", "courbd.ttf", "DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def backend_command(args: list[str]) -> list[str]:
    """The packaged .exe re-launches itself in backend mode; source runs palmclix.py."""
    if FROZEN:
        helper = APP_DIR / ("palmclix_backend.exe" if IS_WINDOWS else "palmclix_backend")
        return [str(helper), *args]
    return [sys.executable, str(APP_DIR / "palmclix.py"), *args]


def popen_flags() -> dict:
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


class PalmClixApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.fmt = self.settings.get("format", "png")
        self.profile = self.settings.get("profile", "dsc-matched")
        parent = self.settings.get("import_parent")
        self.import_parent = pathlib.Path(parent) if parent else None
        self.status = "Ready — connect PalmClix"
        self.progress = "Download →"
        self.fraction = 0.0
        self.photos: list[pathlib.Path] = []
        self.selected: set[int] = set()
        self.page = 0
        self.busy = False
        self.hovered = None
        self.pressed = None
        self.drag_origin = None
        self.log: list[str] = []
        self.last_import: pathlib.Path | None = None
        self.probe_next = False
        self.events: queue.Queue = queue.Queue()
        self.process = None
        self.backend_error = None
        self.excluded = 0
        self.import_count = 0
        self.recovery_saved = False
        self.prior = ([], set(), 0)
        self.fmt_var = tk.StringVar(value=self.fmt)
        self.profile_var = tk.StringVar(value=self.profile)

        self.images = {}
        self.thumbs = {}
        self.font_small = load_font(11)
        self.load_artwork()
        self.build_window()
        self.build_menu()
        self.bind_keys()

        last = self.settings.get("last_import")
        if last and pathlib.Path(last).is_dir():
            self.last_import = pathlib.Path(last)
            self.photos = self.photo_files(self.last_import)
            if self.photos:
                self.status = f"Last import — {len(self.photos)} photos"
                self.progress = "Download for a new session • Ctrl+O: View"
                self.fraction = 1.0
        self.render()
        self.root.after(80, self.poll_events)
        self.check_camera(announce=False)

    # ------------------------------------------------------------------ setup
    def load_artwork(self):
        def asset(name):
            path = ASSETS / f"{name}.png"
            return Image.open(path).convert("RGBA") if path.exists() else None

        body = asset("MainShaped") or asset("Main")
        if body is None:
            raise SystemExit(f"PalmClix artwork not found in {ASSETS}")
        # Flatten onto the chroma-key color; fully transparent pixels become KEY.
        backdrop = Image.new("RGBA", (W, H), KEY + (255,))
        alpha = body.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        backdrop.paste(body, (0, 0), alpha)
        self.images["body"] = backdrop.convert("RGB")
        for name, *_ in BUTTONS:
            for variant in range(1, 5):
                img = asset(f"{name}{variant}")
                if img is not None:
                    self.images[f"{name}{variant}"] = img
        for name in ("ImageFrame1", "ImageFrame2", "Progress1", "Progress2"):
            img = asset(name)
            if img is not None:
                self.images[name] = img

    def build_window(self):
        root = self.root
        root.title("PalmClix")
        root.overrideredirect(True)
        root.configure(bg=KEY_HEX)
        if IS_WINDOWS:
            root.attributes("-transparentcolor", KEY_HEX)
        if ICON_PNG.exists():
            try:
                self.icon = ImageTk.PhotoImage(Image.open(ICON_PNG).resize((64, 64)))
                root.iconphoto(True, self.icon)
            except Exception:
                pass
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = self.settings.get("window_pos", [(sw - W) // 2, (sh - H) // 2])
        x = min(max(0, int(x)), max(0, sw - W))
        y = min(max(0, int(y)), max(0, sh - H))
        root.geometry(f"{W}x{H}+{x}+{y}")
        self.canvas = tk.Canvas(root, width=W, height=H, bg=KEY_HEX, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.frame_item = self.canvas.create_image(0, 0, anchor="nw")
        c = self.canvas
        c.bind("<Motion>", self.on_motion)
        c.bind("<Leave>", lambda e: self.set_hover(None))
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Button-3>", self.show_menu)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.bind("<Map>", self.on_map)
        self.tip = None
        if IS_WINDOWS:
            root.after(20, self.make_taskbar_window)

    def make_taskbar_window(self):
        """Frameless Tk windows are hidden from the taskbar; give it a taskbar button."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x00040000, 0x00000080
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
            self.hwnd = hwnd
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
            self.root.after(30, self.root.focus_force)
        except Exception:
            self.hwnd = None

    def build_menu(self):
        m = tk.Menu(self.root, tearoff=False)
        self.menu = m

        def sub(label):
            menu = tk.Menu(m, tearoff=False)
            m.add_cascade(label=label, menu=menu)
            return menu

        f = sub("File")
        f.add_command(label="Import from Camera…", accelerator="Ctrl+D", command=lambda: self.handle("Download"))
        f.add_command(label="Import Offline Demo…", accelerator="Ctrl+Shift+D", command=lambda: self.start_transfer(demo=True))
        f.add_separator()
        f.add_command(label="Open Selected Photos", accelerator="Ctrl+O", command=lambda: self.handle("ImageAdjust"))
        f.add_command(label="Save Selected Photos…", accelerator="Ctrl+S", command=lambda: self.handle("Save"))
        f.add_command(label="Show Latest Import in Explorer", accelerator="Ctrl+Shift+R", command=self.reveal_import)
        f.add_separator()
        f.add_command(label="", state="disabled")  # "Saving imports to …"
        self.folder_index = f.index("end")
        f.add_command(label="Change Import Folder…", command=self.choose_import_folder)
        f.add_command(label="Reset Import Folder to Pictures", command=self.reset_import_folder)
        f.add_separator()
        f.add_command(label="Quit PalmClix", accelerator="Alt+F4", command=self.quit)
        self.file_menu = f

        e = sub("Edit")
        e.add_command(label="Select All Photos", accelerator="Ctrl+A", command=self.select_all)
        e.add_command(label="Deselect All", accelerator="Ctrl+Shift+A", command=self.deselect_all)
        e.add_separator()
        e.add_command(label="Copy Diagnostics", accelerator="Ctrl+Alt+C", command=self.copy_diagnostics)

        v = sub("View")
        fm = tk.Menu(v, tearoff=False)
        for key, label in FORMATS:
            fm.add_radiobutton(label=label, value=key, variable=self.fmt_var, command=self.set_format)
        v.add_cascade(label="Output Format", menu=fm)
        pm = tk.Menu(v, tearoff=False)
        for key, label in PROFILES:
            pm.add_radiobutton(label=label, value=key, variable=self.profile_var, command=self.set_profile)
        v.add_cascade(label="Color Processing", menu=pm)
        v.add_separator()
        v.add_command(label="Show Diagnostics Log", accelerator="Ctrl+Alt+L", command=self.show_log)

        g = sub("Go")
        g.add_command(label="Previous Page", accelerator="Ctrl+[", command=lambda: self.handle("PreviousPage"))
        g.add_command(label="Next Page", accelerator="Ctrl+]", command=lambda: self.handle("NextPage"))
        g.add_separator()
        g.add_command(label="First Page", accelerator="Home", command=self.first_page)
        g.add_command(label="Last Page", accelerator="End", command=self.last_page)

        cam = sub("Camera")
        cam.add_command(label="Check Camera Connection", accelerator="Ctrl+K", command=lambda: self.check_camera(True))
        cam.add_command(label="Verify USB Access…", command=self.verify_usb)
        cam.add_separator()
        cam.add_command(label="Recovery Lab: Experimental Extra Frame…", command=self.recovery_lab)
        cam.add_separator()
        cam.add_command(label="USB Driver Help (Zadig)…", command=self.driver_help)
        cam.add_command(label="About TWAIN…", command=lambda: self.handle("Twain"))

        wm = sub("Window")
        wm.add_command(label="Minimize", accelerator="Ctrl+M", command=lambda: self.handle("Minimize"))
        wm.add_command(label="Center on Screen", command=self.center)
        m.add_separator()
        m.add_command(label="About PalmClix", command=lambda: self.handle("About"))
        m.add_command(label="Quit PalmClix", command=self.quit)

    def bind_keys(self):
        r = self.root
        keys = {
            "<Control-d>": lambda e: self.handle("Download"),
            "<Control-D>": lambda e: self.start_transfer(demo=True),
            "<Control-o>": lambda e: self.handle("ImageAdjust"),
            "<Control-s>": lambda e: self.handle("Save"),
            "<Control-R>": lambda e: self.reveal_import(),
            "<Control-a>": lambda e: self.select_all(),
            "<Control-A>": lambda e: self.deselect_all(),
            "<Control-bracketleft>": lambda e: self.handle("PreviousPage"),
            "<Control-bracketright>": lambda e: self.handle("NextPage"),
            "<Left>": lambda e: self.handle("PreviousPage"),
            "<Right>": lambda e: self.handle("NextPage"),
            "<Home>": lambda e: self.first_page(),
            "<End>": lambda e: self.last_page(),
            "<Control-k>": lambda e: self.check_camera(True),
            "<Control-m>": lambda e: self.handle("Minimize"),
            "<Control-Alt-c>": lambda e: self.copy_diagnostics(),
            "<Control-Alt-l>": lambda e: self.show_log(),
            "<Alt-F4>": lambda e: self.quit(),
            "<Control-q>": lambda e: self.quit(),
            "<Escape>": lambda e: self.set_hover(None),
            "<Shift-F10>": lambda e: self.show_menu(None),
            "<App>": lambda e: self.show_menu(None),
        }
        for seq, fn in keys.items():
            try:
                r.bind(seq, fn)
            except tk.TclError:
                pass

    # -------------------------------------------------------------- drawing
    def cell_rect(self, cell):
        col, row = cell % 4, cell // 4
        x = 95 + col * 89.5
        top = 122 + row * 77
        return (int(round(x)), int(top), 77, 58)

    def thumbnail(self, path: pathlib.Path):
        if path in self.thumbs:
            return self.thumbs[path]
        try:
            img = Image.open(path).convert("RGB").resize((69, 50), Image.LANCZOS)
        except Exception:
            img = None
        self.thumbs[path] = img
        return img

    def render(self):
        frame = self.images["body"].copy()
        for cell in range(12):
            x, y, w, h = self.cell_rect(cell)
            index = self.page * 12 + cell
            chosen = index < len(self.photos) and index in self.selected
            border = self.images.get("ImageFrame2" if chosen else "ImageFrame1")
            if border is not None:
                frame.paste(border.resize((w, h)), (x, y), border.resize((w, h)))
            if index < len(self.photos):
                thumb = self.thumbnail(self.photos[index])
                if thumb is not None:
                    frame.paste(thumb.resize((w - 8, h - 8)), (x + 4, y + 4))
        for name, x, y, w, h in BUTTONS:
            if self.busy and name == "Download":
                variant = 4
            elif self.pressed == name:
                variant = 3
            elif self.hovered == name:
                variant = 2
            else:
                variant = 1
            img = self.images.get(f"{name}{variant}") or self.images.get(f"{name}1")
            if img is not None:
                frame.paste(img, (x, y), img)
        bar_x, bar_y = 192, 365
        empty = self.images.get("Progress2")
        if empty is not None:
            frame.paste(empty, (bar_x, bar_y), empty)
        lit = self.images.get("Progress1")
        fill = max(0.0, min(1.0, self.fraction))
        if lit is not None and fill > 0:
            width = max(1, int(lit.width * fill))
            part = lit.crop((0, 0, width, lit.height))
            frame.paste(part, (bar_x, bar_y), part)
        draw = ImageDraw.Draw(frame)
        pages = 0 if not self.photos else (len(self.photos) + 11) // 12
        self.label(draw, f"{len(self.selected)} selected", 230, 444, 119)
        self.label(draw, f"Page {0 if not self.photos else self.page + 1} / {pages}", 414, 444, 110)
        self.label(draw, self.status, 95, 53, 350)
        self.label(draw, self.progress, 90, 348, 355)
        self.photo_image = ImageTk.PhotoImage(frame)
        self.canvas.itemconfigure(self.frame_item, image=self.photo_image)

    def label(self, draw, text, x, top, width):
        font = self.font_small
        while True:
            box = draw.textbbox((0, 0), text, font=font)
            if box[2] - box[0] <= width or len(text) < 8:
                break
            middle = len(text) // 2
            text = text[: middle - 2] + "…" + text[middle + 2:]
        tw, th = box[2] - box[0], box[3] - box[1]
        tx = x + (width - tw) / 2
        ty = top + (20 - th) / 2 - box[1] + 1
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)):
            draw.text((tx + dx, ty + dy), text, font=font, fill=(0, 0, 0))
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255))

    # --------------------------------------------------------------- mouse
    def button_at(self, x, y):
        for name, bx, by, bw, bh in BUTTONS:
            if bx <= x < bx + bw and by <= y < by + bh:
                return name
        return None

    def cell_at(self, x, y):
        for cell in range(12):
            cx, cy, cw, ch = self.cell_rect(cell)
            if cx <= x < cx + cw and cy <= y < cy + ch:
                return cell
        return None

    def photo_at(self, x, y):
        cell = self.cell_at(x, y)
        if cell is None:
            return None
        index = self.page * 12 + cell
        return index if index < len(self.photos) else None

    def is_body(self, x, y):
        try:
            return self.images["body"].getpixel((int(x), int(y))) != KEY
        except Exception:
            return False

    def set_hover(self, name):
        if name != self.hovered:
            self.hovered = name
            self.render()
        self.hide_tip()
        if name and name in TIPS:
            self.tip_job = self.root.after(600, lambda n=name: self.show_tip(n))

    def show_tip(self, name):
        if self.hovered != name:
            return
        self.hide_tip()
        x = self.root.winfo_pointerx() + 14
        y = self.root.winfo_pointery() + 18
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=TIPS[name], bg="#ffffe1", fg="#000000", relief="solid", bd=1,
                 font=("Tahoma", 8), padx=4, pady=2).pack()
        tip.geometry(f"+{x}+{y}")
        self.tip = tip

    def hide_tip(self):
        job = getattr(self, "tip_job", None)
        if job:
            self.root.after_cancel(job)
            self.tip_job = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None

    def on_motion(self, e):
        self.set_hover(self.button_at(e.x, e.y))

    def on_press(self, e):
        self.root.focus_force()
        self.hide_tip()
        self.pressed = self.button_at(e.x, e.y)
        self.drag_origin = None
        if self.pressed:
            self.render()
        elif self.cell_at(e.x, e.y) is None and self.is_body(e.x, e.y):
            self.drag_origin = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.drag_origin:
            dx, dy = self.drag_origin
            self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def on_release(self, e):
        if self.drag_origin:
            self.drag_origin = None
            self.settings["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
            save_settings(self.settings)
            return
        name = self.pressed
        self.pressed = None
        if name:
            self.render()
            if self.button_at(e.x, e.y) == name:
                self.handle(name)
            return
        index = self.photo_at(e.x, e.y)
        if index is not None and not self.busy:
            if index in self.selected:
                self.selected.discard(index)
            else:
                self.selected.add(index)
            self.render()

    def on_double(self, e):
        index = self.photo_at(e.x, e.y)
        if index is not None and not self.busy:
            self.selected.add(index)
            self.render()
            self.open_photos([index])

    def show_menu(self, e):
        self.hide_tip()
        self.refresh_menu()
        x = e.x_root if e is not None else self.root.winfo_rootx() + W // 2
        y = e.y_root if e is not None else self.root.winfo_rooty() + H // 2
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def refresh_menu(self):
        where = display_path(self.import_parent or default_pictures())
        self.file_menu.entryconfigure(self.folder_index, label=f"Saving imports to: {where}")
        self.fmt_var.set(self.fmt)
        self.profile_var.set(self.profile)

    # ------------------------------------------------------------- actions
    def handle(self, name):
        if self.busy and name != "Minimize":
            return
        if name == "Exit":
            self.quit()
        elif name == "Minimize":
            self.minimize()
        elif name == "About":
            messagebox.showinfo(
                f"PalmClix for Windows — v{APP_VERSION}",
                "Authentic 1990s PalmClix artwork, original raw-file preservation, "
                "PNG/JPEG conversion and two validated camera-catalog variants. "
                "Supported mode: 640×480 uncompressed still photographs.\n\n"
                "Download imports from the camera (Ctrl+D). Save copies selected photos "
                "to a folder (Ctrl+S). The picture button opens selected photos (Ctrl+O). "
                "Drag the camera body to move it. Right-click anywhere for every other "
                "option: output format, color processing, import folder and camera checks.",
                parent=self.root)
        elif name == "Download":
            self.start_transfer(demo=False)
        elif name == "Save":
            self.save_selected()
        elif name == "SelectAll":
            if self.photos and len(self.selected) == len(self.photos):
                self.selected = set()
            else:
                self.selected = set(range(len(self.photos)))
            self.render()
        elif name == "PreviousPage":
            self.page = max(0, self.page - 1)
            self.render()
        elif name == "NextPage":
            self.page = min(max(0, self.page_count() - 1), self.page + 1)
            self.render()
        elif name == "Twain":
            messagebox.showinfo("TWAIN", "TWAIN was part of the original Windows XP workflow. "
                                "Use Download to import directly instead.", parent=self.root)
        elif name == "ImageAdjust":
            self.open_photos()

    def page_count(self):
        return 0 if not self.photos else (len(self.photos) + 11) // 12

    def first_page(self):
        if not self.busy:
            self.page = 0
            self.render()

    def last_page(self):
        if not self.busy:
            self.page = max(0, self.page_count() - 1)
            self.render()

    def select_all(self):
        if not self.busy:
            self.selected = set(range(len(self.photos)))
            self.render()

    def deselect_all(self):
        if not self.busy:
            self.selected = set()
            self.render()

    def minimize(self):
        self.hide_tip()
        hwnd = getattr(self, "hwnd", None)
        if IS_WINDOWS and hwnd:
            import ctypes
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            return
        # Fallback for other platforms: frameless windows must regain a frame to iconify.
        self.root.overrideredirect(False)
        self.root.iconify()

    def on_map(self, _event):
        if not IS_WINDOWS and not self.root.overrideredirect():
            self.root.after(10, lambda: self.root.overrideredirect(True))

    def center(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - W) // 2}+{(sh - H) // 2}")

    def quit(self):
        if self.busy:
            messagebox.showwarning("Transfer in progress",
                                   "Let the camera transfer finish before quitting. Abrupt "
                                   "interruption may leave the camera in an unknown state.",
                                   parent=self.root)
            return
        self.settings["window_pos"] = [self.root.winfo_x(), self.root.winfo_y()]
        save_settings(self.settings)
        self.root.destroy()

    def set_format(self):
        if self.busy:
            self.fmt_var.set(self.fmt)
            return
        self.fmt = self.fmt_var.get()
        self.settings["format"] = self.fmt
        save_settings(self.settings)
        self.progress = "Output format: " + dict(FORMATS)[self.fmt]
        self.render()

    def set_profile(self):
        if self.busy:
            self.profile_var.set(self.profile)
            return
        self.profile = self.profile_var.get()
        self.settings["profile"] = self.profile
        save_settings(self.settings)
        self.progress = "Color processing: " + dict(PROFILES)[self.profile]
        self.render()

    def choose_import_folder(self):
        if self.busy:
            return
        chosen = filedialog.askdirectory(parent=self.root, title="Choose where PalmClix saves imported photos",
                                         initialdir=str(self.import_parent or default_pictures()), mustexist=False)
        if chosen:
            self.import_parent = pathlib.Path(chosen)
            self.settings["import_parent"] = chosen
            save_settings(self.settings)
            self.progress = "Imports save to " + display_path(self.import_parent)
            self.render()

    def reset_import_folder(self):
        if self.busy:
            return
        self.import_parent = None
        self.settings.pop("import_parent", None)
        save_settings(self.settings)
        self.progress = "Imports save to ~/Pictures"
        self.render()

    def copy_diagnostics(self):
        if not self.log:
            messagebox.showinfo("No diagnostics yet", "Run an import or a camera check first.", parent=self.root)
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(self.log))
        self.progress = "Diagnostics copied to clipboard"
        self.render()

    def show_log(self):
        if not self.log:
            messagebox.showinfo("No diagnostics yet", "Run an import or a camera check first.", parent=self.root)
            return
        path = pathlib.Path(os.environ.get("TEMP") or "/tmp") / "PalmClix Diagnostics.log"
        path.write_text("\n".join(self.log) + "\n", encoding="utf-8")
        self.open_path(path)

    def driver_help(self):
        messagebox.showinfo(
            "USB driver for PalmClix",
            "Windows needs a generic USB driver before PalmClix can talk to the camera.\n\n"
            "1. Plug in the camera.\n"
            "2. Download Zadig from https://zadig.akeo.ie and run it.\n"
            "3. Options ▸ List All Devices, then choose the device with USB ID 2770 9120.\n"
            "4. Select the WinUSB driver and click Install/Replace Driver.\n\n"
            "This replaces the original XP driver for that camera only. To go back, "
            "uninstall the device in Device Manager.",
            parent=self.root)

    def reveal_import(self):
        if not self.last_import:
            messagebox.showinfo("No completed import yet", "Download photos first.", parent=self.root)
            return
        if IS_WINDOWS:
            subprocess.Popen(["explorer", f"/select,{self.last_import}"])
        else:
            self.open_path(self.last_import.parent)

    def open_path(self, path: pathlib.Path):
        try:
            if IS_WINDOWS:
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Could not open", str(exc), parent=self.root)

    def open_photos(self, indices=None):
        if not self.photos:
            messagebox.showinfo("No photographs yet",
                                "Click Download first, then select a thumbnail and click this button to open it.",
                                parent=self.root)
            return
        indices = indices or sorted(self.selected) or [min(self.page * 12, len(self.photos) - 1)]
        files = [self.photos[i] for i in indices if 0 <= i < len(self.photos) and self.photos[i].exists()]
        if not files:
            messagebox.showwarning("Photograph not found",
                                   "The selected photo file has been moved or deleted. Import again, or "
                                   "use File ▸ Show Latest Import in Explorer.", parent=self.root)
            return
        for path in files[:12]:
            self.open_path(path)
        self.progress = (f"Opened {files[0].name}" if len(files) == 1 else f"Opened {min(len(files), 12)} photos")
        self.render()

    def save_selected(self):
        if not self.photos:
            messagebox.showinfo("No photographs yet", "Click Download first.", parent=self.root)
            return
        chosen = [self.photos[i] for i in sorted(self.selected)] if self.selected else list(self.photos)
        dest = filedialog.askdirectory(parent=self.root, title=f"Save {len(chosen)} photo(s) to…",
                                       initialdir=str(self.last_import or default_pictures()))
        if not dest:
            return
        dest = pathlib.Path(dest)
        written = 0
        for source in chosen:
            target = dest / source.name
            if target.exists():
                target = dest / f"{source.stem}_{uuid.uuid4().hex[:6]}{source.suffix}"
            try:
                target.write_bytes(source.read_bytes())
                written += 1
            except Exception as exc:
                messagebox.showerror("Save error", str(exc), parent=self.root)
                break
        self.status = f"Saved {written} photo(s)"
        self.progress = "to " + display_path(dest)
        self.render()

    # -------------------------------------------------------------- camera
    def run_quick(self, args, done):
        def worker():
            try:
                result = subprocess.run(backend_command(args), capture_output=True, text=True,
                                        timeout=60, **popen_flags())
                output = (result.stdout + result.stderr).strip()
                self.events.put(("call", lambda: done(result.returncode, output)))
            except Exception as exc:
                self.events.put(("call", lambda: done(-1, str(exc))))
        threading.Thread(target=worker, daemon=True).start()

    def check_camera(self, announce):
        if self.busy:
            return
        if announce:
            self.status = "Checking USB…"
            self.render()

        def done(code, output):
            found = "Detected device" in output
            text = "PalmClix connected — 2770:9120" if found else "PalmClix not connected"
            if code not in (0, 1):
                text = "USB detection unavailable"
            self.append_log(text + (" — " + output if output and not found else ""))
            if not self.busy:
                self.status = text
                self.render()
            if announce and not found:
                messagebox.showinfo(text, "Plug in the camera. If it is plugged in, Windows may still need "
                                    "the WinUSB driver: right-click ▸ Camera ▸ USB Driver Help.\n\n" + output[-600:],
                                    parent=self.root)
        self.run_quick(["--inspect"], done)

    def verify_usb(self):
        if self.busy:
            return
        self.status = "Verifying USB access…"
        self.append_log("Checking camera USB configuration and interface access…")
        self.render()

        def done(code, output):
            result = "PalmClix USB interface ready" if code == 0 else "USB interface unavailable"
            self.append_log(result + " — " + output)
            self.status = result
            self.render()
            messagebox.showinfo(result, output or "No details reported.", parent=self.root)
        self.run_quick(["--ready-check"], done)

    def recovery_lab(self):
        if self.busy:
            return
        ok = messagebox.askyesno(
            "Experimental eighth-photo investigation",
            "Windows DSC transferred seven frames, while the catalog reported eight slots. Slot 1 (0x01) has "
            "NO known decoding rule. This one-time experiment reads at most ONE additional stream after saving "
            "the seven recognized photos. It may time out, return duplicate data, or leave the camera requiring "
            "reconnection. No erase command is included. This is NOT guaranteed recovery.\n\n"
            "Enable it for the next live import?", icon="warning", parent=self.root)
        if ok:
            self.probe_next = True
            self.append_log("Recovery probe armed ONCE. Only the next LIVE import uses it.")
            self.progress = "Recovery probe armed for next live import"
            self.render()

    # -------------------------------------------------------------- import
    def append_log(self, text):
        if text:
            self.log.append(text)
            del self.log[:-400]

    def photo_files(self, root: pathlib.Path):
        folder = root / "Photos"
        if not folder.is_dir():
            return []
        by_stem = {}
        for path in folder.iterdir():
            ext = path.suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg") or path.name.startswith("."):
                continue
            if path.stem not in by_stem or ext == ".png":
                by_stem[path.stem] = path
        return sorted(by_stem.values(), key=lambda p: p.name.lower())

    def find_demo(self):
        for candidate in (APP_DIR / "reference_capture.pcap", APP_DIR / "Demo" / "reference_capture.pcap",
                          pathlib.Path(self.settings.get("demo_capture", "")) if self.settings.get("demo_capture") else None):
            if candidate and candidate.is_file():
                return candidate
        chosen = filedialog.askopenfilename(
            parent=self.root, title="Choose a recorded PalmClix USB capture (.pcap)",
            filetypes=[("USB capture", "*.pcap"), ("All files", "*.*")])
        if chosen:
            self.settings["demo_capture"] = chosen
            save_settings(self.settings)
            return pathlib.Path(chosen)
        return None

    def start_transfer(self, demo):
        if self.busy:
            return
        extra = []
        if demo:
            capture = self.find_demo()
            if capture is None:
                return
            extra += ["--simulate", str(capture)]
        else:
            fmt_label = "PNG + JPEG" if self.fmt == "both" else self.fmt.upper()
            if not messagebox.askyesno(
                    "Read photos from PalmClix?",
                    f"Photos will be saved to {display_path(self.import_parent or default_pictures())} as {fmt_label}.\n\n"
                    "The application uses the USB commands observed in successful Windows XP transfers. This "
                    "proprietary camera protocol is not guaranteed risk-free. Irreplaceable images should be "
                    "backed up first. No erase operation is requested.", parent=self.root):
                return
            extra += ["--download", "auto", "--i-accept-experimental-usb"]
            if self.probe_next:
                extra += ["--probe-extra-frame", "--i-accept-experimental-probe"]
                self.append_log("EXPERIMENTAL RECOVERY PROBE ENABLED for this import only.")
            self.probe_next = False
        base = self.import_parent or default_pictures()
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        destination = base / f"PalmClix_{stamp}_{uuid.uuid4().hex[:6].upper()}"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Import folder unavailable", str(exc), parent=self.root)
            return
        extra += ["--profile", self.profile, "--format", self.fmt, "--output", str(destination), "--json-progress"]
        self.log = []
        self.append_log(f"Mode: {'offline replay' if demo else 'live camera'}  •  Format: {self.fmt}  •  Profile: {self.profile}")
        self.append_log("Destination: " + str(destination))
        self.prior = (self.photos, set(self.selected), self.page)
        self.busy = True
        self.fraction = 0.0
        self.excluded = 0
        self.import_count = 0
        self.recovery_saved = False
        self.backend_error = None
        self.status = "Offline recording replay…" if demo else "Reading PalmClix…"
        self.progress = "Starting transfer…"
        self.render()

        def worker():
            try:
                proc = subprocess.Popen(backend_command(extra), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        cwd=str(base), text=True, encoding="utf-8", errors="replace", bufsize=1,
                                        **popen_flags())
                self.process = proc
                for line in proc.stdout:
                    self.events.put(("line", line.rstrip("\r\n")))
                code = proc.wait()
                self.events.put(("finished", (code, destination)))
            except Exception as exc:
                self.events.put(("launch_failed", (str(exc), destination)))
        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self):
        changed = False
        try:
            while True:
                kind, payload = self.events.get_nowait()
                changed = True
                if kind == "line":
                    self.handle_line(payload)
                elif kind == "finished":
                    self.finish_transfer(*payload)
                elif kind == "launch_failed":
                    message, destination = payload
                    self.busy = False
                    self.status = "Cannot run backend"
                    self.append_log("Backend launch failed: " + message)
                    self.save_session_log(destination)
                    self.render()
                    messagebox.showerror("Failed to start backend", message, parent=self.root)
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        if changed and self.busy:
            self.render()
        self.root.after(80, self.poll_events)

    def handle_line(self, line):
        if not line.startswith("PALMCLIX_EVENT "):
            if line:
                self.append_log(line)
            return
        try:
            payload = json.loads(line[len("PALMCLIX_EVENT "):])
        except json.JSONDecodeError:
            return
        kind = payload.get("event")
        i, total = payload.get("index", 0), payload.get("total", 0)
        if kind == "error":
            self.backend_error = payload.get("message")
            self.append_log("Error: " + str(self.backend_error))
            self.status = "USB error"
            self.progress = self.backend_error or "Unknown error"
        elif kind == "metadata":
            self.status = "Camera model identified"
            self.progress = f"Model ID: {payload.get('model_id', '')}"
            self.append_log(self.progress)
            self.fraction = 0.03
        elif kind == "catalog":
            count = payload.get("count", 0)
            self.excluded = payload.get("excluded_slots", 0)
            self.import_count = count
            self.status = f"Camera: {count} photos" + (f" • {self.excluded} unavailable slot" if self.excluded else "")
            self.progress = "No supported photographs" if count == 0 else f"Reading {count} supported photo(s)…"
            self.append_log(f"Catalog: {count} valid photos, {self.excluded} excluded slot(s)")
            self.fraction = 1.0 if count == 0 else 0.07
        elif kind == "stage":
            self.append_log("USB transfer complete; decoding images…" if payload.get("stage") == "decode"
                            else "Starting USB image transfer…")
        elif kind == "chunk":
            done, everything = payload.get("completed_chunks", 0), max(1, payload.get("all_chunks", 1))
            self.fraction = 0.07 + 0.73 * done / everything
            self.progress = (f"Receiving photo {payload.get('photo', 0)}/{payload.get('total_photos', 0)} · "
                             f"block {payload.get('chunk', 0)}/10")
        elif kind == "transfer":
            self.progress = f"Raw photo {i} of {total} saved safely"
            self.append_log(self.progress)
        elif kind == "photo":
            self.progress = f"Converted photo {i} of {total}"
            self.fraction = 0.8 + 0.2 * i / max(1, total)
            self.append_log(self.progress)
        elif kind == "done":
            self.progress = f"Imported {payload.get('count', self.import_count)} photographs"
            self.fraction = 1.0
        elif kind == "recovery":
            state = payload.get("status", "unknown")
            self.recovery_saved = state == "unverified-candidate-saved"
            self.append_log("RECOVERY LAB: " + state + " · unverified, not part of the normal gallery")

    def finish_transfer(self, code, destination: pathlib.Path):
        self.process = None
        self.busy = False
        if code == 0:
            self.photos = self.photo_files(destination)
            self.thumbs.clear()
            self.selected = set()
            self.page = 0
            self.last_import = destination
            self.settings["last_import"] = str(destination)
            save_settings(self.settings)
            self.status = f"Imported {len(self.photos)} photos"
            self.progress = (f"{self.excluded} unusable slot(s) excluded" if self.excluded
                             else "Saved to " + display_path(destination.parent))
            self.fraction = 1.0
            self.append_log(f"Complete: {len(self.photos)} images. Import folder: {destination}")
            if self.recovery_saved:
                messagebox.showinfo("Unverified extra stream saved",
                                    "A candidate raw sensor frame was stored in the Recovery folder. This does NOT "
                                    "confirm recovery of catalog slot 1.", parent=self.root)
        else:
            self.photos, self.selected, self.page = self.prior
            self.fraction = 0.0
            self.status = "Transfer failed — previous gallery retained"
            self.append_log(f"FAILED (exit {code}): {self.backend_error or 'Unknown helper error'}")
            self.render()
            messagebox.showerror("PalmClix transfer failed",
                                 f"{self.backend_error or f'The USB helper exited with code {code}.'}\n\n"
                                 f"Any already saved raw photos have been preserved in {destination}. "
                                 "Avoid repeated attempts after unexpected USB failures.", parent=self.root)
        self.save_session_log(destination)
        self.render()

    def save_session_log(self, destination: pathlib.Path):
        try:
            folder = destination / "Protocol"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "app_session.log").write_text("\n".join(self.log) + "\n", encoding="utf-8")
        except Exception as exc:
            self.append_log("Unable to save session log: " + str(exc))


def run_backend(argv):
    """Entry point used when the packaged exe re-launches itself as the USB helper."""
    if not FROZEN:
        sys.path.insert(0, str(APP_DIR))
    import palmclix
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass
    code = palmclix.main(argv)
    sys.exit(code if isinstance(code, int) else 0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        run_backend(sys.argv[2:])
        return
    root = tk.Tk()
    PalmClixApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
