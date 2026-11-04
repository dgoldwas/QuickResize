"""Image pipeline: finding inputs, naming outputs, decoding, resizing, and saving.

This module has no UI dependency so every rule in it can be tested directly.
Optional decoders (HEIC, RAW, PDF) are imported on first use because they cost
more startup time than the rest of the application combined.
"""

from __future__ import annotations

import io
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from PIL import Image, ImageCms, UnidentifiedImageError

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    ".heic", ".heif", ".crw", ".cr3", ".pdf", ".psd", ".psb",
}
RAW_EXTENSIONS = {".crw", ".cr3"}
HEIF_EXTENSIONS = {".heic", ".heif"}
FORMAT_INFO = {
    "JPG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "WEBP": ("WEBP", ".webp"),
    "TIFF": ("TIFF", ".tiff"),
    "BMP": ("BMP", ".bmp"),
}
TYPE_LABELS = {
    ".jpg": "JPG", ".jpeg": "JPG", ".png": "PNG", ".webp": "WEBP", ".tif": "TIFF",
    ".tiff": "TIFF", ".bmp": "BMP", ".gif": "GIF", ".heic": "HEIC", ".heif": "HEIF",
    ".crw": "CRW", ".cr3": "CR3", ".pdf": "PDF", ".psd": "PSD", ".psb": "PSB",
}
MAX_DIMENSION = 65500  # The largest side JPEG and WEBP encoders can write in practice.
PDF_MAX_PIXELS = 100_000_000  # Keeps an oversized target from exhausting memory.

ORIENTATION_TAG = 0x0112
_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_SIXTEEN_BIT_MODES = {"I;16", "I;16L", "I;16B", "I;16N"}
_DEEP_MODES = _SIXTEEN_BIT_MODES | {"I", "F"}
_BASIC_MODES = {"RGB", "RGBA", "L", "LA"}

_decoder_lock = threading.Lock()
_decoders: dict[str, Any] = {}
_pdf_lock = threading.RLock()  # PyMuPDF is not thread-safe, so all calls share this lock.
_pdf_path: str | None = None
_pdf_document: Any = None


def _decoder(name: str) -> Any:
    """Return an optional decoder module, or None when it is not installed."""
    with _decoder_lock:
        if name not in _decoders:
            try:
                if name == "heif":
                    from pillow_heif import register_heif_opener

                    register_heif_opener()
                    _decoders[name] = True
                elif name == "raw":
                    import rawpy

                    _decoders[name] = rawpy
                else:
                    import pymupdf

                    _decoders[name] = pymupdf
            except (ImportError, OSError):
                _decoders[name] = None
        return _decoders[name]


def decoder_issue(path: Path) -> str | None:
    """Describe the missing package needed to read a file, if any."""
    suffix = path.suffix.lower()
    if suffix in HEIF_EXTENSIONS and not _decoder("heif"):
        return "HEIC needs pillow-heif"
    if suffix in RAW_EXTENSIONS and not _decoder("raw"):
        return "RAW needs rawpy"
    if suffix == ".pdf" and not _decoder("pdf"):
        return "PDF needs pymupdf"
    return None


def path_key(path: Path | str) -> str:
    """Return a case-normalized key without the disk access of Path.resolve()."""
    return os.path.normcase(os.path.abspath(str(path)))


def type_label(path: Path) -> str:
    suffix = path.suffix.lower()
    return TYPE_LABELS.get(suffix, suffix[1:].upper() or "?")


def natural_key(text: str) -> list[object]:
    """Sort key that places IMG_2 before IMG_10."""
    return [int(part) if part.isdecimal() else part.casefold() for part in re.split(r"(\d+)", text)]


def format_bytes(size: float) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_pages(pages: list[int], page_count: int | None = None) -> str:
    """Describe 0-based page indexes as 'Pages 1-5, 8'."""
    if not pages:
        return "No pages"
    if page_count and len(pages) == page_count and page_count > 1:
        return f"All {page_count} pages"
    numbers = sorted(page + 1 for page in pages)
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    if len(runs) > 4:
        total = f" of {page_count}" if page_count else ""
        return f"{len(numbers)}{total} pages"
    text = ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in runs)
    return f"Page {text}" if len(numbers) == 1 else f"Pages {text}"


