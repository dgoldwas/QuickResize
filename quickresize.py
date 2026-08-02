"""QuickResize - lightweight Windows bulk image resizer.

Run with: python quickresize.py
Install dependencies with: pip install -r requirements.txt
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

APP_VERSION = "2026.08.02.6"

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
    import fitz  # PyMuPDF

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


class QuickResizeApp:
    def __init__(self, root: tk.Misc):
        self.root = root
        self.root.title(f"QuickResize v{APP_VERSION}")
        self.root.geometry("820x760")
        self.root.minsize(760, 680)
        self.root.configure(bg="#f5f7fb")

        self.files: list[Path] = []
        self.pdf_pages: dict[Path, list[int]] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.is_processing = False

        self.width_var = tk.StringVar(value="1600")
        self.height_var = tk.StringVar(value="1600")
        self.format_var = tk.StringVar(value="JPG")
        self.destination_var = tk.StringVar(value=str(Path.home() / "Pictures" / "QuickResize"))
        self.status_var = tk.StringVar(value="Ready — drop photos here to begin")
        self.count_var = tk.StringVar(value="0 photos queued")
        self.theme_var = tk.StringVar(value="Dark theme")
        self.dark_mode = False
        self.drop_widgets: list[tk.Widget] = []
        self.field_widgets: list[ttk.Widget] = []
        self.queue_drag_index: int | None = None
        self._build_ui()
        self.apply_theme()
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        style = ttk.Style()
        try:
            # clam respects fieldbackground/foreground styling consistently on Windows.
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#f5f7fb")
        style.configure("Card.TFrame", background="white")
        style.configure("Title.TLabel", background="#f5f7fb", foreground="#162033", font=("Segoe UI", 25, "bold"))
        style.configure("Subtitle.TLabel", background="#f5f7fb", foreground="#647084", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background="white", foreground="#162033", font=("Segoe UI", 11, "bold"))
        style.configure("CardText.TLabel", background="white", foreground="#667085", font=("Segoe UI", 9))
        style.configure("Badge.TLabel", background="#e8f0ff", foreground="#2459c3", font=("Segoe UI", 8, "bold"), padding=(8, 4))
        style.configure("TButton", font=("Segoe UI", 9), padding=(11, 7), relief="flat", borderwidth=0)
        style.configure("Secondary.TButton", font=("Segoe UI", 9), padding=(11, 7), relief="flat", borderwidth=0)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 9), relief="flat", borderwidth=0)

        outer = ttk.Frame(self.root, style="App.TFrame", padding=(28, 22))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="QuickResize", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"v{APP_VERSION}", style="Badge.TLabel").pack(side="left", padx=(12, 0), pady=(8, 0))
        self.theme_button = ttk.Button(header, textvariable=self.theme_var, style="Secondary.TButton", command=self.toggle_theme)
        self.theme_button.pack(side="right", pady=(8, 0))
        ttk.Label(outer, text="Resize a batch of photos in seconds", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 18))

        drop = tk.Frame(outer, highlightthickness=1, cursor="hand2")
        self.drop_widgets.append(drop)
        drop.pack(fill="x", ipady=27)
        drop.bind("<Button-1>", lambda _event: self.choose_files())
        icon = tk.Label(drop, text="+", font=("Segoe UI", 28, "bold"))
        title = tk.Label(drop, text="Drop files to resize", font=("Segoe UI", 15, "bold"))
        note = tk.Label(drop, font=("Segoe UI", 9))
        self.drop_widgets.extend([icon, title, note])
        icon.pack()
        title.pack()
        dnd_note = "or click to choose files" if DND_AVAILABLE else "click to choose files (install dependencies for drag-and-drop)"
        note.configure(text=dnd_note)
        note.pack(pady=(2, 0))
        if DND_AVAILABLE:
            drop.drop_target_register(DND_FILES)
            drop.dnd_bind("<<Drop>>", self._on_drop)
            for child in drop.winfo_children():
                child.drop_target_register(DND_FILES)
                child.dnd_bind("<<Drop>>", self._on_drop)

        card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        card.pack(fill="x", pady=(16, 0))
        ttk.Label(card, text="Resize settings", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=5, sticky="w")
        ttk.Label(card, text="Images fit inside this box; their original aspect ratio is preserved.", style="CardText.TLabel").grid(row=1, column=0, columnspan=5, sticky="w", pady=(3, 14))
        ttk.Label(card, text="Max width", style="CardText.TLabel").grid(row=2, column=0, sticky="w")
        width_entry = ttk.Entry(card, textvariable=self.width_var, width=9, style="Dark.TEntry")
        width_entry.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.field_widgets.append(width_entry)
        ttk.Label(card, text="px", style="CardText.TLabel").grid(row=3, column=1, sticky="w", padx=(5, 20))
        ttk.Label(card, text="Max height", style="CardText.TLabel").grid(row=2, column=2, sticky="w")
        height_entry = ttk.Entry(card, textvariable=self.height_var, width=9, style="Dark.TEntry")
        height_entry.grid(row=3, column=2, sticky="w", pady=(4, 0))
        self.field_widgets.append(height_entry)
        ttk.Label(card, text="px", style="CardText.TLabel").grid(row=3, column=3, sticky="w", padx=(5, 20))
        ttk.Label(card, text="Save as", style="CardText.TLabel").grid(row=2, column=4, sticky="w")
        format_combo = ttk.Combobox(card, textvariable=self.format_var, values=list(FORMAT_INFO), state="readonly", width=9, style="Dark.TCombobox")
        format_combo.grid(row=3, column=4, sticky="w", pady=(4, 0))
        self.field_widgets.append(format_combo)

        dest = ttk.Frame(outer, style="Card.TFrame", padding=18)
        dest.pack(fill="x", pady=(12, 0))
        ttk.Label(dest, text="Destination folder", style="CardTitle.TLabel").pack(anchor="w")
        line = ttk.Frame(dest, style="Card.TFrame")
        line.pack(fill="x", pady=(8, 0))
        destination_entry = ttk.Entry(line, textvariable=self.destination_var, style="Dark.TEntry")
        destination_entry.pack(side="left", fill="x", expand=True)
        self.field_widgets.append(destination_entry)
        ttk.Button(line, text="Browse…", command=self.choose_destination).pack(side="left", padx=(8, 0))

        bottom = ttk.Frame(outer, style="App.TFrame")
        bottom.pack(fill="x", pady=(14, 0))
        ttk.Label(bottom, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left")
        self.resize_button = ttk.Button(bottom, text="Resize photos", style="Accent.TButton", command=self.start_resize)
        self.resize_button.pack(side="right")

        queue_card = ttk.Frame(outer, style="Card.TFrame", padding=18)
        queue_card.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(queue_card, textvariable=self.count_var, style="CardTitle.TLabel").pack(anchor="w")
        queue_actions = ttk.Frame(queue_card, style="Card.TFrame")
        queue_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(queue_actions, text="Clear queue", style="Secondary.TButton", command=self.clear_queue).pack(side="right")
        ttk.Button(queue_actions, text="Remove", style="Secondary.TButton", command=self.remove_selected).pack(side="right", padx=(0, 6))
        ttk.Button(queue_actions, text="Move down", style="Secondary.TButton", command=lambda: self.move_selected(1)).pack(side="left")
        ttk.Button(queue_actions, text="Move up", style="Secondary.TButton", command=lambda: self.move_selected(-1)).pack(side="left", padx=(0, 6))
        self.listbox = tk.Listbox(queue_card, height=5, borderwidth=0, highlightthickness=0, font=("Segoe UI", 9), activestyle="none")
        self.listbox.pack(fill="both", expand=True, pady=(8, 0))
        self.listbox.bind("<ButtonPress-1>", self._queue_press)
        self.listbox.bind("<B1-Motion>", self._queue_drag)
        self.listbox.bind("<ButtonRelease-1>", self._queue_release)

    def _refresh_queue(self, selected: int | None = None):
        self.listbox.delete(0, "end")
        for path in self.files:
            suffix = f" (pages {', '.join(str(page + 1) for page in self.pdf_pages[path])})" if path.suffix.lower() == ".pdf" else ""
            self.listbox.insert("end", f"  {path.name}{suffix}   ·   {path.parent}")
        if selected is not None and self.files:
            selected = max(0, min(selected, len(self.files) - 1))
            self.listbox.selection_set(selected)
            self.listbox.see(selected)
        self.count_var.set(f"{len(self.files)} photo{'s' if len(self.files) != 1 else ''} queued")

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

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.theme_var.set("Light theme" if self.dark_mode else "Dark theme")
        self.apply_theme()

    def apply_theme(self):
        colors = {
            "app": "#141821" if self.dark_mode else "#f5f7fb",
            "card": "#202631" if self.dark_mode else "white",
            "field": "#2b3442" if self.dark_mode else "white",
            "text": "#f1f5f9" if self.dark_mode else "#162033",
            "muted": "#aab5c4" if self.dark_mode else "#647084",
            "drop": "#1c3151" if self.dark_mode else "#eef4ff",
            "drop_border": "#416caa" if self.dark_mode else "#a9c7ff",
            "drop_title": "#8bb8ff" if self.dark_mode else "#1d4ed8",
            "list_text": "#d8e0ea" if self.dark_mode else "#344054",
            "button": "#2a3341" if self.dark_mode else "#ffffff",
            "button_hover": "#354154" if self.dark_mode else "#eef3f9",
            "accent": "#3b82f6" if self.dark_mode else "#2563eb",
            "accent_hover": "#60a5fa" if self.dark_mode else "#1d4ed8",
            "badge": "#263b63" if self.dark_mode else "#e8f0ff",
            "badge_text": "#a9c8ff" if self.dark_mode else "#2459c3",
        }
        self.root.configure(bg=colors["app"])
        style = ttk.Style()
        style.configure("App.TFrame", background=colors["app"])
        style.configure("Card.TFrame", background=colors["card"])
        style.configure("Title.TLabel", background=colors["app"], foreground=colors["text"])
        style.configure("Subtitle.TLabel", background=colors["app"], foreground=colors["muted"])
        style.configure("CardTitle.TLabel", background=colors["card"], foreground=colors["text"])
        style.configure("CardText.TLabel", background=colors["card"], foreground=colors["muted"])
        style.configure("Badge.TLabel", background=colors["badge"], foreground=colors["badge_text"])
        style.configure("TButton", background=colors["button"], foreground=colors["text"])
        style.configure("Secondary.TButton", background=colors["button"], foreground=colors["text"])
        style.configure("Accent.TButton", background=colors["accent"], foreground="white")
        style.map("TButton", background=[("active", colors["button_hover"]), ("pressed", colors["button_hover"])], foreground=[("disabled", colors["muted"])])
        style.map("Secondary.TButton", background=[("active", colors["button_hover"]), ("pressed", colors["button_hover"])], foreground=[("disabled", colors["muted"])])
        style.map("Accent.TButton", background=[("active", colors["accent_hover"]), ("pressed", colors["accent_hover"]), ("disabled", colors["button_hover"])], foreground=[("disabled", colors["muted"])])
        style.configure("Dark.TEntry", fieldbackground=colors["field"], foreground=colors["text"], insertcolor=colors["text"])
        style.configure("Dark.TCombobox", fieldbackground=colors["field"], background=colors["field"], foreground=colors["text"], arrowcolor=colors["text"], selectbackground=colors["drop"], selectforeground=colors["text"])
        style.map("Dark.TEntry", fieldbackground=[("disabled", colors["field"]), ("readonly", colors["field"])])
        style.map("Dark.TCombobox", fieldbackground=[("readonly", colors["field"]), ("disabled", colors["field"])], foreground=[("readonly", colors["text"])])
        for widget in self.drop_widgets:
            widget.configure(bg=colors["drop"], highlightbackground=colors["drop_border"])
        self.drop_widgets[1].configure(fg=colors["drop_title"])
        self.drop_widgets[2].configure(fg=colors["muted"])
        self.listbox.configure(bg=colors["card"], fg=colors["list_text"], selectbackground=colors["drop"], selectforeground=colors["text"])

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
                suffix = f" (pages {', '.join(str(page + 1) for page in self.pdf_pages[path])})" if path.suffix.lower() == ".pdf" else ""
                self.listbox.insert("end", f"  {path.name}{suffix}   ·   {path.parent}")
        self.count_var.set(f"{len(self.files)} photo{'s' if len(self.files) != 1 else ''} queued")
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
        dark = self.dark_mode
        background = "#141821" if dark else "#f5f7fb"
        foreground = "#f1f5f9" if dark else "#162033"
        muted = "#aab5c4" if dark else "#647084"
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
            cell = tk.Frame(thumb_frame, bg=background, highlightthickness=1, highlightbackground="#416caa" if dark else "#cdd7e5", padx=8, pady=8, cursor="hand2")
            cell.grid(row=page_number // 3, column=page_number % 3, sticky="nsew", padx=6, pady=6)
            thumbnail_label = tk.Label(cell, image=photo, bg=background, cursor="hand2")
            thumbnail_label.pack()
            var = tk.BooleanVar(value=False)
            page_vars.append(var)
            check = tk.Checkbutton(cell, text=f"Page {page_number + 1}", variable=var, command=update_selected_text, bg=background, fg=foreground, activebackground=background, activeforeground=foreground, selectcolor="#2b3442" if dark else "white", font=("Segoe UI", 9))
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

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(buttons, text="Cancel", command=cancel).pack(side="right")
        ttk.Button(buttons, text="Use selected pages", command=accept).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self.root.wait_window(dialog)
        return result

    def choose_destination(self):
        selected = filedialog.askdirectory(title="Choose output folder", initialdir=self.destination_var.get())
        if selected:
            self.destination_var.set(selected)

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
        self.is_processing = True
        self.resize_button.configure(state="disabled")
        self.status_var.set("Resizing…")
        threading.Thread(target=self._resize_worker, args=(width, height, self.destination_var.get(), self.format_var.get()), daemon=True).start()

    def _resize_worker(self, width: int, height: int, destination: str, fmt: str):
        output_dir = Path(destination).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
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
    QuickResizeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
