"""QuickResize - lightweight Windows bulk image resizer.

Run with: python quickresize.py
Install dependencies with: pip install -r requirements.txt
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

APP_VERSION = "2026.10.20.1"
CLEAR_CONFIRM_AT = 8

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

try:
    from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    COPY = "copy"
    REFUSE_DROP = "refuse_drop"
    DND_AVAILABLE = False

try:
    import rawpy

    CRW_AVAILABLE = True
except ImportError:
    CRW_AVAILABLE = False

try:
    import pymupdf as fitz

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".crw",
    ".cr3",
    ".pdf",
    ".psd",
    ".psb",
}
FORMAT_INFO = {
    "JPG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "WEBP": ("WEBP", ".webp"),
    "TIFF": ("TIFF", ".tiff"),
    "BMP": ("BMP", ".bmp"),
}
TYPE_LABELS = {
    ".jpg": "JPG",
    ".jpeg": "JPG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".bmp": "BMP",
    ".gif": "GIF",
    ".heic": "HEIC",
    ".heif": "HEIF",
    ".crw": "CRW",
    ".cr3": "CR3",
    ".pdf": "PDF",
    ".psd": "PSD",
    ".psb": "PSB",
}
PRESETS = (("1920", 1920), ("1600", 1600), ("1080", 1080), ("800", 800))
COLLISION_OPTIONS = (
    ("unique", "Unique names"),
    ("overwrite", "Overwrite existing"),
    ("beside", "Next to each source"),
)
COLLISION_LABELS = {code: label for code, label in COLLISION_OPTIONS}
COLLISION_CODES = {label: code for code, label in COLLISION_OPTIONS}
COLLISION_HINTS = {
    "unique": "If a name is already used, a number is added.",
    "overwrite": "An existing file with the same name is replaced.",
    "beside": "Each photo is saved in the same folder as the original.",
}
STATUS_TAGS = {
    "Pending": "pending",
    "Working": "working",
    "Done": "done",
    "Failed": "failed",
    "Partial": "partial",
}

COLORS = {
    "app": "#0e1420",
    "card": "#182231",
    "border": "#2a394b",
    "field": "#101a28",
    "text": "#eef4fa",
    "muted": "#9aaabd",
    "accent": "#5b9dff",
    "accent_hover": "#78afff",
    "button": "#263447",
    "button_hover": "#34465c",
    "drop": "#15283e",
    "drop_hot": "#1c3554",
    "drop_border": "#3a638e",
    "selection": "#294d75",
    "ok_bg": "#163226",
    "ok_border": "#3d8f62",
    "warn_bg": "#342818",
    "warn_border": "#c4923a",
    "done_text": "#9ddeb0",
    "failed_text": "#f3a7a7",
    "partial_text": "#e6c98a",
}


def enable_dpi_awareness() -> None:
    """Make the window sharp on scaled Windows displays. Must run before Tk starts."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError, ValueError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError, ValueError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError, ValueError):
        pass


def path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:
        return os.path.normcase(str(path))


def normalize_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def type_label(path: Path) -> str:
    suffix = path.suffix.lower()
    return TYPE_LABELS.get(suffix, suffix[1:].upper() or "?")


def pdf_page_summary(pages: list[int]) -> str:
    numbers = [page + 1 for page in pages]
    if len(numbers) <= 4:
        return "pages " + ", ".join(str(number) for number in numbers)
    return f"{len(numbers)} pages"


def decoder_issue(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".heic", ".heif"} and not HEIC_AVAILABLE:
        return "HEIC needs pillow-heif"
    if suffix in {".crw", ".cr3"} and not CRW_AVAILABLE:
        return "RAW needs rawpy"
    if suffix == ".pdf" and not PDF_AVAILABLE:
        return "PDF needs pymupdf"
    return None


def collect_inputs(paths: list[Path]) -> tuple[list[Path], int]:
    """Return supported files and a count of explicitly unsupported files.

    Folders are scanned recursively. Unsupported files inside a folder are ignored
    so a camera folder full of sidecars does not flood the status line. A file the
    user dropped directly still counts as unsupported.
    """
    supported: list[Path] = []
    unsupported = 0
    seen: set[str] = set()

    def add_supported(candidate: Path) -> None:
        key = path_key(candidate)
        if key in seen:
            return
        seen.add(key)
        supported.append(candidate)

    for path in paths:
        try:
            is_dir = path.is_dir()
            is_file = path.is_file()
        except OSError:
            unsupported += 1
            continue
        if is_dir:
            try:
                children = list(path.rglob("*"))
            except OSError:
                unsupported += 1
                continue
            for child in children:
                try:
                    if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
                        add_supported(child)
                except OSError:
                    continue
        elif is_file:
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                add_supported(path)
            else:
                unsupported += 1
        else:
            unsupported += 1
    return supported, unsupported


def summarize_add(added: int, updated: int, duplicates: int, unsupported: int, decoder_skips: dict[str, int], cancelled: int) -> str:
    parts: list[str] = []
    if added:
        parts.append(f"Added {added} file{'s' if added != 1 else ''}")
    if updated:
        parts.append(f"Updated {updated} PDF selection{'s' if updated != 1 else ''}")
    if duplicates:
        parts.append(f"{duplicates} already queued")
    if unsupported:
        parts.append(f"Skipped {unsupported} unsupported file{'s' if unsupported != 1 else ''}")
    for reason, count in decoder_skips.items():
        parts.append(f"Skipped {count} — {reason}")
    if cancelled:
        parts.append(f"Skipped {cancelled} PDF{'s' if cancelled != 1 else ''} with no pages selected")
    if not parts:
        return "No files added"
    return ". ".join(parts)