def fit_size(width: int, height: int, box: tuple[int, int]) -> tuple[int, int]:
    """Return the size Image.thumbnail() will produce, without loading the image."""
    box_w, box_h = box
    if width <= box_w and height <= box_h:
        return width, height
    x, y = min(width, box_w), min(height, box_h)
    aspect = width / height

    def closest(number: float, key: Callable[[int], float]) -> int:
        return max(min(math.floor(number), math.ceil(number), key=key), 1)

    if x / y >= aspect:
        x = closest(y * aspect, lambda n: abs(aspect - n / y))
    else:
        y = closest(x / aspect, lambda n: 0 if n == 0 else abs(aspect - x / n))
    return x, y


class ScannedFile(NamedTuple):
    path: Path
    size: int


@dataclass
class ScanResult:
    files: list[ScannedFile] = field(default_factory=list)
    unsupported: int = 0
    decoder_skips: dict[str, int] = field(default_factory=dict)


def collect_inputs(paths: Iterable[Path]) -> ScanResult:
    """Expand dropped paths into supported files.

    Folders are walked recursively in natural order. Unsupported files inside a
    folder are ignored so sidecars do not flood the summary, while a file the user
    chose directly still counts as unsupported.
    """
    result = ScanResult()
    seen: set[str] = set()

    def add(path: str) -> None:
        key = path_key(path)
        if key in seen:
            return
        seen.add(key)
        candidate = Path(os.path.abspath(path))
        issue = decoder_issue(candidate)
        if issue:
            result.decoder_skips[issue] = result.decoder_skips.get(issue, 0) + 1
            return
        try:
            result.files.append(ScannedFile(candidate, os.stat(path).st_size))
        except OSError:
            result.unsupported += 1

    for path in paths:
        text = str(path)
        if os.path.isdir(text):
            for folder, subfolders, names in os.walk(text):
                subfolders.sort(key=natural_key)
                for name in sorted(names, key=natural_key):
                    if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                        add(os.path.join(folder, name))
        elif os.path.isfile(text) and os.path.splitext(text)[1].lower() in IMAGE_EXTENSIONS:
            add(text)
        else:
            result.unsupported += 1
    return result


def summarize_add(added: int, updated: int, duplicates: int, unsupported: int, decoder_skips: dict[str, int], cancelled: int) -> str:
    parts: list[str] = []
    if added:
        parts.append(f"Added {added} file{'s' if added != 1 else ''}")
    if updated:
        parts.append(f"Updated {updated} PDF selection{'s' if updated != 1 else ''}")
    if duplicates:
        parts.append(f"{duplicates} already in the list")
    if unsupported:
        parts.append(f"Skipped {unsupported} unsupported file{'s' if unsupported != 1 else ''}")
    for reason, count in decoder_skips.items():
        parts.append(f"Skipped {count} — {reason}")
    if cancelled:
        parts.append(f"Skipped {cancelled} PDF{'s' if cancelled != 1 else ''} with no pages selected")
    return " · ".join(parts) if parts else "No files added"


