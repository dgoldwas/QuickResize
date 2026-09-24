"""QuickResize - lightweight Windows bulk image resizer.

Run with: python quickresize.py
Install dependencies with: pip install -r requirements.txt
"""

from __future__ import annotations

import os
import json
import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

APP_VERSION = "2026.09.23.1"

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_AVAILABLE = True
except ImportError:
    HEIC_AVAILABLE = False

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
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
    "drop_border": "#3a638e",
    "selection": "#294d75",
}


class QuickResizeApp:
    def __init__(self, root: tk.Misc):
        self.root = root
        self.root.title(f"QuickResize v{APP_VERSION}")
        self.root.geometry("980x730")
        self.root.minsize(820, 650)
        self.root.configure(bg=COLORS["app"])

        self.files: list[Path] = []
        self.pdf_pages: dict[Path, list[int]] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.is_processing = False

        settings = self._load_settings()
        self.width_var = tk.StringVar(value="1600")
        self.height_var = tk.StringVar(value="1600")
        self.format_var = tk.StringVar(value="JPG")
        default_destination = Path.home() / "Pictures" / "QuickResize"
        saved_destination = settings.get("destination")
        if not isinstance(saved_destination, str) or not saved_destination.strip():
            saved_destination = None
        self.destination_var = tk.StringVar(value=saved_destination or str(default_destination))
        self.status_var = tk.StringVar(value="Ready — drop photos here to begin")
        self.count_var = tk.StringVar(value="0 files")
        self.drop_widgets: list[tk.Widget] = []
        self.queue_drag_index: int | None = None
        self._save_after_id: str | None = None
        self._build_ui()
        self.destination_var.trace_add("write", self._schedule_settings_save)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_events)

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
        style.configure("TButton", background=COLORS["button"], foreground=COLORS["text"], font=("Segoe UI", 9), padding=(11, 8), relief="flat", borderwidth=0)
        style.configure("Compact.TButton", background=COLORS["button"], foreground=COLORS["text"], font=("Segoe UI", 9), padding=(8, 6), relief="flat", borderwidth=0)
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="#081321", font=("Segoe UI", 10, "bold"), padding=(20, 10), relief="flat", borderwidth=0)
        style.map("TButton", background=[("active", COLORS["button_hover"])], foreground=[("disabled", COLORS["muted"])])
        style.map("Compact.TButton", background=[("active", COLORS["button_hover"])])
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["button"])], foreground=[("disabled", COLORS["muted"])])
        style.configure("Dark.TEntry", fieldbackground=COLORS["field"], foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["border"], padding=(8, 7))
        style.map("Dark.TEntry", fieldbackground=[("disabled", COLORS["field"])])
        style.configure("Dark.TCombobox", fieldbackground=COLORS["field"], background=COLORS["field"], foreground=COLORS["text"], arrowcolor=COLORS["text"], bordercolor=COLORS["border"], padding=(8, 7))
        style.map("Dark.TCombobox", fieldbackground=[("readonly", COLORS["field"])], foreground=[("readonly", COLORS["text"])])

        outer = ttk.Frame(self.root, style="App.TFrame", padding=(26, 22))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 20))
        ttk.Label(header, text="QuickResize", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Batch image resizing, made simple", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(header, text=f"v{APP_VERSION}", style="Subtitle.TLabel").place(relx=1, x=0, y=12, anchor="ne")

        footer = ttk.Frame(outer, style="App.TFrame")
        footer.pack(side="bottom", fill="x", pady=(18, 0))
        ttk.Label(footer, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left")
        self.resize_button = ttk.Button(footer, text="Resize photos", style="Accent.TButton", command=self.start_resize)
        self.resize_button.pack(side="right")

        workspace = ttk.Frame(outer, style="App.TFrame")
        workspace.pack(fill="both", expand=True)
        workspace.columnconfigure(0, weight=3)
        workspace.columnconfigure(1, weight=2)
        workspace.rowconfigure(0, weight=1)
        left = ttk.Frame(workspace, style="App.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right = ttk.Frame(workspace, style="App.TFrame")
        right.grid(row=0, column=1, sticky="nsew")

        drop = tk.Frame(left, bg=COLORS["drop"], highlightthickness=1, highlightbackground=COLORS["drop_border"], cursor="hand2")
        drop.pack(fill="x", ipady=18)
        self.drop_widgets.append(drop)
        drop.bind("<Button-1>", lambda _event: self.choose_files())
        icon = tk.Label(drop, text="+", bg=COLORS["drop"], fg=COLORS["accent"], font=("Segoe UI", 28, "bold"), cursor="hand2")
        title = tk.Label(drop, text="Drop files or folders", bg=COLORS["drop"], fg=COLORS["text"], font=("Segoe UI", 14, "bold"), cursor="hand2")
        note_text = "Or click to browse files" if DND_AVAILABLE else "Click to browse files"
        note = tk.Label(drop, text=note_text, bg=COLORS["drop"], fg=COLORS["muted"], font=("Segoe UI", 9), cursor="hand2")
        for child in (icon, title, note):
            child.pack()
            child.bind("<Button-1>", lambda _event: self.choose_files())
        self.drop_widgets.extend([icon, title, note])
        if DND_AVAILABLE:
            for widget in self.drop_widgets:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

        queue_border = tk.Frame(left, bg=COLORS["border"], padx=1, pady=1)
        queue_border.pack(fill="both", expand=True, pady=(14, 0))
        queue_card = ttk.Frame(queue_border, style="Card.TFrame", padding=16)
        queue_card.pack(fill="both", expand=True)
        queue_heading = ttk.Frame(queue_card, style="Card.TFrame")
        queue_heading.pack(fill="x")
        ttk.Label(queue_heading, text="Queue", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(queue_heading, textvariable=self.count_var, style="Count.TLabel").pack(side="right")
        queue_body = tk.Frame(queue_card, bg=COLORS["card"])
        queue_body.pack(fill="both", expand=True, pady=(14, 10))
        self.listbox = tk.Listbox(queue_body, height=8, borderwidth=0, highlightthickness=0, font=("Segoe UI", 9),
                                  activestyle="none", bg=COLORS["card"], fg=COLORS["text"],
                                  selectbackground=COLORS["selection"], selectforeground=COLORS["text"])
        self.listbox.pack(fill="both", expand=True)
        self.empty_queue_label = tk.Label(queue_body, text="No files queued yet", bg=COLORS["card"], fg=COLORS["muted"], font=("Segoe UI", 10))
        self.empty_queue_label.place(relx=0.5, rely=0.5, anchor="center")
        queue_actions = ttk.Frame(queue_card, style="Card.TFrame")
        queue_actions.pack(fill="x")
        ttk.Button(queue_actions, text="Up", style="Compact.TButton", command=lambda: self.move_selected(-1)).pack(side="left")
        ttk.Button(queue_actions, text="Down", style="Compact.TButton", command=lambda: self.move_selected(1)).pack(side="left", padx=(6, 0))
        ttk.Button(queue_actions, text="Clear", style="Compact.TButton", command=self.clear_queue).pack(side="right")
        ttk.Button(queue_actions, text="Remove", style="Compact.TButton", command=self.remove_selected).pack(side="right", padx=(0, 6))
        self.listbox.bind("<ButtonPress-1>", self._queue_press)
        self.listbox.bind("<B1-Motion>", self._queue_drag)
        self.listbox.bind("<ButtonRelease-1>", self._queue_release)

        settings_border = tk.Frame(right, bg=COLORS["border"], padx=1, pady=1)
        settings_border.pack(fill="x")
        settings_card = ttk.Frame(settings_border, style="Card.TFrame", padding=18)
        settings_card.pack(fill="x")
        ttk.Label(settings_card, text="Resize settings", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(settings_card, text="Fit inside these dimensions", style="CardText.TLabel").pack(anchor="w", pady=(3, 18))
        dimensions = ttk.Frame(settings_card, style="Card.TFrame")
        dimensions.pack(fill="x")
        dimensions.columnconfigure(0, weight=1)
        dimensions.columnconfigure(1, weight=1)
        for column, (label, variable) in enumerate((("Max width (px)", self.width_var), ("Max height (px)", self.height_var))):
            cell = ttk.Frame(dimensions, style="Card.TFrame")
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
            ttk.Label(cell, text=label, style="CardText.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=variable, style="Dark.TEntry").pack(fill="x", pady=(6, 0))
        ttk.Label(settings_card, text="Output format", style="CardText.TLabel").pack(anchor="w", pady=(20, 0))
        ttk.Combobox(settings_card, textvariable=self.format_var, values=list(FORMAT_INFO), state="readonly",
                     style="Dark.TCombobox").pack(fill="x", pady=(6, 0))
        ttk.Label(settings_card, text="Aspect ratio is always preserved.", style="CardText.TLabel").pack(anchor="w", pady=(16, 0))

        dest_border = tk.Frame(right, bg=COLORS["border"], padx=1, pady=1)
        dest_border.pack(fill="x", pady=(14, 0))
        dest_card = ttk.Frame(dest_border, style="Card.TFrame", padding=18)
        dest_card.pack(fill="x")
        ttk.Label(dest_card, text="Destination", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(dest_card, text="Saved for your next session", style="CardText.TLabel").pack(anchor="w", pady=(3, 12))
        ttk.Entry(dest_card, textvariable=self.destination_var, style="Dark.TEntry").pack(fill="x")
        ttk.Button(dest_card, text="Browse folders…", command=self.choose_destination).pack(anchor="e", pady=(10, 0))

    def _refresh_queue(self, selected: int | None = None):
        self.listbox.delete(0, "end")
        for path in self.files:
            suffix = f" (pages {', '.join(str(page + 1) for page in self.pdf_pages[path])})" if path.suffix.lower() == ".pdf" else ""
            self.listbox.insert("end", f"  {path.name}{suffix}   ·   {path.parent}")
        if selected is not None and self.files:
            selected = max(0, min(selected, len(self.files) - 1))
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        self.count_var.set(f"{len(self.files)} file{'s' if len(self.files) != 1 else ''}")
        if self.files:
            self.empty_queue_label.place_forget()
        else:
            self.empty_queue_label.place(relx=0.5, rely=0.5, anchor="center")

    def remove_selected(self):
        selection = self.listbox.curselection()
        if not selection or self.is_processing:
            return
        index = selection[0]
        self.files.pop(index)
        self._refresh_queue(index if index < len(self.files) else index - 1)
        self.status_var.set("Removed selected item")

    def clear_queue(self):
        if self.is_processing or not self.files:
            return
        self.files.clear()
        self.pdf_pages.clear()
        self._refresh_queue()
        self.status_var.set("Queue cleared")

    def move_selected(self, direction: int):
        selection = self.listbox.curselection()
        if not selection or self.is_processing:
            return
        old_index = selection[0]
        new_index = old_index + direction
        if not 0 <= new_index < len(self.files):
            return
        self.files[old_index], self.files[new_index] = self.files[new_index], self.files[old_index]
        self._refresh_queue(new_index)

    def _queue_press(self, event):
        self.queue_drag_index = self.listbox.nearest(event.y)

    def _queue_drag(self, event):
        if self.queue_drag_index is None or self.is_processing or not self.files:
            return
        target = max(0, min(self.listbox.nearest(event.y), len(self.files) - 1))
        if target != self.queue_drag_index:
            item = self.files.pop(self.queue_drag_index)
            self.files.insert(target, item)
            self.queue_drag_index = target
            self._refresh_queue(target)

    def _queue_release(self, _event):
        self.queue_drag_index = None


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

    def _schedule_settings_save(self, *_args):
        if self._save_after_id is not None:
            self.root.after_cancel(self._save_after_id)
        self._save_after_id = self.root.after(500, self._save_settings)

    def _save_settings(self):
        self._save_after_id = None
        destination = self.destination_var.get().strip()
        if not destination:
            return
        try:
            settings_path = self._settings_path()
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            with settings_path.open("w", encoding="utf-8") as settings_file:
                json.dump({"destination": destination}, settings_file, indent=2)
        except OSError:
            # A read-only profile should not prevent the app from working.
            pass

    def _on_close(self):
        if self._save_after_id is not None:
            self.root.after_cancel(self._save_after_id)
        self._save_settings()
        self.root.destroy()


    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        self.add_paths([Path(p) for p in paths])

    def choose_files(self):
        paths = filedialog.askopenfilenames(title="Choose photos", filetypes=[("Image files", " ".join(f"*{x}" for x in sorted(IMAGE_EXTENSIONS))), ("All files", "*.*")])
        self.add_paths([Path(p) for p in paths])

    def add_paths(self, paths: list[Path]):
        found: list[Path] = []
        for path in paths:
            if path.is_dir():
                found.extend(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
            elif path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                found.append(path)
        for path in found:
            if path.suffix.lower() == ".pdf":
                pages = self._choose_pdf_pages(path)
                if not pages:
                    continue
                self.pdf_pages[path] = pages
            if path not in self.files:
                self.files.append(path)
        self._refresh_queue()
        if found:
            self.status_var.set(f"Added {len(found)} photo{'s' if len(found) != 1 else ''}")

    def _choose_pdf_pages(self, path: Path) -> list[int] | None:
        if not PDF_AVAILABLE:
            messagebox.showerror("PDF support unavailable", "Install the pymupdf package to process PDFs.")
            return None
        try:
            document = fitz.open(str(path))
            page_count = document.page_count
            document.close()
        except Exception as exc:
            messagebox.showerror("Could not read PDF", f"{path.name}: {exc}")
            return None
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Choose pages — {path.name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.geometry("820x700")
        dialog.minsize(700, 560)
        background = COLORS["app"]
        foreground = COLORS["text"]
        muted = COLORS["muted"]
        dialog.configure(bg=background)
        tk.Label(dialog, text="Choose PDF pages", bg=background, fg=foreground, font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(dialog, text="Click a thumbnail or checkbox to include it in the resize.", bg=background, fg=muted, font=("Segoe UI", 9)).pack(anchor="w", padx=18)
        actions = tk.Frame(dialog, bg=background)
        actions.pack(fill="x", padx=18, pady=(12, 10))
        selected_text = tk.StringVar(value=f"0 of {page_count} pages selected")
        tk.Label(actions, textvariable=selected_text, bg=background, fg=muted, font=("Segoe UI", 9)).pack(side="left")
        content = tk.Frame(dialog, bg=background)
        content.pack(fill="both", expand=True, padx=18)
        canvas = tk.Canvas(content, bg=background, highlightthickness=0)
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        thumb_frame = tk.Frame(canvas, bg=background)
        canvas_window = canvas.create_window((0, 0), window=thumb_frame, anchor="nw")
        thumb_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        for column in range(3):
            thumb_frame.grid_columnconfigure(column, weight=1)
        page_vars: list[tk.BooleanVar] = []
        dialog._thumbnail_images = []

        def update_selected_text():
            selected_text.set(f"{sum(var.get() for var in page_vars)} of {page_count} pages selected")

        def select_all():
            for var in page_vars:
                var.set(True)
            update_selected_text()

        def clear_selection():
            for var in page_vars:
                var.set(False)
            update_selected_text()

        ttk.Button(actions, text="Clear selection", command=clear_selection).pack(side="right")
        ttk.Button(actions, text="Select all", command=select_all).pack(side="right", padx=(0, 6))
        document = fitz.open(str(path))
        for page_number in range(page_count):
            pdf_page = document.load_page(page_number)
            pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(0.35, 0.35), alpha=False)
            thumbnail = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            thumbnail.thumbnail((170, 130), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumbnail)
            dialog._thumbnail_images.append(photo)
            cell = tk.Frame(thumb_frame, bg=COLORS["card"], highlightthickness=1, highlightbackground=COLORS["border"], padx=8, pady=8, cursor="hand2")
            cell.grid(row=page_number // 3, column=page_number % 3, sticky="nsew", padx=6, pady=6)
            thumbnail_label = tk.Label(cell, image=photo, bg=COLORS["card"], cursor="hand2")
            thumbnail_label.pack()
            var = tk.BooleanVar(value=False)
            page_vars.append(var)
            check = tk.Checkbutton(cell, text=f"Page {page_number + 1}", variable=var, command=update_selected_text, bg=COLORS["card"], fg=foreground, activebackground=COLORS["card"], activeforeground=foreground, selectcolor=COLORS["field"], font=("Segoe UI", 9))
            check.pack(anchor="w", pady=(5, 0))

            def toggle(_event, selected_var=var):
                selected_var.set(not selected_var.get())
                update_selected_text()

            cell.bind("<Button-1>", toggle)
            thumbnail_label.bind("<Button-1>", toggle)
        document.close()
        result: list[int] | None = None

        def accept():
            nonlocal result
            result = [index for index, var in enumerate(page_vars) if var.get()]
            if not result:
                messagebox.showinfo("No pages selected", "Select at least one PDF page to continue.", parent=dialog)
                return
            dialog.destroy()

        def cancel():
            dialog.destroy()

        buttons = ttk.Frame(dialog, style="App.TFrame")
        buttons.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="right")
        ttk.Button(buttons, text="Use selected pages", command=accept).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.root.wait_window(dialog)
        return result

    def choose_destination(self):
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
            messagebox.showinfo("No photos", "Drop photos here or click the drop area to choose some.")
            return
        if self.format_var.get() not in FORMAT_INFO:
            messagebox.showerror("Invalid format", "Choose an output format.")
            return
        destination = self.destination_var.get().strip()
        if not destination:
            messagebox.showerror("No destination", "Choose a destination folder.")
            return
        self._save_settings()
        self.is_processing = True
        self.resize_button.configure(state="disabled")
        self.status_var.set("Resizing…")
        threading.Thread(target=self._resize_worker, args=(width, height, destination, self.format_var.get()), daemon=True).start()

    def _resize_worker(self, width: int, height: int, destination: str, fmt: str):
        output_dir = Path(destination).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.events.put(("done", (0, [f"Destination folder: {exc}"], str(output_dir))))
            return
        pil_format, extension = FORMAT_INFO[fmt]
        successes = 0
        errors: list[str] = []
        jobs = [(source, page) for source in self.files for page in (self.pdf_pages.get(source, [None]) if source.suffix.lower() == ".pdf" else [None])]
        for index, (source, page) in enumerate(jobs, start=1):
            try:
                image = self._load_image(source, page, (width, height))
                image = ImageOps.exif_transpose(image)
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
                if fmt == "JPG":
                    if image.mode in ("RGBA", "LA", "P"):
                        background = Image.new("RGB", image.size, "white")
                        if image.mode == "P":
                            image = image.convert("RGBA")
                        background.paste(image, mask=image.getchannel("A") if "A" in image.getbands() else None)
                        image = background
                    else:
                        image = image.convert("RGB")
                elif fmt == "BMP" and image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                page_suffix = f"_page_{page + 1:03d}" if page is not None else ""
                output = output_dir / f"{source.stem}{page_suffix}{extension}"
                if output.resolve() == source.resolve():
                    output = output_dir / f"{source.stem}_resized{extension}"
                save_options = {"quality": 92} if fmt in ("JPG", "WEBP") else {}
                image.save(output, format=pil_format, **save_options)
                successes += 1
            except Exception as exc:  # individual files should not stop a batch
                errors.append(f"{source.name}: {exc}")
            self.events.put(("progress", (index, len(jobs), successes)))
        self.events.put(("done", (successes, errors, str(output_dir))))

    @staticmethod
    def _load_image(source: Path, page: int | None = None, target_size: tuple[int, int] | None = None) -> Image.Image:
        if source.suffix.lower() == ".pdf":
            if not PDF_AVAILABLE:
                raise RuntimeError("PDF support requires the pymupdf package")
            document = fitz.open(str(source))
            pdf_page = document.load_page(page or 0)
            page_rect = pdf_page.rect
            target_width, target_height = target_size or (1600, 1600)
            # PDF coordinates are points at 72 DPI. Render large enough that
            # the later aspect-ratio-preserving resize can reach the target.
            scale = max(target_width / page_rect.width, target_height / page_rect.height, 1.0)
            pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            document.close()
            return image
        if source.suffix.lower() in (".crw", ".cr3"):
            if not CRW_AVAILABLE:
                raise RuntimeError("CRW/CR3 support requires the rawpy package")
            with rawpy.imread(str(source)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8)
            return Image.fromarray(rgb)
        with Image.open(source) as image:
            return image.copy()

    def _poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "progress":
                    index, total, successes = data
                    self.status_var.set(f"Resizing {index} of {total}…")
                elif kind == "done":
                    successes, errors, output_dir = data
                    self.is_processing = False
                    self.resize_button.configure(state="normal")
                    self.status_var.set(f"Done — {successes} photo{'s' if successes != 1 else ''} saved")
                    if errors:
                        messagebox.showwarning("Finished with some errors", f"Saved {successes} photos.\n\n" + "\n".join(errors[:8]))
                    else:
                        messagebox.showinfo("Resize complete", f"Saved {successes} photos to:\n{output_dir}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    asset_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
    icon_path = asset_dir / "QuickResize.ico"
    if icon_path.exists():
        root.iconbitmap(str(icon_path))
    # iconphoto provides a reliable Tk fallback for title bars and taskbar icons.
    png_icon_path = asset_dir / "quickresize-icon.png"
    if png_icon_path.exists():
        root._app_icon = ImageTk.PhotoImage(Image.open(png_icon_path))
        root.iconphoto(True, root._app_icon)
    QuickResizeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