def parse_page_range(text: str, page_count: int) -> list[int]:
    """Parse a 1-based range such as '1-5, 8' into 0-based page indexes."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty")
    if page_count < 1:
        raise ValueError("empty document")
    chosen: list[int] = []
    seen: set[int] = set()
    for raw_part in stripped.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("empty part")
        if "-" in part:
            left, right = part.split("-", 1)
            if not left.strip() or not right.strip() or "-" in right:
                raise ValueError("bad range")
            start = int(left.strip())
            end = int(right.strip())
            step = 1 if start <= end else -1
            for number in range(start, end + step, step):
                if number < 1 or number > page_count:
                    raise ValueError("out of range")
                index = number - 1
                if index not in seen:
                    seen.add(index)
                    chosen.append(index)
        else:
            number = int(part)
            if number < 1 or number > page_count:
                raise ValueError("out of range")
            index = number - 1
            if index not in seen:
                seen.add(index)
                chosen.append(index)
    if not chosen:
        raise ValueError("empty")
    return chosen


def _same_file(candidate: Path, source: Path) -> bool:
    try:
        return candidate.resolve() == source.resolve()
    except OSError:
        return False


def _taken_key(candidate: Path) -> str:
    try:
        return os.path.normcase(str(candidate.resolve()))
    except OSError:
        return os.path.normcase(str(candidate))


def plan_output_path(folder: Path, source: Path, page: int | None, extension: str, collision: str, used: set[str]) -> Path:
    """Choose an output path that does not overwrite the source file."""
    page_suffix = f"_page_{page + 1:03d}" if page is not None else ""
    stem = f"{source.stem}{page_suffix}"
    candidate = folder / f"{stem}{extension}"
    if _same_file(candidate, source):
        stem = f"{stem}_resized"
        candidate = folder / f"{stem}{extension}"
    if collision == "overwrite":
        return candidate
    number = 2
    while _taken_key(candidate) in used or candidate.exists():
        candidate = folder / f"{stem}_{number}{extension}"
        number += 1
        if number > 10000:
            raise RuntimeError(f"Could not find a free name for {source.name}")
    used.add(_taken_key(candidate))
    return candidate


def _setting_dimension(settings: dict[str, object], key: str, default: str) -> str:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        value = str(int(value))
    if isinstance(value, str) and value.strip().isdigit() and int(value.strip()) >= 1:
        return value.strip()
    return default


def _setting_quality(settings: dict[str, object]) -> int:
    value = settings.get("quality", 92)
    try:
        quality = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 92
    return max(1, min(100, quality))


class QuickResizeApp:
    def __init__(self, root: tk.Misc):
        self.root = root
        self.root.title(f"QuickResize v{APP_VERSION}")
        self.root.geometry("1080x920")
        self.root.minsize(960, 860)
        self.root.configure(bg=COLORS["app"])

        self.files: list[Path] = []
        self.pdf_pages: dict[Path, list[int]] = {}
        self.file_status: dict[Path, str] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.is_processing = False
        self.cancel_event = threading.Event()
        self._save_after_id: str | None = None
        self._drag_clear_id: str | None = None
        self._iid_by_path: dict[Path, str] = {}
        self._iid_counter = 0
        self.queue_drag_iid: str | None = None
        self._expected: dict[Path, int] = {}
        self._ok_count: dict[Path, int] = {}
        self._fail_count: dict[Path, int] = {}
        self._paths_by_text: dict[str, Path] = {}
        self._job_total = 0
        self._jobs_finished = 0
        self._result_folder = ""
        self._errors_visible = False
        self._run_beside = False

        settings = self._load_settings()
        self.width_var = tk.StringVar(value=_setting_dimension(settings, "width", "1600"))
        self.height_var = tk.StringVar(value=_setting_dimension(settings, "height", "1600"))
        saved_format = settings.get("format")
        self.format_var = tk.StringVar(value=saved_format if isinstance(saved_format, str) and saved_format in FORMAT_INFO else "JPG")
        saved_collision = settings.get("collision")
        collision_code = saved_collision if isinstance(saved_collision, str) and saved_collision in COLLISION_LABELS else "unique"
        self.collision_var = tk.StringVar(value=COLLISION_LABELS[collision_code])
        self.quality_var = tk.DoubleVar(value=_setting_quality(settings))
        self.quality_text_var = tk.StringVar(value=str(_setting_quality(settings)))
        self.collision_hint_var = tk.StringVar(value=COLLISION_HINTS[collision_code])
        default_destination = Path.home() / "Pictures" / "QuickResize"
        saved_destination = settings.get("destination")
        if not isinstance(saved_destination, str) or not saved_destination.strip():
            saved_destination = None
        self.destination_var = tk.StringVar(value=saved_destination or str(default_destination))
        self.status_var = tk.StringVar(value="Ready — drop files or folders anywhere")
        self.count_var = tk.StringVar(value="0 files")

        self.drop_labels: list[tk.Label] = []
        self.action_buttons: list[ttk.Button] = []
        self._build_ui()
        self._sync_quality_state()
        self._sync_destination_state()
        for variable in (self.destination_var, self.width_var, self.height_var, self.format_var, self.collision_var):
            variable.trace_add("write", self._schedule_settings_save)
        self.quality_var.trace_add("write", self._on_quality_changed)
        self.format_var.trace_add("write", self._sync_quality_state)
        self.collision_var.trace_add("write", self._sync_destination_state)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._poll_events)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=COLORS["app"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("Title.TLabel", background=COLORS["app"], foreground=COLORS["text"], font=("Segoe UI", 25, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["app"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background=COLORS["card"], foreground=COLORS["text"], font=("Segoe UI", 12, "bold"))
        style.configure("CardText.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Count.TLabel", background=COLORS["card"], foreground=COLORS["accent"], font=("Segoe UI", 9, "bold"))
        style.configure("Hint.TLabel", background=COLORS["card"], foreground=COLORS["muted"], font=("Segoe UI", 8))
        style.configure("TButton", background=COLORS["button"], foreground=COLORS["text"], font=("Segoe UI", 9), padding=(11, 8), relief="flat", borderwidth=0)
        style.configure("Compact.TButton", background=COLORS["button"], foreground=COLORS["text"], font=("Segoe UI", 9), padding=(8, 6), relief="flat", borderwidth=0)
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="#081321", font=("Segoe UI", 10, "bold"), padding=(20, 10), relief="flat", borderwidth=0)
        style.map("TButton", background=[("active", COLORS["button_hover"]), ("disabled", COLORS["button"])], foreground=[("disabled", COLORS["muted"])])
        style.map("Compact.TButton", background=[("active", COLORS["button_hover"]), ("disabled", COLORS["button"])], foreground=[("disabled", COLORS["muted"])])
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["button"])], foreground=[("disabled", COLORS["muted"])])
        style.configure("Dark.TEntry", fieldbackground=COLORS["field"], foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["border"], padding=(8, 7))
        style.map("Dark.TEntry", fieldbackground=[("disabled", COLORS["field"])], foreground=[("disabled", COLORS["muted"])])
        style.configure("Dark.TCombobox", fieldbackground=COLORS["field"], background=COLORS["field"], foreground=COLORS["text"], arrowcolor=COLORS["text"], bordercolor=COLORS["border"], padding=(8, 7))
        style.map("Dark.TCombobox", fieldbackground=[("readonly", COLORS["field"]), ("disabled", COLORS["field"])], foreground=[("readonly", COLORS["text"]), ("disabled", COLORS["muted"])])
        self.root.option_add("*TCombobox*Listbox.background", COLORS["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", COLORS["selection"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", COLORS["text"])
        try:
            style.layout("Queue.Treeview", style.layout("Treeview"))
            style.layout("Queue.Treeview.Heading", style.layout("Treeview.Heading"))
        except tk.TclError:
            pass
        style.configure("Queue.Treeview", background=COLORS["card"], fieldbackground=COLORS["card"], foreground=COLORS["text"], borderwidth=0, relief="flat", rowheight=30, font=("Segoe UI", 9))
        style.configure("Queue.Treeview.Heading", background=COLORS["button"], foreground=COLORS["text"], relief="flat", borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("Queue.Treeview", background=[("selected", COLORS["selection"])], foreground=[("selected", COLORS["text"])])
        style.map("Queue.Treeview.Heading", background=[("active", COLORS["button_hover"])])
        for custom_style, base_style in (
            ("Run.Horizontal.TProgressbar", "Horizontal.TProgressbar"),
            ("Dark.Vertical.TScrollbar", "Vertical.TScrollbar"),
            ("Dark.Horizontal.TScale", "Horizontal.TScale"),
        ):
            try:
                style.layout(custom_style, style.layout(base_style))
            except tk.TclError:
                pass
        style.configure("Run.Horizontal.TProgressbar", troughcolor=COLORS["field"], background=COLORS["accent"], bordercolor=COLORS["field"], lightcolor=COLORS["accent"], darkcolor=COLORS["accent"])
        style.configure("Dark.Vertical.TScrollbar", background=COLORS["button"], troughcolor=COLORS["field"], arrowcolor=COLORS["text"], bordercolor=COLORS["field"])
        style.configure("Dark.Horizontal.TScale", background=COLORS["card"], troughcolor=COLORS["field"])

        outer = ttk.Frame(self.root, style="App.TFrame", padding=(26, 18))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="QuickResize", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Batch image resizing, made simple", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(header, text=f"v{APP_VERSION}", style="Subtitle.TLabel").place(relx=1, x=0, y=12, anchor="ne")

        self.bottom_stack = ttk.Frame(outer, style="App.TFrame")
        self.bottom_stack.pack(side="bottom", fill="x", pady=(14, 0))
        self._build_result_banner()
        self._build_error_panel()
        self._build_footer()

        workspace = ttk.Frame(outer, style="App.TFrame")
        workspace.pack(fill="both", expand=True)
        workspace.columnconfigure(0, weight=3)
        workspace.columnconfigure(1, weight=2)
        workspace.rowconfigure(0, weight=1)
        left = ttk.Frame(workspace, style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.right_canvas = tk.Canvas(workspace, bg=COLORS["app"], highlightthickness=0, bd=0)
        self.right_canvas.grid(row=0, column=1, sticky="nsew")
        self.right_scroll = ttk.Scrollbar(workspace, orient="vertical", command=self.right_canvas.yview, style="Dark.Vertical.TScrollbar")
        right = ttk.Frame(self.right_canvas, style="App.TFrame")
        self._right_window = self.right_canvas.create_window((0, 0), window=right, anchor="nw")
        right.bind("<Configure>", self._sync_right_scroll)
        self.right_canvas.bind("<Configure>", self._sync_right_scroll)
        self.left_column = left
        self.right_column = right

        self.drop_frame = tk.Frame(left, bg=COLORS["drop"], highlightthickness=1, highlightbackground=COLORS["drop_border"], cursor="hand2")
        self.drop_frame.pack(fill="x", ipady=12)
        self.drop_frame.bind("<Button-1>", lambda _event: self.choose_files())
        icon = tk.Label(self.drop_frame, text="+", bg=COLORS["drop"], fg=COLORS["accent"], font=("Segoe UI", 26, "bold"), cursor="hand2")
        title = tk.Label(self.drop_frame, text="Drop files or folders anywhere", bg=COLORS["drop"], fg=COLORS["text"], font=("Segoe UI", 14, "bold"), cursor="hand2")
        note_text = "Subfolders are included. Click here to browse files." if DND_AVAILABLE else "Click here to browse files, or use Add folder."
        note = tk.Label(self.drop_frame, text=note_text, bg=COLORS["drop"], fg=COLORS["muted"], font=("Segoe UI", 9), cursor="hand2")
        for child in (icon, title, note):
            child.pack()
            child.bind("<Button-1>", lambda _event: self.choose_files())
        self.drop_labels.extend([icon, title, note])

        add_row = ttk.Frame(left, style="App.TFrame")
        add_row.pack(fill="x", pady=(10, 0))
        self.add_files_button = ttk.Button(add_row, text="Add files", style="Compact.TButton", command=self.choose_files)
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(add_row, text="Add folder", style="Compact.TButton", command=self.choose_folder)
        self.add_folder_button.pack(side="left", padx=(6, 0))
        self.action_buttons.extend([self.add_files_button, self.add_folder_button])

        queue_border = tk.Frame(left, bg=COLORS["border"], padx=1, pady=1)
        queue_border.pack(fill="both", expand=True, pady=(10, 0))
        queue_card = ttk.Frame(queue_border, style="Card.TFrame", padding=14)
        queue_card.pack(fill="both", expand=True)
        queue_heading = ttk.Frame(queue_card, style="Card.TFrame")
        queue_heading.pack(fill="x")
        ttk.Label(queue_heading, text="Queue", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(queue_heading, textvariable=self.count_var, style="Count.TLabel").pack(side="right")
        queue_body = tk.Frame(queue_card, bg=COLORS["card"])
        queue_body.pack(fill="both", expand=True, pady=(10, 8))
        self.queue_scroll = ttk.Scrollbar(queue_body, orient="vertical", style="Dark.Vertical.TScrollbar")
        self.queue = ttk.Treeview(
            queue_body,
            columns=("name", "type", "folder", "status"),
            show="headings",
            selectmode="browse",
            style="Queue.Treeview",
            yscrollcommand=self.queue_scroll.set,
        )
        self.queue_scroll.configure(command=self.queue.yview)
        self.queue.heading("name", text="Name", anchor="w")
        self.queue.heading("type", text="Type", anchor="w")
        self.queue.heading("folder", text="Folder", anchor="w")
        self.queue.heading("status", text="Status", anchor="w")
        self.queue.column("name", width=240, minwidth=120, stretch=True, anchor="w")
        self.queue.column("type", width=64, minwidth=52, stretch=False, anchor="w")
        self.queue.column("folder", width=180, minwidth=80, stretch=True, anchor="w")
        self.queue.column("status", width=92, minwidth=76, stretch=False, anchor="w")
        self.queue.tag_configure("pending", foreground=COLORS["muted"])
        self.queue.tag_configure("working", foreground=COLORS["accent"])
        self.queue.tag_configure("done", foreground=COLORS["done_text"])
        self.queue.tag_configure("failed", foreground=COLORS["failed_text"])
        self.queue.tag_configure("partial", foreground=COLORS["partial_text"])
        self.queue_scroll.pack(side="right", fill="y")
        self.queue.pack(side="left", fill="both", expand=True)
        self.empty_queue_label = tk.Label(queue_body, text="No files queued yet", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 10))
        self.empty_queue_label.place(relx=0.46, rely=0.58, anchor="center")
        self.queue.bind("<ButtonPress-1>", self._queue_press)
        self.queue.bind("<B1-Motion>", self._queue_drag)
        self.queue.bind("<ButtonRelease-1>", self._queue_release)
        self.queue.bind("<Delete>", lambda _event: self.remove_selected())

        queue_actions = ttk.Frame(queue_card, style="Card.TFrame")
        queue_actions.pack(fill="x")
        self.up_button = ttk.Button(queue_actions, text="Up", style="Compact.TButton", command=lambda: self.move_selected(-1))
        self.up_button.pack(side="left")
        self.down_button = ttk.Button(queue_actions, text="Down", style="Compact.TButton", command=lambda: self.move_selected(1))
        self.down_button.pack(side="left", padx=(6, 0))
        self.clear_button = ttk.Button(queue_actions, text="Clear", style="Compact.TButton", command=self.clear_queue)
        self.clear_button.pack(side="right")
        self.remove_button = ttk.Button(queue_actions, text="Remove", style="Compact.TButton", command=self.remove_selected)
        self.remove_button.pack(side="right", padx=(0, 6))
        self.action_buttons.extend([self.up_button, self.down_button, self.clear_button, self.remove_button])

        self._build_settings(right)
        self._build_destination(right)
        self._bind_right_wheel(self.right_canvas)
        if DND_AVAILABLE:
            self._register_drops(self.root)

    def _sync_right_scroll(self, _event=None):
        try:
            width = self.right_canvas.winfo_width()
            current = int(float(self.right_canvas.itemcget(self._right_window, "width")))
            if width > 1 and current != width:
                self.right_canvas.itemconfigure(self._right_window, width=width)
            wrap = max(width - 48, 180)
            if width > 1 and hasattr(self, "settings_note"):
                self.settings_note.configure(wraplength=wrap)
            if width > 1 and hasattr(self, "collision_hint"):
                self.collision_hint.configure(wraplength=wrap)
            bbox = self.right_canvas.bbox("all")
            if not bbox:
                return
            self.right_canvas.configure(scrollregion=bbox)
            overflow = bbox[3] > self.right_canvas.winfo_height() + 2
            if overflow:
                if not self.right_scroll.winfo_ismapped():
                    self.right_scroll.grid(row=0, column=2, sticky="ns")
            elif self.right_scroll.winfo_ismapped():
                self.right_scroll.grid_remove()
                self.right_canvas.yview_moveto(0)
        except tk.TclError:
            return

    def _right_wheel(self, event):
        if isinstance(event.widget, ttk.Scale):
            return
        bbox = self.right_canvas.bbox("all")
        if not bbox or bbox[3] <= self.right_canvas.winfo_height() + 2:
            return
        steps = int(-event.delta / 120) if getattr(event, "delta", 0) else 0
        if steps == 0:
            steps = -1 if getattr(event, "delta", 0) > 0 else 1
        self.right_canvas.yview_scroll(steps, "units")
        return "break"

    def _bind_right_wheel(self, widget: tk.Misc):
        widget.bind("<MouseWheel>", self._right_wheel, add="+")
        for child in widget.winfo_children():
            self._bind_right_wheel(child)

    def _build_settings(self, parent: ttk.Frame):
        settings_border = tk.Frame(parent, bg=COLORS["border"], padx=1, pady=1)
        settings_border.pack(fill="x")
        settings_card = ttk.Frame(settings_border, style="Card.TFrame", padding=14)
        settings_card.pack(fill="x")
        ttk.Label(settings_card, text="Resize settings", style="CardTitle.TLabel").pack(anchor="w")
        self.settings_note = ttk.Label(settings_card, text="Aspect ratio is preserved. Smaller images stay at their original size.", style="CardText.TLabel", wraplength=320)
        self.settings_note.pack(anchor="w", pady=(3, 10))
        presets = ttk.Frame(settings_card, style="Card.TFrame")
        presets.pack(fill="x")
        for index, (label, size) in enumerate(PRESETS):
            button = ttk.Button(presets, text=label, style="Compact.TButton", command=lambda value=size: self._apply_preset(value))
            button.pack(side="left", padx=(0, 6) if index < len(PRESETS) - 1 else 0)
        dimensions = ttk.Frame(settings_card, style="Card.TFrame")
        dimensions.pack(fill="x", pady=(12, 0))
        dimensions.columnconfigure(0, weight=1)
        dimensions.columnconfigure(1, weight=1)
        for column, (label, variable) in enumerate((("Max width (px)", self.width_var), ("Max height (px)", self.height_var))):
            cell = ttk.Frame(dimensions, style="Card.TFrame")
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
            ttk.Label(cell, text=label, style="CardText.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=variable, style="Dark.TEntry").pack(fill="x", pady=(4, 0))
        ttk.Label(settings_card, text="Output format", style="CardText.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Combobox(settings_card, textvariable=self.format_var, values=list(FORMAT_INFO), state="readonly", style="Dark.TCombobox").pack(fill="x", pady=(4, 0))

        quality_header = ttk.Frame(settings_card, style="Card.TFrame")
        quality_header.pack(fill="x", pady=(12, 0))
        ttk.Label(quality_header, text="Quality", style="CardText.TLabel").pack(side="left")
        ttk.Label(quality_header, textvariable=self.quality_text_var, style="Count.TLabel").pack(side="right")
        self.quality_scale = ttk.Scale(settings_card, from_=1, to=100, variable=self.quality_var, style="Dark.Horizontal.TScale")
        self.quality_scale.pack(fill="x", pady=(4, 0))
        self.quality_hint = ttk.Label(settings_card, text="Applies to JPG and WEBP.", style="Hint.TLabel")
        self.quality_hint.pack(anchor="w", pady=(4, 0))

        ttk.Label(settings_card, text="When a name already exists", style="CardText.TLabel").pack(anchor="w", pady=(12, 0))
        ttk.Combobox(settings_card, textvariable=self.collision_var, values=[label for _code, label in COLLISION_OPTIONS], state="readonly", style="Dark.TCombobox").pack(fill="x", pady=(4, 0))
        self.collision_hint = ttk.Label(settings_card, textvariable=self.collision_hint_var, style="Hint.TLabel", wraplength=320)
        self.collision_hint.pack(anchor="w", pady=(4, 0))

    def _build_destination(self, parent: ttk.Frame):
        dest_border = tk.Frame(parent, bg=COLORS["border"], padx=1, pady=1)
        dest_border.pack(fill="x", pady=(10, 0))
        dest_card = ttk.Frame(dest_border, style="Card.TFrame", padding=14)
        dest_card.pack(fill="x")
        ttk.Label(dest_card, text="Destination", style="CardTitle.TLabel").pack(anchor="w")
        self.destination_hint = ttk.Label(dest_card, text="Saved for your next session", style="CardText.TLabel")
        self.destination_hint.pack(anchor="w", pady=(3, 8))
        self.destination_entry = ttk.Entry(dest_card, textvariable=self.destination_var, style="Dark.TEntry")
        self.destination_entry.pack(fill="x")
        self.destination_button = ttk.Button(dest_card, text="Browse folders…", command=self.choose_destination)
        self.destination_button.pack(anchor="e", pady=(8, 0))

    def _build_footer(self):
        self.footer = ttk.Frame(self.bottom_stack, style="App.TFrame")
        self.footer.pack(side="bottom", fill="x")
        self.button_row = ttk.Frame(self.footer, style="App.TFrame")
        self.button_row.pack(side="bottom", fill="x", pady=(8, 0))
        self.resize_button = ttk.Button(self.button_row, text="Resize photos", style="Accent.TButton", command=self.start_resize)
        self.resize_button.pack(side="right")
        self.cancel_button = ttk.Button(self.button_row, text="Cancel", command=self.cancel_resize)
        self.progress = ttk.Progressbar(self.footer, style="Run.Horizontal.TProgressbar", mode="determinate", maximum=1)
        ttk.Label(self.footer, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="top", anchor="w", fill="x")

    def _build_result_banner(self):
        self.result_frame = tk.Frame(self.bottom_stack, bg=COLORS["ok_bg"], highlightthickness=1, highlightbackground=COLORS["ok_border"], padx=12, pady=10)
        self.result_label = tk.Label(self.result_frame, text="", bg=COLORS["ok_bg"], fg=COLORS["text"], font=("Segoe UI", 9), justify="left", anchor="w", wraplength=760)
        self.result_label.pack(anchor="w", fill="x")
        self.result_actions = tk.Frame(self.result_frame, bg=COLORS["ok_bg"])
        self.result_actions.pack(anchor="e", pady=(8, 0))
        self.open_folder_button = ttk.Button(self.result_actions, text="Open folder", style="Compact.TButton", command=self._open_result_folder)
        self.errors_button = ttk.Button(self.result_actions, text="Show errors", style="Compact.TButton", command=self._toggle_errors)
        self.dismiss_button = ttk.Button(self.result_actions, text="Dismiss", style="Compact.TButton", command=self._dismiss_result)
        self.dismiss_button.pack(side="right")
        self.result_frame.bind("<Configure>", self._fit_result_wrap)

    def _build_error_panel(self):
        self.error_frame = tk.Frame(self.bottom_stack, bg=COLORS["field"], highlightthickness=1, highlightbackground=COLORS["border"], padx=8, pady=8)
        self.error_scroll = ttk.Scrollbar(self.error_frame, orient="vertical", style="Dark.Vertical.TScrollbar")
        self.error_text = tk.Text(
            self.error_frame,
            height=6,
            wrap="word",
            bg=COLORS["field"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
            highlightthickness=0,
            font=("Segoe UI", 9),
            padx=6,
            pady=4,
            yscrollcommand=self.error_scroll.set,
        )
        self.error_scroll.configure(command=self.error_text.yview)
        self.error_scroll.pack(side="right", fill="y")
        self.error_text.pack(side="left", fill="both", expand=True)
        self.error_text.configure(state="disabled")

    def _fit_result_wrap(self, event):
        self.result_label.configure(wraplength=max(280, event.width - 28))

    def _register_drops(self, widget: tk.Misc):
        try:
            widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            widget.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            widget.dnd_bind("<<DropEnter>>", self._on_drag_enter)  # type: ignore[attr-defined]
            widget.dnd_bind("<<DropPosition>>", self._on_drag_position)  # type: ignore[attr-defined]
            widget.dnd_bind("<<DropLeave>>", self._on_drag_leave)  # type: ignore[attr-defined]
        except (tk.TclError, AttributeError):
            pass
        for child in widget.winfo_children():
            self._register_drops(child)

    def _set_drop_highlight(self, active: bool):
        background = COLORS["drop_hot"] if active else COLORS["drop"]
        border = COLORS["accent"] if active else COLORS["drop_border"]
        self.drop_frame.configure(bg=background, highlightbackground=border)
        for label in self.drop_labels:
            label.configure(bg=background)

    def _on_drag_enter(self, event):
        if self._drag_clear_id is not None:
            self.root.after_cancel(self._drag_clear_id)
            self._drag_clear_id = None
        if self.is_processing:
            return REFUSE_DROP
        self._set_drop_highlight(True)
        return COPY

    def _on_drag_position(self, _event):
        return REFUSE_DROP if self.is_processing else COPY

    def _on_drag_leave(self, _event):
        if self._drag_clear_id is not None:
            self.root.after_cancel(self._drag_clear_id)
        self._drag_clear_id = self.root.after(80, lambda: self._set_drop_highlight(False))

    def _on_drop(self, event):
        self._set_drop_highlight(False)
        if self.is_processing:
            return REFUSE_DROP
        try:
            paths = [Path(item) for item in self.root.tk.splitlist(event.data)]
        except tk.TclError:
            return REFUSE_DROP
        self.add_paths(paths)
        return COPY

    def _apply_preset(self, size: int):
        self.width_var.set(str(size))
        self.height_var.set(str(size))

    def _collision_code(self) -> str:
        return COLLISION_CODES.get(self.collision_var.get(), "unique")

    def _on_quality_changed(self, *_args):
        try:
            quality = int(round(float(self.quality_var.get())))
        except (tk.TclError, ValueError):
            quality = 92
        quality = max(1, min(100, quality))
        if self.quality_text_var.get() != str(quality):
            self.quality_text_var.set(str(quality))
        self._schedule_settings_save()

    def _sync_quality_state(self, *_args):
        active = self.format_var.get() in {"JPG", "WEBP"}
        try:
            self.quality_scale.configure(state="normal" if active else "disabled")
        except tk.TclError:
            pass
        self._schedule_settings_save()

    def _sync_destination_state(self, *_args):
        beside = self._collision_code() == "beside"
        state = "disabled" if beside else "normal"
        self.destination_entry.configure(state=state)
        self.destination_button.configure(state=state)
        self.destination_hint.configure(text="Not used while saving next to each source" if beside else "Saved for your next session")
        self.collision_hint_var.set(COLLISION_HINTS.get(self._collision_code(), COLLISION_HINTS["unique"]))
        self._schedule_settings_save()

    def _set_inputs_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for button in self.action_buttons:
            button.configure(state=state)
        self.drop_frame.configure(cursor="hand2" if enabled else "arrow")
        for label in self.drop_labels:
            label.configure(cursor="hand2" if enabled else "arrow")

    def _display_name(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf" and path in self.pdf_pages:
            return f"{path.name}   ·   {pdf_page_summary(self.pdf_pages[path])}"
        return path.name

    def _row_values(self, path: Path) -> tuple[str, str, str, str]:
        return (self._display_name(path), type_label(path), str(path.parent), self.file_status.get(path, ""))

    def _status_tags(self, path: Path) -> tuple[str, ...]:
        tag = STATUS_TAGS.get(self.file_status.get(path, ""))
        return (tag,) if tag else ()

    def _new_iid(self, path: Path) -> str:
        self._iid_counter += 1
        iid = f"file-{self._iid_counter}"
        self._iid_by_path[path] = iid
        return iid

    def _refresh_queue(self, selected: int | None = None):
        self.queue.delete(*self.queue.get_children())
        self._iid_by_path.clear()
        for path in self.files:
            self.queue.insert("", "end", iid=self._new_iid(path), values=self._row_values(path), tags=self._status_tags(path))
        if selected is not None and self.files:
            selected = max(0, min(selected, len(self.files) - 1))
            iid = self._iid_by_path[self.files[selected]]
            self.queue.selection_set(iid)
            self.queue.focus(iid)
            self.queue.see(iid)
        self.count_var.set(f"{len(self.files)} file{'s' if len(self.files) != 1 else ''}")
        if self.files:
            self.empty_queue_label.place_forget()
        else:
            self.empty_queue_label.place(relx=0.46, rely=0.58, anchor="center")
            self.empty_queue_label.lift()

    def _set_status(self, path: Path, status: str):
        self.file_status[path] = status
        iid = self._iid_by_path.get(path)
        if not iid or not self.queue.exists(iid):
            return
        values = list(self.queue.item(iid, "values"))
        if len(values) != 4:
            values = list(self._row_values(path))
        values[3] = status
        tag = STATUS_TAGS.get(status)
        self.queue.item(iid, values=values, tags=(tag,) if tag else ())

    def _selected_index(self) -> int | None:
        selection = self.queue.selection()
        if not selection:
            return None
        try:
            return self.queue.index(selection[0])
        except tk.TclError:
            return None

    def remove_selected(self):
        index = self._selected_index()
        if index is None or self.is_processing:
            return
        removed = self.files.pop(index)
        self.pdf_pages.pop(removed, None)
        self.file_status.pop(removed, None)
        self._refresh_queue(index if index < len(self.files) else index - 1)
        self.status_var.set("Removed selected item")

    def clear_queue(self):
        if self.is_processing or not self.files:
            return
        if len(self.files) >= CLEAR_CONFIRM_AT:
            confirmed = messagebox.askyesno("Clear queue", f"Remove all {len(self.files)} files from the queue?", parent=self.root)
            if not confirmed:
                return
        self.files.clear()
        self.pdf_pages.clear()
        self.file_status.clear()
        self._refresh_queue()
        self.status_var.set("Queue cleared")

    def move_selected(self, direction: int):
        index = self._selected_index()
        if index is None or self.is_processing:
            return
        new_index = index + direction
        if not 0 <= new_index < len(self.files):
            return
        self.files[index], self.files[new_index] = self.files[new_index], self.files[index]
        self._refresh_queue(new_index)

    def _queue_press(self, event):
        if self.queue.identify_region(event.x, event.y) in {"heading", "separator"}:
            self.queue_drag_iid = None
            return
        row = self.queue.identify_row(event.y)
        self.queue_drag_iid = row or None

    def _queue_drag(self, event):
        if self.queue_drag_iid is None or self.is_processing or not self.files:
            return
        if not self.queue.exists(self.queue_drag_iid):
            self.queue_drag_iid = None
            return
        height = self.queue.winfo_height()
        if event.y < 24:
            self.queue.yview_scroll(-1, "units")
        elif event.y > height - 16:
            self.queue.yview_scroll(1, "units")
        if self.queue.identify_region(event.x, event.y) == "heading":
            return "break"
        target = self.queue.identify_row(event.y)
        if not target or target == self.queue_drag_iid or not self.queue.exists(target):
            return "break"
        bbox = self.queue.bbox(target)
        if not bbox:
            return "break"
        source_index = self.queue.index(self.queue_drag_iid)
        target_index = self.queue.index(target)
        midpoint = bbox[1] + bbox[3] / 2
        if source_index < target_index and event.y < midpoint:
            return "break"
        if source_index > target_index and event.y > midpoint:
            return "break"
        # Treeview.move removes the row before it inserts, so a downward move
        # needs the index after the target row.
        insert_at = target_index + 1 if source_index < target_index else target_index
        self.queue.move(self.queue_drag_iid, "", insert_at)
        self._sync_files_from_tree()
        self.queue.selection_set(self.queue_drag_iid)
        self.queue.focus(self.queue_drag_iid)
        return "break"

    def _sync_files_from_tree(self):
        by_iid = {iid: path for path, iid in self._iid_by_path.items()}
        ordered: list[Path] = []
        for iid in self.queue.get_children():
            path = by_iid.get(iid)
            if path is not None:
                ordered.append(path)
        if len(ordered) == len(self.files):
            self.files = ordered

    def _queue_release(self, _event):
        self.queue_drag_iid = None

    @staticmethod
    def _settings_path() -> Path:
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "QuickResize" / "settings.json"

    @classmethod
    def _load_settings(cls) -> dict[str, object]:
        try:
            with cls._settings_path().open("r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
                return settings if isinstance(settings, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _settings_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        destination = self.destination_var.get().strip()
        if destination:
            payload["destination"] = destination
        for key, variable in (("width", self.width_var), ("height", self.height_var)):
            text = variable.get().strip()
            if text.isdigit() and int(text) >= 1:
                payload[key] = text
        if self.format_var.get() in FORMAT_INFO:
            payload["format"] = self.format_var.get()
        try:
            quality = int(round(float(self.quality_var.get())))
        except (tk.TclError, ValueError):
            quality = 92
        payload["quality"] = max(1, min(100, quality))
        payload["collision"] = self._collision_code()
        return payload

    def _schedule_settings_save(self, *_args):
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        if self._save_after_id is not None:
            self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(500, self._save_settings)

    def _save_settings(self):
        self._save_after_id = None
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        payload = self._settings_payload()
        if "destination" not in payload and "width" not in payload:
            return
        try:
            current = self._load_settings()
            current.update(payload)
            settings_path = self._settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with settings_path.open("w", encoding="utf-8") as settings_file:
                json.dump(current, settings_file, indent=2)
        except OSError:
            pass

    def _on_close(self):
        self.cancel_event.set()
        if self._save_after_id is not None:
            self.root.after_cancel(self._save_after_id)
            self._save_after_id = None
        self._save_settings()
        self.root.destroy()

    def choose_files(self):
        if self.is_processing:
            return
        paths = filedialog.askopenfilenames(
            title="Choose files",
            filetypes=[("Supported files", " ".join(f"*{extension}" for extension in sorted(IMAGE_EXTENSIONS))), ("All files", "*.*")],
        )
        self.add_paths([Path(path) for path in paths])

    def choose_folder(self):
        if self.is_processing:
            return
        selected = filedialog.askdirectory(title="Choose a folder of photos")
        if selected:
            self.add_paths([Path(selected)])

    def _queued_match(self, path: Path) -> Path | None:
        key = path_key(path)
        for queued in self.files:
            if path_key(queued) == key:
                return queued
        return None

    def add_paths(self, paths: list[Path]):
        if self.is_processing or not paths:
            return
        if any(path.is_dir() for path in paths):
            self.status_var.set("Scanning folders…")
            self.root.update_idletasks()
        supported, unsupported = collect_inputs(paths)
        added = 0
        updated = 0
        duplicates = 0
        cancelled = 0
        decoder_skips: dict[str, int] = {}
        queued_keys = {path_key(path) for path in self.files}
        for path in supported:
            issue = decoder_issue(path)
            if issue:
                decoder_skips[issue] = decoder_skips.get(issue, 0) + 1
                continue
            normalized = normalize_path(path)
            key = path_key(normalized)
            if normalized.suffix.lower() == ".pdf":
                self.status_var.set(f"Choose pages for {normalized.name}")
                pages = self._choose_pdf_pages(normalized)
                if not pages:
                    cancelled += 1
                    continue
                existing = self._queued_match(normalized)
                if existing is not None:
                    self.pdf_pages[existing] = pages
                    updated += 1
                    continue
                self.pdf_pages[normalized] = pages
            elif key in queued_keys:
                duplicates += 1
                continue
            self.files.append(normalized)
            queued_keys.add(key)
            self.file_status.setdefault(normalized, "")
            added += 1
        self._refresh_queue()
        self.status_var.set(summarize_add(added, updated, duplicates, unsupported, decoder_skips, cancelled))

    def _choose_pdf_pages(self, path: Path) -> list[int] | None:
        if not PDF_AVAILABLE:
            messagebox.showerror("PDF support unavailable", "Install the pymupdf package to process PDFs.", parent=self.root)
            return None
        try:
            document = fitz.open(str(path))
        except Exception as exc:
            messagebox.showerror("Could not read PDF", f"{path.name}: {exc}", parent=self.root)
            return None
        page_count = document.page_count
        if page_count < 1:
            document.close()
            messagebox.showinfo("No pages", f"{path.name} does not contain any pages.", parent=self.root)
            return None

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Choose pages — {path.name}")
        dialog.transient(self.root)
        dialog.geometry("860x740")
        dialog.minsize(720, 560)
        dialog.configure(bg=COLORS["app"])
        background = COLORS["app"]
        foreground = COLORS["text"]
        muted = COLORS["muted"]
        page_vars = [tk.BooleanVar(value=False) for _ in range(page_count)]
        cards: dict[int, tk.Frame] = {}
        dialog._thumbnail_images = []  # type: ignore[attr-defined]
        dialog.page_vars = page_vars  # type: ignore[attr-defined]
        dialog.cards = cards  # type: ignore[attr-defined]
        selected_text = tk.StringVar(value=f"0 of {page_count} pages selected")
        load_text = tk.StringVar(value=f"Loading thumbnails — 0 of {page_count}")
        range_var = tk.StringVar()
        range_error = tk.StringVar(value="Example: 1-5, 8")
        dialog.page_range_var = range_var  # type: ignore[attr-defined]
        closed = False

        def update_selected_text():
            selected_text.set(f"{sum(var.get() for var in page_vars)} of {page_count} pages selected")

        def style_card(index: int):
            cell = cards.get(index)
            if cell is None:
                return
            selected = page_vars[index].get()
            fill = COLORS["selection"] if selected else COLORS["card"]
            border = COLORS["accent"] if selected else COLORS["border"]
            cell.configure(bg=fill, highlightbackground=border)
            for child in cell.winfo_children():
                options = {"bg": fill, "activebackground": fill}
                try:
                    child.configure(**options)
                except tk.TclError:
                    child.configure(bg=fill)

        def watch(index: int):
            def _on_write(*_args):
                update_selected_text()
                style_card(index)
            return _on_write

        for index, variable in enumerate(page_vars):
            variable.trace_add("write", watch(index))

        def select_all():
            for variable in page_vars:
                variable.set(True)

        def clear_selection():
            for variable in page_vars:
                variable.set(False)

        def apply_range():
            try:
                indexes = parse_page_range(range_var.get(), page_count)
            except ValueError:
                range_error.set("Use page numbers like 1-5, 8.")
                return
            chosen = set(indexes)
            range_error.set(f"Selected {len(indexes)} page{'s' if len(indexes) != 1 else ''}.")
            for index, variable in enumerate(page_vars):
                variable.set(index in chosen)

        dialog.apply_range = apply_range  # type: ignore[attr-defined]

        buttons = tk.Frame(dialog, bg=background)
        buttons.pack(side="bottom", fill="x", padx=18, pady=(8, 16))
        cancel_button = ttk.Button(buttons, text="Cancel", command=lambda: close(None))
        cancel_button.pack(side="right")
        accept_button = ttk.Button(buttons, text="Use selected pages", style="Accent.TButton", command=lambda: close(True))
        accept_button.pack(side="right", padx=(0, 8))
        dialog.accept_button = accept_button  # type: ignore[attr-defined]

        tk.Label(dialog, text="Choose PDF pages", bg=background, fg=foreground, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(dialog, text="Click a thumbnail or checkbox. Selected pages are highlighted.", bg=background, fg=muted, font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        range_row = tk.Frame(dialog, bg=background)
        range_row.pack(fill="x", padx=18, pady=(12, 0))
        ttk.Entry(range_row, textvariable=range_var, style="Dark.TEntry").pack(side="left", fill="x", expand=True)
        ttk.Button(range_row, text="Select range", style="Compact.TButton", command=apply_range).pack(side="left", padx=(8, 0))
        tk.Label(dialog, textvariable=range_error, bg=background, fg=muted, font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(4, 0))
        actions = tk.Frame(dialog, bg=background)
        actions.pack(fill="x", padx=18, pady=(8, 6))
        tk.Label(actions, textvariable=selected_text, bg=background, fg=muted, font=("Segoe UI", 9)).pack(side="left")
        ttk.Button(actions, text="Clear selection", style="Compact.TButton", command=clear_selection).pack(side="right")
        ttk.Button(actions, text="Select all", style="Compact.TButton", command=select_all).pack(side="right", padx=(0, 6))
        tk.Label(dialog, textvariable=load_text, bg=background, fg=COLORS["accent"], font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 6))

        content = tk.Frame(dialog, bg=background)
        content.pack(fill="both", expand=True, padx=18, pady=(0, 4))
        canvas = tk.Canvas(content, bg=background, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=canvas.yview, style="Dark.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        thumb_frame = tk.Frame(canvas, bg=background)
        canvas_window = canvas.create_window((0, 0), window=thumb_frame, anchor="nw")
        thumb_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        for column in range(3):
            thumb_frame.grid_columnconfigure(column, weight=1)

        def on_wheel(event):
            try:
                if not dialog.winfo_exists():
                    return "break"
            except tk.TclError:
                return "break"
            steps = int(-event.delta / 120) if event.delta else 0
            if steps == 0:
                steps = -1 if event.delta > 0 else 1
            canvas.yview_scroll(steps, "units")
            return "break"

        dialog.bind_all("<MouseWheel>", on_wheel)
        dialog.bind("<Escape>", lambda _event: close(None))

        result: list[int] | None = None

        def cleanup():
            nonlocal closed
            if closed:
                return
            closed = True
            try:
                dialog.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            try:
                if document is not None and not getattr(document, "is_closed", False):
                    document.close()
            except Exception:
                pass

        def close(accepted: bool | None):
            nonlocal result
            if accepted:
                chosen_pages = [index for index, variable in enumerate(page_vars) if variable.get()]
                if not chosen_pages:
                    messagebox.showinfo("No pages selected", "Select at least one PDF page to continue.", parent=dialog)
                    return
                result = chosen_pages
            cleanup()
            if dialog.winfo_exists():
                dialog.destroy()

        def render_batch(start: int):
            if closed or not dialog.winfo_exists():
                cleanup()
                return
            end = min(start + 2, page_count)
            for page_number in range(start, end):
                cell = tk.Frame(thumb_frame, bg=COLORS["card"], highlightthickness=2, highlightbackground=COLORS["border"], padx=8, pady=8, cursor="hand2")
                cell.grid(row=page_number // 3, column=page_number % 3, sticky="nsew", padx=6, pady=6)
                cards[page_number] = cell
                try:
                    pdf_page = document.load_page(page_number)
                    scale = min(0.45, 180 / max(pdf_page.rect.width, 1))
                    pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                    thumbnail = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    thumbnail.thumbnail((170, 130), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(thumbnail)
                    dialog._thumbnail_images.append(photo)  # type: ignore[attr-defined]
                    preview = tk.Label(cell, image=photo, bg=COLORS["card"], cursor="hand2")
                except Exception:
                    preview = tk.Label(cell, text="Preview unavailable", bg=COLORS["card"], fg=muted, font=("Segoe UI", 8), cursor="hand2", padx=8, pady=24)
                preview.pack()
                check = tk.Checkbutton(
                    cell,
                    text=f"Page {page_number + 1}",
                    variable=page_vars[page_number],
                    bg=COLORS["card"],
                    fg=foreground,
                    activebackground=COLORS["card"],
                    activeforeground=foreground,
                    selectcolor=COLORS["field"],
                    font=("Segoe UI", 9),
                    cursor="hand2",
                )
                check.pack(anchor="w", pady=(5, 0))

                def toggle(_event, index=page_number):
                    page_vars[index].set(not page_vars[index].get())

                cell.bind("<Button-1>", toggle)
                preview.bind("<Button-1>", toggle)
                style_card(page_number)
                load_text.set(f"Loading thumbnails — {page_number + 1} of {page_count}")
            if end < page_count:
                dialog.after(1, lambda: render_batch(end))
            else:
                load_text.set("Thumbnails ready")

        dialog.protocol("WM_DELETE_WINDOW", lambda: close(None))
        try:
            dialog.grab_set()
        except tk.TclError:
            pass
        dialog.focus_set()
        dialog.after(10, lambda: render_batch(0))
        try:
            self.root.wait_window(dialog)
        finally:
            cleanup()
        return result

    def choose_destination(self):
        if self._collision_code() == "beside":
            return
        initial = self.destination_var.get().strip()
        selected = filedialog.askdirectory(title="Choose output folder", initialdir=initial if Path(initial).is_dir() else str(Path.home()))
        if selected:
            self.destination_var.set(selected)
            self._save_settings()

    def start_resize(self):
        if self.is_processing:
            return
        try:
            width, height = int(self.width_var.get()), int(self.height_var.get())
            if width < 1 or height < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid size", "Enter positive whole numbers for width and height.")
            return
        if not self.files:
            messagebox.showinfo("No photos", "Drop files here or use Add files.")
            return
        if self.format_var.get() not in FORMAT_INFO:
            messagebox.showerror("Invalid format", "Choose an output format.")
            return
        collision = self._collision_code()
        destination = self.destination_var.get().strip()
        if collision != "beside" and not destination:
            messagebox.showerror("No destination", "Choose a destination folder.")
            return
        try:
            quality = int(round(float(self.quality_var.get())))
        except (tk.TclError, ValueError):
            quality = 92
        quality = max(1, min(100, quality))
        jobs: list[tuple[Path, int | None]] = []
        for source in list(self.files):
            if source.suffix.lower() == ".pdf":
                pages = list(self.pdf_pages.get(source, []))
                if not pages:
                    continue
                jobs.extend((source, page) for page in pages)
            else:
                jobs.append((source, None))
        if not jobs:
            messagebox.showinfo("No photos", "Add at least one file with pages selected.")
            return
        self._save_settings()
        self._dismiss_result()
        self.cancel_event.clear()
        self.is_processing = True
        self._run_beside = collision == "beside"
        self._job_total = len(jobs)
        self._jobs_finished = 0
        self._expected = {}
        self._ok_count = {}
        self._fail_count = {}
        self._paths_by_text = {}
        for source, _page in jobs:
            self._expected[source] = self._expected.get(source, 0) + 1
            self._ok_count[source] = 0
            self._fail_count[source] = 0
            self._paths_by_text[str(source)] = source
        for source in self.files:
            self._set_status(source, "Pending")
        self._set_inputs_enabled(False)
        self.resize_button.configure(state="disabled")
        self.cancel_button.configure(state="normal", text="Cancel")
        self.cancel_button.pack(side="right", padx=(0, 8))
        self.progress.configure(maximum=max(len(jobs), 1), value=0)
        self.progress.pack(side="bottom", fill="x", pady=(8, 0))
        self.status_var.set(f"Resizing 1 of {len(jobs)}…")
        threading.Thread(
            target=self._resize_worker,
            args=(width, height, destination, self.format_var.get(), quality, collision, jobs),
            daemon=True,
        ).start()

    def cancel_resize(self):
        if not self.is_processing:
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled", text="Stopping…")
        self.status_var.set("Finishing the current photo…")

    def _resize_worker(self, width: int, height: int, destination: str, fmt: str, quality: int, collision: str, jobs: list[tuple[Path, int | None]]):
        output_dir = Path(destination).expanduser() if destination else Path.home()
        if collision != "beside":
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.events.put(("done", {"successes": 0, "errors": [f"Destination folder: {exc}"], "folder": str(output_dir), "cancelled": False, "beside": False}))
                return
        pil_format, extension = FORMAT_INFO[fmt]
        successes = 0
        errors: list[str] = []
        used: set[str] = set()
        total = len(jobs)
        cancelled = False
        saved_folder = str(output_dir)
        for index, (source, page) in enumerate(jobs, start=1):
            if self.cancel_event.is_set():
                cancelled = True
                break
            label = source.name if page is None else f"{source.name} page {page + 1}"
            self.events.put(("start", (index, total, label, str(source))))
            try:
                folder = source.parent if collision == "beside" else output_dir
                image = self._load_image(source, page, (width, height))
                image = ImageOps.exif_transpose(image)
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
                if fmt == "JPG":
                    if image.mode in ("RGBA", "LA", "P"):
                        background = Image.new("RGB", image.size, "white")
                        if image.mode == "P":
                            image = image.convert("RGBA")
                        alpha = image.getchannel("A") if "A" in image.getbands() else None
                        background.paste(image, mask=alpha)
                        image = background
                    else:
                        image = image.convert("RGB")
                elif fmt == "BMP" and image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                output = plan_output_path(folder, source, page, extension, collision, used)
                save_options = {"quality": quality} if fmt in ("JPG", "WEBP") else {}
                image.save(output, format=pil_format, **save_options)
                successes += 1
                if collision == "beside" and successes == 1:
                    saved_folder = str(folder)
                self.events.put(("file_done", (str(source), True, "")))
            except Exception as exc:
                name = source.name if page is None else f"{source.name} page {page + 1}"
                errors.append(f"{name}: {exc}")
                self.events.put(("file_done", (str(source), False, str(exc))))
        self.events.put(("done", {"successes": successes, "errors": errors, "folder": saved_folder, "cancelled": cancelled, "beside": collision == "beside"}))

    @staticmethod
    def _load_image(source: Path, page: int | None = None, target_size: tuple[int, int] | None = None) -> Image.Image:
        if source.suffix.lower() == ".pdf":
            if not PDF_AVAILABLE:
                raise RuntimeError("PDF support requires the pymupdf package")
            document = fitz.open(str(source))
            try:
                pdf_page = document.load_page(page or 0)
                page_rect = pdf_page.rect
                target_width, target_height = target_size or (1600, 1600)
                # PDF coordinates are points at 72 DPI. Render large enough that
                # the later aspect-ratio-preserving resize can reach the target.
                scale = max(target_width / page_rect.width, target_height / page_rect.height, 1.0)
                pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            finally:
                document.close()
        if source.suffix.lower() in {".crw", ".cr3"}:
            if not CRW_AVAILABLE:
                raise RuntimeError("CRW/CR3 support requires the rawpy package")
            with rawpy.imread(str(source)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            return Image.fromarray(rgb)
        with Image.open(source) as image:
            return image.copy()

    def _stored_path(self, path_text: str) -> Path | None:
        stored = self._paths_by_text.get(path_text)
        if stored is not None:
            return stored
        candidate = Path(path_text)
        return self._queued_match(candidate)

    def _on_start_file(self, index: int, total: int, label: str, path_text: str):
        if self.cancel_event.is_set():
            self.status_var.set("Finishing the current photo…")
        else:
            self.status_var.set(f"Resizing {label} — {index} of {total}")
        stored = self._stored_path(path_text)
        if stored is not None:
            self._set_status(stored, "Working")

    def _on_file_done(self, path_text: str, ok: bool):
        stored = self._stored_path(path_text)
        self._jobs_finished += 1
        try:
            self.progress.configure(value=self._jobs_finished)
        except tk.TclError:
            return
        if stored is None:
            return
        if ok:
            self._ok_count[stored] = self._ok_count.get(stored, 0) + 1
        else:
            self._fail_count[stored] = self._fail_count.get(stored, 0) + 1
        finished = self._ok_count.get(stored, 0) + self._fail_count.get(stored, 0)
        expected = self._expected.get(stored, 1)
        if finished < expected:
            status = "Working"
        elif self._fail_count.get(stored, 0) == 0:
            status = "Done"
        elif self._ok_count.get(stored, 0) == 0:
            status = "Failed"
        else:
            status = "Partial"
        self._set_status(stored, status)
        if self.cancel_event.is_set():
            self.status_var.set("Finishing the current photo…")

    def _finish_run(self, payload: dict[str, object]):
        successes = int(payload.get("successes", 0))
        errors = payload.get("errors", [])
        if not isinstance(errors, list):
            errors = []
        error_lines = [str(item) for item in errors]
        folder = str(payload.get("folder", ""))
        cancelled = bool(payload.get("cancelled"))
        beside = bool(payload.get("beside"))
        self.is_processing = False
        self._set_inputs_enabled(True)
        self.resize_button.configure(state="normal")
        for source, status in list(self.file_status.items()):
            if status == "Pending":
                self._set_status(source, "")
        try:
            self.cancel_button.pack_forget()
            self.progress.pack_forget()
        except tk.TclError:
            pass
        if cancelled:
            self.status_var.set(f"Stopped — {successes} saved")
        elif error_lines and successes:
            self.status_var.set(f"Saved {successes}. {len(error_lines)} failed")
        elif error_lines:
            self.status_var.set("Finished with errors")
        else:
            self.status_var.set(f"Saved {successes} photo{'s' if successes != 1 else ''}")
        self._show_result(successes, error_lines, folder, cancelled, beside)

    def _show_result(self, successes: int, errors: list[str], folder: str, cancelled: bool, beside: bool):
        warn = bool(errors) or cancelled or successes == 0
        background = COLORS["warn_bg"] if warn else COLORS["ok_bg"]
        border = COLORS["warn_border"] if warn else COLORS["ok_border"]
        self.result_frame.configure(bg=background, highlightbackground=border)
        self.result_label.configure(bg=background)
        self.result_actions.configure(bg=background)
        if cancelled and successes == 0 and not errors:
            message = "Stopped before any photos were saved."
        elif cancelled:
            message = f"Stopped. Saved {successes} photo{'s' if successes != 1 else ''}."
        elif successes == 0:
            message = "No photos were saved."
        else:
            message = f"Saved {successes} photo{'s' if successes != 1 else ''}."
        if errors:
            message += f" {len(errors)} failed."
        if successes and beside:
            message += " Files are next to the originals."
        elif successes and folder:
            message += f" Folder: {folder}"
        self.result_label.configure(text=message)
        self._result_folder = folder if successes and folder and Path(folder).is_dir() else ""
        self.open_folder_button.pack_forget()
        self.errors_button.pack_forget()
        if self._result_folder:
            self.open_folder_button.pack(side="right", padx=(0, 6))
        if errors:
            self._set_error_lines(errors)
            self.errors_button.configure(text="Hide errors")
            self.errors_button.pack(side="right", padx=(0, 6))
            self._errors_visible = True
        else:
            self._errors_visible = False
            self.error_frame.pack_forget()
        self.result_frame.pack(side="top", fill="x", pady=(0, 8))
        if errors:
            self.error_frame.pack(side="top", fill="x", pady=(0, 8))

    def _set_error_lines(self, errors: list[str]):
        self.error_text.configure(state="normal")
        self.error_text.delete("1.0", "end")
        self.error_text.insert("1.0", "\n".join(errors))
        self.error_text.configure(state="disabled")

    def _toggle_errors(self):
        if self._errors_visible:
            self.error_frame.pack_forget()
            self._errors_visible = False
            self.errors_button.configure(text="Show errors")
            return
        self.error_frame.pack(side="top", fill="x", pady=(0, 8))
        self._errors_visible = True
        self.errors_button.configure(text="Hide errors")

    def _dismiss_result(self):
        self.result_frame.pack_forget()
        self.error_frame.pack_forget()
        self._errors_visible = False

    def _open_result_folder(self):
        if not self._result_folder:
            return
        try:
            os.startfile(self._result_folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self.status_var.set(f"Could not open folder: {exc}")

    def _poll_events(self):
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "start":
                    index, total, label, path_text = data  # type: ignore[misc]
                    self._on_start_file(index, total, label, path_text)
                elif kind == "file_done":
                    path_text, ok, _error = data  # type: ignore[misc]
                    self._on_file_done(path_text, bool(ok))
                elif kind == "done":
                    self._finish_run(data if isinstance(data, dict) else {})
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.root.after(80, self._poll_events)
        except tk.TclError:
            return


def main():
    enable_dpi_awareness()
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    asset_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
    icon_path = asset_dir / "QuickResize.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass
    png_icon_path = asset_dir / "quickresize-icon.png"
    if png_icon_path.exists():
        root._app_icon = ImageTk.PhotoImage(Image.open(png_icon_path))
        root.iconphoto(True, root._app_icon)
    QuickResizeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