def parse_page_range(text: str, page_count: int) -> list[int]:
    """Parse a 1-based range such as '1-5, 8' into 0-based page indexes."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty")
    if page_count < 1:
        raise ValueError("empty document")
    chosen: dict[int, None] = {}
    for raw_part in stripped.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("empty part")
        left, separator, right = part.partition("-")
        if separator and (not left.strip() or not right.strip() or "-" in right):
            raise ValueError("bad range")
        start = int(left.strip())
        end = int(right.strip()) if separator else start
        if not (1 <= start <= page_count and 1 <= end <= page_count):
            raise ValueError("out of range")
        step = 1 if start <= end else -1
        chosen.update(dict.fromkeys(number - 1 for number in range(start, end + step, step)))
    return list(chosen)


def plan_output_path(folder: Path, source: Path, page: int | None, extension: str, replace: bool, used: set[str], protected: set[str]) -> Path:
    """Choose an output path, reserving it in `used`.

    `protected` holds the key of every source in the batch, so an output can never
    overwrite a file that is itself an input. Two outputs of one batch also never
    share a name, even when replacing existing files is allowed.
    """
    stem = f"{source.stem}_page_{page + 1:03d}" if page is not None else source.stem
    if path_key(folder / f"{stem}{extension}") == path_key(source):
        stem = f"{stem}_resized"
    candidate = folder / f"{stem}{extension}"
    number = 2
    while True:
        key = path_key(candidate)
        if key not in used and key not in protected and (replace or not candidate.exists()):
            used.add(key)
            return candidate
        candidate = folder / f"{stem}_{number}{extension}"
        number += 1
        if number > 100000:
            raise RuntimeError(f"Could not find a free name for {source.name}")


@dataclass(frozen=True)
class ResizeOptions:
    max_width: int
    max_height: int
    fmt: str = "JPG"
    quality: int = 92
    destination: Path | None = None  # None saves next to each source.
    replace: bool = False

    @property
    def box(self) -> tuple[int, int]:
        return self.max_width, self.max_height


@dataclass(frozen=True)
class Job:
    tag: object
    source: Path
    page: int | None
    output: Path

    @property
    def label(self) -> str:
        return self.source.name if self.page is None else f"{self.source.name} page {self.page + 1}"


@dataclass(frozen=True)
class JobResult:
    job: Job
    ok: bool
    error: str = ""
    bytes_in: int = 0
    bytes_out: int = 0


@dataclass
class BatchSummary:
    saved: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    folder: Path | None = None
    bytes_in: int = 0
    bytes_out: int = 0
    elapsed: float = 0.0


def plan_jobs(items: Iterable[tuple[object, Path, list[int] | None]], options: ResizeOptions) -> list[Job]:
    """Assign output names in list order, before any decoding starts.

    Naming up front keeps results deterministic while files finish out of order.
    Each item is (tag, source, pages), where pages is None for a single image.
    """
    listed = list(items)
    protected = {path_key(source) for _tag, source, _pages in listed}
    extension = FORMAT_INFO[options.fmt][1]
    used: set[str] = set()
    jobs: list[Job] = []
    for tag, source, pages in listed:
        folder = options.destination if options.destination is not None else source.parent
        for page in pages if pages is not None else [None]:
            output = plan_output_path(folder, source, page, extension, options.replace, used, protected)
            jobs.append(Job(tag, source, page, output))
    return jobs


def _open_pdf(source: Path) -> Any:
    """Open a PDF, reusing the last one. The caller must hold _pdf_lock."""
    global _pdf_path, _pdf_document
    key = path_key(source)
    if _pdf_document is None or _pdf_path != key:
        close_pdf_cache()
        fitz = _decoder("pdf")
        if fitz is None:
            raise RuntimeError("PDF support requires the pymupdf package")
        _pdf_document = fitz.open(str(source))
        _pdf_path = key
    return _pdf_document


def close_pdf_cache() -> None:
    """Release the cached PDF so Windows no longer holds the file open."""
    global _pdf_path, _pdf_document
    with _pdf_lock:
        if _pdf_document is not None:
            try:
                _pdf_document.close()
            finally:
                _pdf_document = None
                _pdf_path = None


def pdf_page_count(source: Path) -> int:
    with _pdf_lock:
        document = _open_pdf(source)
        if document.needs_pass:
            raise ValueError("This PDF is password protected")
        return int(document.page_count)


def _render_pdf_page(source: Path, page: int | None, box: tuple[int, int]) -> Image.Image:
    fitz = _decoder("pdf")
    with _pdf_lock:
        pdf_page = _open_pdf(source).load_page(page or 0)
        width, height = pdf_page.rect.width, pdf_page.rect.height
        if width <= 0 or height <= 0:
            raise ValueError("The page has no size")
        # PDF pages are vector art at 72 DPI, so render directly at the target size.
        scale = min(box[0] / width, box[1] / height, math.sqrt(PDF_MAX_PIXELS / (width * height)))
        pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _load_raw(source: Path, box: tuple[int, int]) -> Image.Image:
    rawpy = _decoder("raw")
    if rawpy is None:
        raise RuntimeError("CRW/CR3 support requires the rawpy package")
    with rawpy.imread(str(source)) as raw:
        width, height = raw.sizes.width, raw.sizes.height
        # The camera may be rotated, so test the box against both orientations.
        scale = max(min(box[0] / width, box[1] / height), min(box[0] / height, box[1] / width))
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=True, output_bps=8, half_size=scale <= 0.5)
    return Image.fromarray(rgb)


def _load_raster(source: Path, box: tuple[int, int], resample: Image.Resampling) -> tuple[Image.Image, tuple[int, int]]:
    """Decode and shrink an image, returning it with its full upright size."""
    with Image.open(source) as image:
        orientation = image.getexif().get(ORIENTATION_TAG, 1)
        sideways = orientation in (5, 6, 7, 8)
        full_size = (image.height, image.width) if sideways else image.size
        bounds = (box[1], box[0]) if sideways else box
        # Thumbnailing before the file is loaded lets JPEG decode at reduced scale.
        working = _to_continuous_tone(image)
        working.thumbnail(bounds, resample)
        # A copy detaches format-specific state such as TIFF tags from the save step.
        result = working.copy()
    transpose = _TRANSPOSE.get(orientation)
    if transpose is not None:
        info = result.info
        result = result.transpose(transpose)
        result.info = info
    return result, full_size


def _to_continuous_tone(image: Image.Image) -> Image.Image:
    """Convert palette and 1-bit images, which Pillow can only resize with NEAREST."""
    transparent = "transparency" in image.info and image.mode in ("P", "L", "RGB", "1")
    if transparent or image.mode == "PA":
        return image.convert("RGBA")
    if image.mode == "P":
        return image.convert("RGB")
    if image.mode == "1":
        return image.convert("L")
    return image


def load_resized(source: Path, page: int | None, box: tuple[int, int], resample: Image.Resampling = Image.Resampling.LANCZOS) -> Image.Image:
    """Return an upright image that fits inside box, never enlarged."""
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        image = _render_pdf_page(source, page, box)
    elif suffix in RAW_EXTENSIONS:
        image = _load_raw(source, box)
    else:
        if suffix in HEIF_EXTENSIONS and not _decoder("heif"):
            raise RuntimeError("HEIC support requires the pillow-heif package")
        return _load_raster(source, box, resample)[0]
    image.thumbnail(box, resample)
    return image


def _to_eight_bit(image: Image.Image) -> Image.Image:
    """Scale a high-bit-depth grayscale image down to 8 bits instead of clipping it."""
    if image.mode in _SIXTEEN_BIT_MODES:
        peak = 65535.0
    else:
        peak = max(float(image.getextrema()[1]), 255.0)
    scaled = image.convert("F") if image.mode != "F" else image
    return scaled.point(lambda value: value * (255.0 / peak)).convert("L")


def _cmyk_to_rgb(image: Image.Image, profile: bytes | None) -> Image.Image:
    if profile:
        try:
            return ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass
    return image.convert("RGB")


def _flatten(image: Image.Image) -> Image.Image:
    """Composite alpha over white, keeping grayscale images grayscale."""
    gray = image.mode == "LA"
    background = Image.new("L" if gray else "RGB", image.size, 255 if gray else (255, 255, 255))
    background.paste(image.getchannel(0) if gray else image.convert("RGB"), mask=image.getchannel("A"))
    return background


def prepare_for_format(image: Image.Image, fmt: str) -> tuple[Image.Image, bytes | None]:
    """Convert an image to a mode the format can store, with its matching ICC profile."""
    profile = image.info.get("icc_profile") or None
    if image.mode in _DEEP_MODES and not (fmt == "TIFF" or (fmt == "PNG" and image.mode in _SIXTEEN_BIT_MODES)):
        image, profile = _to_eight_bit(image), None
    elif image.mode == "CMYK" and fmt != "TIFF":
        image, profile = _cmyk_to_rgb(image, profile), None
    elif image.mode not in _BASIC_MODES and image.mode not in _DEEP_MODES and image.mode != "CMYK":
        image, profile = image.convert("RGBA" if "A" in image.getbands() else "RGB"), None

    if fmt in ("JPG", "BMP") and image.mode in ("RGBA", "LA"):
        image = _flatten(image)
    elif fmt == "WEBP" and image.mode in ("L", "LA"):
        # WEBP has no grayscale mode, and a gray profile would not describe RGB data.
        image, profile = image.convert("RGBA" if image.mode == "LA" else "RGB"), None
    return image, profile


def save_image(image: Image.Image, output: Path, fmt: str, quality: int) -> int:
    """Encode to a temporary file and move it into place, so a failed or interrupted
    write can never damage a file that is being replaced. Returns the output size."""
    prepared, profile = prepare_for_format(image, fmt)
    prepared.info = {}  # Nothing from the source's metadata is carried into the output.
    options: dict[str, object] = {}
    if fmt == "JPG":
        options = {"quality": quality, "optimize": True}
    elif fmt == "WEBP":
        options = {"quality": quality}
    elif fmt == "TIFF":
        options = {"compression": "tiff_lzw"}
    if profile and fmt != "BMP":
        options["icc_profile"] = profile
    temporary = output.with_name(f".{output.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        prepared.save(temporary, format=FORMAT_INFO[fmt][0], **options)
        size = temporary.stat().st_size
        os.replace(temporary, output)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return size


def describe_error(exc: Exception) -> str:
    """Turn an exception into a sentence, without the path the row already shows."""
    if isinstance(exc, UnidentifiedImageError):
        return "Not a readable image. The file may be damaged."
    if isinstance(exc, FileNotFoundError):
        return "The file no longer exists."
    if isinstance(exc, OSError) and exc.strerror:
        return f"{exc.strerror}."
    return str(exc) or exc.__class__.__name__


def process_job(job: Job, options: ResizeOptions) -> JobResult:
    try:
        image = load_resized(job.source, job.page, options.box)
        bytes_out = save_image(image, job.output, options.fmt, options.quality)
    except Exception as exc:  # One bad file must never stop the batch.
        return JobResult(job, False, describe_error(exc))
    try:
        bytes_in = job.source.stat().st_size if job.page is None else 0
    except OSError:
        bytes_in = 0
    return JobResult(job, True, bytes_in=bytes_in, bytes_out=bytes_out)


def default_workers() -> int:
    """Leave one core for the UI. The cap bounds memory on batches of large files."""
    return max(1, min(6, (os.cpu_count() or 2) - 1))


def run_batch(
    jobs: list[Job],
    options: ResizeOptions,
    cancel: threading.Event,
    on_start: Callable[[Job], None] = lambda _job: None,
    on_done: Callable[[JobResult], None] = lambda _result: None,
    workers: int | None = None,
) -> BatchSummary:
    """Process jobs in parallel. Pillow releases the GIL while it decodes, resizes,
    and encodes, so threads scale without the packaging cost of processes."""
    started = time.perf_counter()
    summary = BatchSummary(folder=options.destination)
    if options.destination is not None:
        try:
            options.destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            summary.errors.append(f"Destination folder: {exc}")
            return summary
    Image.init()  # Load format plugins once, before threads race to do it.
    lock = threading.Lock()

    def work(job: Job) -> None:
        if cancel.is_set():
            with lock:
                summary.cancelled = True
            return
        on_start(job)
        result = process_job(job, options)
        with lock:
            if result.ok:
                summary.saved += 1
                summary.bytes_in += result.bytes_in
                summary.bytes_out += result.bytes_out
                if summary.folder is None:
                    summary.folder = job.source.parent
            else:
                summary.errors.append(f"{job.label}: {result.error}")
        on_done(result)

    try:
        with ThreadPoolExecutor(max_workers=workers or default_workers(), thread_name_prefix="resize") as pool:
            # Consuming the iterator surfaces any unexpected exception from a worker.
            for _ in pool.map(work, jobs):
                pass
    finally:
        close_pdf_cache()
    summary.elapsed = time.perf_counter() - started
    return summary


@dataclass(frozen=True)
class Thumbnail:
    image: Image.Image | None
    size: tuple[int, int] | None = None
    page_count: int | None = None


def make_thumbnail(source: Path, page: int | None, side: int) -> Thumbnail:
    """Build a fast preview, along with whatever size facts were cheap to learn."""
    suffix = source.suffix.lower()
    box = (side, side)
    fast = Image.Resampling.BILINEAR
    if suffix == ".pdf":
        with _pdf_lock:
            count = pdf_page_count(source)
            image = _render_pdf_page(source, page, box)
        return Thumbnail(image, None, count)
    if suffix in RAW_EXTENSIONS:
        return _raw_thumbnail(source, box)
    if suffix in HEIF_EXTENSIONS and not _decoder("heif"):
        return Thumbnail(None)
    image, size = _load_raster(source, box, fast)
    return Thumbnail(_displayable(image), size)


def _displayable(image: Image.Image) -> Image.Image:
    if image.mode in _DEEP_MODES:
        return _to_eight_bit(image)
    return image.convert("RGBA")


def _raw_thumbnail(source: Path, box: tuple[int, int]) -> Thumbnail:
    """Use the JPEG a camera embeds in its RAW files, avoiding a full demosaic."""
    rawpy = _decoder("raw")
    if rawpy is None:
        return Thumbnail(None)
    with rawpy.imread(str(source)) as raw:
        width, height = raw.sizes.width, raw.sizes.height
        # LibRaw flips: 3 is 180 degrees, 5 is 90 counterclockwise, 6 is 90 clockwise.
        flip = raw.sizes.flip
        size = (height, width) if flip in (5, 6) else (width, height)
        try:
            embedded = raw.extract_thumb()
        except rawpy.LibRawError:
            return Thumbnail(None, size)
    if embedded.format == rawpy.ThumbFormat.JPEG:
        with Image.open(io.BytesIO(embedded.data)) as stream:
            stream.thumbnail(box, Image.Resampling.BILINEAR)
            image = stream.convert("RGBA")
    else:
        image = Image.fromarray(embedded.data).convert("RGBA")
        image.thumbnail(box, Image.Resampling.BILINEAR)
    turn = {3: Image.Transpose.ROTATE_180, 5: Image.Transpose.ROTATE_90, 6: Image.Transpose.ROTATE_270}.get(flip)
    return Thumbnail(image.transpose(turn) if turn else image, size)
