"""Engine tests. Each regression test names the defect it guards against."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageCms, ImageDraw

from qr import APP_VERSION, core
from qr.core import ResizeOptions, fit_size, format_pages, parse_page_range, plan_jobs, run_batch
from qr import settings as settings_module
from qr.settings import Settings, load_settings, save_settings

ROOT = Path(__file__).resolve().parent.parent


def batch(sources, tmp_path, **options):
    options.setdefault("destination", tmp_path / "out")
    opts = ResizeOptions(options.pop("max_width", 100), options.pop("max_height", 100), **options)
    jobs = plan_jobs([(i, Path(s), None) for i, s in enumerate(sources)], opts)
    return jobs, run_batch(jobs, opts, threading.Event())


def test_version_matches_version_file():
    assert (ROOT / "VERSION").read_text().strip() == APP_VERSION


# --- Resizing -----------------------------------------------------------------


@pytest.mark.parametrize("size,box", [((6000, 4000), (1600, 1600)), ((4000, 6000), (1600, 900)), ((3001, 1999), (777, 333)), ((800, 600), (1600, 1600)), ((5000, 10), (100, 100))])
def test_fit_size_predicts_pillow(size, box):
    image = Image.new("L", size)
    image.thumbnail(box)
    assert fit_size(*size, box) == image.size


def test_fits_box_without_stretching_or_enlarging(tmp_path):
    Image.new("RGB", (1000, 500)).save(tmp_path / "wide.jpg")
    Image.new("RGB", (50, 40)).save(tmp_path / "small.jpg")
    _, summary = batch([tmp_path / "wide.jpg", tmp_path / "small.jpg"], tmp_path, max_width=200, max_height=200)
    assert summary.saved == 2 and not summary.errors
    assert Image.open(tmp_path / "out" / "wide.jpg").size == (200, 100)
    assert Image.open(tmp_path / "out" / "small.jpg").size == (50, 40)


@pytest.mark.parametrize("orientation,expected", [(1, (200, 100)), (3, (200, 100)), (6, (50, 100)), (8, (50, 100))])
def test_exif_orientation_applied_against_the_upright_box(tmp_path, orientation, expected):
    # A 400x200 sensor image, shot rotated, should fit a 200x100 box when upright.
    source = tmp_path / "o.jpg"
    exif = Image.Exif()
    exif[core.ORIENTATION_TAG] = orientation
    Image.new("RGB", (400, 200), "red").save(source, exif=exif)
    _, summary = batch([source], tmp_path, max_width=200, max_height=100)
    assert summary.saved == 1
    output = Image.open(tmp_path / "out" / "o.jpg")
    assert output.size == expected
    assert output.getexif().get(core.ORIENTATION_TAG, 1) == 1


def test_orientation_pixels_rotate_correctly(tmp_path):
    source = tmp_path / "o.png"
    image = Image.new("RGB", (40, 20), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 19, 19), fill="red")  # Left half red.
    exif = Image.Exif()
    exif[core.ORIENTATION_TAG] = 6  # Rotate 90 clockwise to display.
    image.save(source, exif=exif)
    _, summary = batch([source], tmp_path, fmt="PNG")
    output = Image.open(tmp_path / "out" / "o.png").convert("RGB")
    assert summary.saved == 1 and output.size == (20, 40)
    assert output.getpixel((10, 5)) == (255, 0, 0)  # The left half ends up on top.
    assert output.getpixel((10, 35)) == (255, 255, 255)


def test_palette_images_are_smoothly_resampled(tmp_path):
    """Pillow silently uses NEAREST for mode P, which gave GIFs and PNG-8 jagged edges."""
    source = tmp_path / "pal.png"
    image = Image.new("P", (800, 800))
    image.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    draw = ImageDraw.Draw(image)
    for x in range(0, 800, 3):
        draw.line((x, 0, 800 - x, 800), fill=1)
    image.save(source)
    _, summary = batch([source], tmp_path, fmt="PNG", max_width=200, max_height=200)
    assert summary.saved == 1
    levels = Image.open(tmp_path / "out" / "pal.png").convert("L").getcolors(256)
    assert levels is not None and len(levels) > 16


@pytest.mark.parametrize("fmt,suffix", [("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("TIFF", "tiff"), ("BMP", "bmp")])
@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "LA", "P", "PA", "1", "CMYK", "I;16", "I", "F", "YCbCr", "HSV"])
def test_every_mode_converts_to_every_format(tmp_path, mode, fmt, suffix):
    """CMYK to PNG used to fail outright. No combination may raise."""
    image = Image.new(mode, (64, 64))
    resized = image.copy()
    resized.thumbnail((32, 32), Image.Resampling.LANCZOS) if mode not in ("P", "PA", "1") else None
    output = tmp_path / f"out.{suffix}"
    assert core.save_image(resized, output, fmt, 90) > 0
    assert Image.open(output).load() is not None
    assert not list(tmp_path.glob("*.tmp"))


def test_cmyk_jpeg_to_png_through_the_pipeline(tmp_path):
    source = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (300, 300), (10, 50, 80, 0)).save(source, quality=90)
    _, summary = batch([source], tmp_path, fmt="PNG")
    assert summary.errors == [] and Image.open(tmp_path / "out" / "cmyk.png").mode == "RGB"


def test_sixteen_bit_gray_scales_rather_than_clips(tmp_path):
    """A mid-gray 16-bit PNG came out pure white as JPG."""
    source = tmp_path / "g.png"
    Image.new("I;16", (200, 200), 12000).save(source)
    _, summary = batch([source], tmp_path, fmt="JPG")
    assert summary.errors == []
    value = Image.open(tmp_path / "out" / "g.jpg").convert("L").getpixel((5, 5))
    assert abs(value - 12000 / 257) < 3


def test_transparency_flattens_onto_white_for_jpg_and_bmp(tmp_path):
    """BMP output used to reveal the color hidden under fully transparent pixels."""
    source = tmp_path / "t.png"
    Image.new("RGBA", (100, 100), (255, 0, 0, 0)).save(source)
    _, summary = batch([source], tmp_path, fmt="BMP", max_width=50, max_height=50)
    assert summary.errors == [] and Image.open(tmp_path / "out" / "t.bmp").convert("RGB").getpixel((5, 5)) == (255, 255, 255)
    _, summary = batch([source], tmp_path, fmt="JPG", max_width=50, max_height=50)
    r, g, b = Image.open(tmp_path / "out" / "t.jpg").convert("RGB").getpixel((5, 5))
    assert min(r, g, b) > 250


def test_png_transparency_survives_webp_and_png(tmp_path):
    source = tmp_path / "t.png"
    Image.new("RGBA", (100, 100), (0, 0, 255, 128)).save(source)
    for fmt, name in (("PNG", "t.png"), ("WEBP", "t.webp")):
        _, summary = batch([source], tmp_path, fmt=fmt, max_width=50, max_height=50)
        assert summary.saved == 1
        assert Image.open(tmp_path / "out" / name).convert("RGBA").getpixel((5, 5))[3] < 200


def test_gif_transparency_is_kept(tmp_path):
    source = tmp_path / "t.gif"
    image = Image.new("P", (100, 100), 0)
    image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
    image.save(source, transparency=0)
    _, summary = batch([source], tmp_path, fmt="PNG", max_width=50, max_height=50)
    assert summary.saved == 1
    assert Image.open(tmp_path / "out" / "t.png").convert("RGBA").getpixel((5, 5))[3] == 0


@pytest.mark.parametrize("fmt,name", [("JPG", "c.jpg"), ("WEBP", "c.webp"), ("PNG", "c.png"), ("TIFF", "c.tiff")])
def test_icc_profile_is_preserved(tmp_path, fmt, name):
    """JPG and WEBP dropped the profile, so wide-gamut photos looked washed out."""
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    source = tmp_path / "c.jpg"
    Image.new("RGB", (300, 300), (200, 20, 20)).save(source, icc_profile=profile)
    _, summary = batch([source], tmp_path, fmt=fmt)
    assert summary.saved == 1
    assert Image.open(tmp_path / "out" / name).info.get("icc_profile") == profile


def test_cmyk_profile_is_not_attached_to_rgb_output(tmp_path):
    image = Image.new("CMYK", (40, 40))
    image.info["icc_profile"] = b"not a real profile"
    prepared, profile = core.prepare_for_format(image, "JPG")
    assert prepared.mode == "RGB" and profile is None


def test_metadata_is_not_carried_over(tmp_path):
    source = tmp_path / "e.jpg"
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    Image.new("RGB", (300, 300)).save(source, exif=exif)
    for fmt, name in (("JPG", "e.jpg"), ("PNG", "e.png"), ("WEBP", "e.webp"), ("TIFF", "e.tiff")):
        _, summary = batch([source], tmp_path, fmt=fmt)
        assert summary.saved == 1
        assert 0x010F not in Image.open(tmp_path / "out" / name).getexif()


# --- PDF -----------------------------------------------------------------------


@pytest.fixture
def pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "doc.pdf"
    document = pymupdf.open()
    for _ in range(5):
        document.new_page(width=612, height=792)
    document.save(path)
    document.close()
    yield path
    core.close_pdf_cache()


def test_pdf_pages_render_exactly_to_the_box(pdf, tmp_path):
    opts = ResizeOptions(1600, 1600, fmt="PNG", destination=tmp_path / "out")
    jobs = plan_jobs([(0, pdf, [0, 2])], opts)
    summary = run_batch(jobs, opts, threading.Event())
    assert summary.saved == 2 and not summary.errors
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["doc_page_001.png", "doc_page_003.png"]
    width, height = Image.open(tmp_path / "out" / "doc_page_001.png").size
    assert height == 1600 and width in (1236, 1237)  # MuPDF rounds its pixmap up.


def test_pdf_render_size_is_bounded_by_the_narrow_side(pdf):
    """A wide, short box used to render the page 8000 x 10353 before shrinking it."""
    image = core._render_pdf_page(pdf, 0, (8000, 200))
    assert image.height <= 201
    huge = core._render_pdf_page(pdf, 0, (65000, 65000))
    assert huge.width * huge.height <= core.PDF_MAX_PIXELS * 1.01


def test_pdf_cache_releases_file_after_batch(pdf, tmp_path):
    opts = ResizeOptions(100, 100, destination=tmp_path / "out")
    run_batch(plan_jobs([(0, pdf, [0])], opts), opts, threading.Event())
    pdf.unlink()  # Windows refuses this while the document is open.
    assert not pdf.exists()


def test_pdf_thumbnail_reports_page_count(pdf):
    thumbnail = core.make_thumbnail(pdf, 1, 120)
    assert thumbnail.page_count == 5 and max(thumbnail.image.size) <= 121


# --- RAW (no sample file is available, so the decision logic uses a stand-in) -------


@pytest.mark.parametrize("box,half", [((1600, 1600), True), ((3200, 3200), False), ((6000, 200), True)])
def test_raw_uses_half_size_when_it_still_reaches_the_target(monkeypatch, box, half):
    import numpy as np

    calls = {}

    class Raw:
        sizes = SimpleNamespace(width=6000, height=4000, flip=0)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def postprocess(self, **kwargs):
            calls.update(kwargs)
            return np.zeros((2000, 3000, 3), dtype="uint8")

    monkeypatch.setitem(core._decoders, "raw", SimpleNamespace(imread=lambda _path: Raw()))
    core._load_raw(Path("x.cr3"), box)
    assert calls["half_size"] is half
    assert calls["use_camera_wb"] is True


# --- Naming and safety ---------------------------------------------------------


def test_replace_mode_keeps_same_named_sources_apart(tmp_path):
    """IMG_0001.jpg in two subfolders used to overwrite each other silently."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    Image.new("RGB", (50, 50), "red").save(tmp_path / "a" / "x.jpg")
    Image.new("RGB", (50, 50), "blue").save(tmp_path / "b" / "x.jpg")
    _, summary = batch([tmp_path / "a" / "x.jpg", tmp_path / "b" / "x.jpg"], tmp_path, replace=True)
    assert summary.saved == 2
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["x.jpg", "x_2.jpg"]


def test_output_never_overwrites_another_source_in_the_batch(tmp_path):
    """x.png to JPG used to destroy x.jpg before x.jpg had been processed."""
    Image.new("RGB", (50, 50), "red").save(tmp_path / "x.png")
    Image.new("RGB", (50, 50), "blue").save(tmp_path / "x.jpg", quality=95)
    before = (tmp_path / "x.jpg").read_bytes()
    _, summary = batch([tmp_path / "x.png", tmp_path / "x.jpg"], tmp_path, destination=tmp_path, replace=True, max_width=40, max_height=40)
    assert summary.saved == 2
    assert (tmp_path / "x.jpg").read_bytes() == before


def test_source_is_never_overwritten_saving_beside(tmp_path):
    source = tmp_path / "x.jpg"
    Image.new("RGB", (500, 500)).save(source)
    before = source.read_bytes()
    jobs, summary = batch([source], tmp_path, destination=None, replace=True)
    assert summary.saved == 1 and jobs[0].output.name == "x_resized.jpg"
    assert source.read_bytes() == before


def test_keep_both_numbers_around_existing_files(tmp_path):
    source = tmp_path / "x.png"
    Image.new("RGB", (50, 50)).save(source)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x.jpg").write_bytes(b"keep me")
    _, summary = batch([source], tmp_path)
    assert summary.saved == 1 and (tmp_path / "out" / "x.jpg").read_bytes() == b"keep me"
    assert (tmp_path / "out" / "x_2.jpg").exists()


def test_replace_mode_replaces_existing(tmp_path):
    source = tmp_path / "x.png"
    Image.new("RGB", (50, 50)).save(source)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "x.jpg").write_bytes(b"old")
    _, summary = batch([source], tmp_path, replace=True)
    assert summary.saved == 1 and (tmp_path / "out" / "x.jpg").read_bytes() != b"old"


def test_failed_save_leaves_the_existing_output_intact(tmp_path, monkeypatch):
    """Writes were not atomic, so a failed replace destroyed the previous file."""
    output = tmp_path / "x.jpg"
    output.write_bytes(b"precious")

    def explode(self, fp, *args, **kwargs):
        Path(fp).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(Image.Image, "save", explode)
    with pytest.raises(OSError):
        core.save_image(Image.new("RGB", (10, 10)), output, "JPG", 90)
    assert output.read_bytes() == b"precious"
    assert [p.name for p in tmp_path.iterdir()] == ["x.jpg"]


def test_names_follow_list_order_despite_parallel_finish(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    sources = [tmp_path / "b" / "x.png", tmp_path / "a" / "x.png"]
    for path in sources:
        Image.new("RGB", (10, 10)).save(path)
    jobs, _ = batch(sources, tmp_path)
    assert jobs[0].source == sources[0] and jobs[0].output.name == "x.jpg" and jobs[1].output.name == "x_2.jpg"


# --- Batch behavior --------------------------------------------------------------


def test_one_bad_file_does_not_stop_the_batch(tmp_path):
    good = tmp_path / "good.png"
    Image.new("RGB", (50, 50)).save(good)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"this is not an image")
    _, summary = batch([bad, good], tmp_path)
    assert summary.saved == 1
    assert len(summary.errors) == 1 and summary.errors[0].startswith("bad.jpg:")


def test_cancel_stops_remaining_jobs(tmp_path):
    sources = []
    for index in range(20):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (20, 20)).save(path)
        sources.append(path)
    opts = ResizeOptions(10, 10, destination=tmp_path / "out")
    jobs = plan_jobs([(i, p, None) for i, p in enumerate(sources)], opts)
    cancel = threading.Event()
    summary = run_batch(jobs, opts, cancel, on_done=lambda _r: cancel.set(), workers=1)
    assert summary.cancelled and summary.saved == 1


def test_bad_destination_is_reported(tmp_path):
    source = tmp_path / "x.png"
    Image.new("RGB", (10, 10)).save(source)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    _, summary = batch([source], tmp_path, destination=blocker / "sub")
    assert summary.saved == 0 and summary.errors[0].startswith("Destination folder:")


def test_results_report_byte_totals(tmp_path):
    source = tmp_path / "x.png"
    Image.effect_noise((400, 400), 50).convert("RGB").save(source)
    _, summary = batch([source], tmp_path)
    assert summary.bytes_in == source.stat().st_size
    assert summary.bytes_out == (tmp_path / "out" / "x.jpg").stat().st_size


# --- Inputs ----------------------------------------------------------------------


def test_collect_recurses_ignores_sidecars_counts_direct_unsupported(tmp_path):
    (tmp_path / "shoot" / "sub").mkdir(parents=True)
    (tmp_path / "shoot" / "a.jpg").write_bytes(b"x")
    (tmp_path / "shoot" / "a.xmp").write_bytes(b"x")
    (tmp_path / "shoot" / "sub" / "b.PNG").write_bytes(b"xx")
    direct = tmp_path / "notes.txt"
    direct.write_text("x")
    result = core.collect_inputs([tmp_path / "shoot", direct, tmp_path / "missing.jpg", tmp_path / "shoot" / "a.jpg"])
    assert [f.path.name for f in result.files] == ["a.jpg", "b.PNG"]
    assert result.files[1].size == 2
    assert result.unsupported == 2


def test_collect_uses_natural_order(tmp_path):
    for name in ("IMG_10.jpg", "IMG_2.jpg", "img_1.jpg"):
        (tmp_path / name).write_bytes(b"x")
    assert [f.path.name for f in core.collect_inputs([tmp_path]).files] == ["img_1.jpg", "IMG_2.jpg", "IMG_10.jpg"]


def test_collect_reports_missing_decoder(tmp_path, monkeypatch):
    monkeypatch.setitem(core._decoders, "raw", None)
    (tmp_path / "a.cr3").write_bytes(b"x")
    result = core.collect_inputs([tmp_path])
    assert result.files == [] and result.decoder_skips == {"RAW needs rawpy": 1}


@pytest.mark.parametrize("text,count,expected", [("1-3, 5", 5, [0, 1, 2, 4]), ("3-1", 5, [2, 1, 0]), ("2,2", 3, [1]), (" 1 ", 1, [0])])
def test_parse_page_range(text, count, expected):
    assert parse_page_range(text, count) == expected


@pytest.mark.parametrize("text", ["", "0", "6", "1-", "-2", "a", "1,,2", "1-2-3", "2-9", "\u00b2"])
def test_parse_page_range_rejects(text):
    with pytest.raises(ValueError):
        parse_page_range(text, 5)


@pytest.mark.parametrize(
    "pages,count,expected",
    [([0], 5, "Page 1"), ([0, 1, 2, 7], 9, "Pages 1\u20133, 8"), ([0, 1], 2, "All 2 pages"), (list(range(0, 20, 2)), 40, "10 of 40 pages")],
)
def test_format_pages(pages, count, expected):
    assert format_pages(pages, count) == expected


# --- Settings ----------------------------------------------------------------------


def test_settings_round_trip_preserving_unknown_keys(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"theme": "dark"}')
    save_settings(Settings(width="800", height="600", fmt="PNG", quality=70, destination="D:/x", save_beside=True, replace=True), path)
    loaded = load_settings(path)
    assert (loaded.width, loaded.height, loaded.fmt, loaded.quality, loaded.destination, loaded.save_beside, loaded.replace) == ("800", "600", "PNG", 70, "D:/x", True, True)
    assert '"theme"' in path.read_text()


@pytest.mark.parametrize("collision,beside,replace", [("beside", True, False), ("overwrite", False, True), ("unique", False, False)])
def test_settings_migrate_old_collision_values(tmp_path, collision, beside, replace):
    path = tmp_path / "s.json"
    path.write_text(f'{{"collision": "{collision}"}}')
    loaded = load_settings(path)
    assert (loaded.save_beside, loaded.replace) == (beside, replace)


@pytest.mark.parametrize("content", ["not json", "[]", '{"width": "\u00b2", "height": true, "quality": "x", "format": 3, "destination": 9}', '{"width": "0", "height": 99999999}'])
def test_settings_tolerate_bad_data(tmp_path, content):
    """A value like a superscript 2 passed str.isdigit() and then crashed int() at launch."""
    path = tmp_path / "s.json"
    path.write_text(content, encoding="utf-8")
    loaded = load_settings(path)
    assert (loaded.width, loaded.height, loaded.fmt, loaded.quality) == ("1600", "1600", "JPG", 92)


def test_saving_incomplete_dimension_keeps_last_good_value(tmp_path):
    path = tmp_path / "s.json"
    save_settings(Settings(width="800", height="800", destination="x"), path)
    save_settings(Settings(width="", height="abc", destination="x"), path)
    assert load_settings(path).width == "800"


# --- Portable package --------------------------------------------------------------


@pytest.fixture
def portable(tmp_path, monkeypatch):
    """Pretend to be the packaged app, installed at <drive>/App, on an empty profile."""
    folder = tmp_path / "App"
    folder.mkdir()
    monkeypatch.setattr(settings_module, "portable_folder", lambda: folder)
    monkeypatch.setattr(settings_module, "default_destination", lambda: str(tmp_path / "home" / "Pictures" / "QuickResize"))
    return folder


def test_portable_settings_sit_beside_the_exe(monkeypatch, tmp_path):
    exe = tmp_path / "App" / "QuickResize.exe"
    monkeypatch.setattr(settings_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(settings_module.sys, "executable", str(exe))
    assert settings_module.settings_path() == tmp_path.resolve() / "App" / "settings.json"


def test_source_runs_keep_using_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert settings_module.settings_path() == tmp_path / "QuickResize" / "settings.json"


def test_default_folder_is_not_saved_so_it_follows_the_user(portable):
    path = portable / "settings.json"
    save_settings(Settings(destination=settings_module.default_destination()), path)
    assert "destination" not in path.read_text()
    assert load_settings(path).destination == settings_module.default_destination()


def test_folder_on_the_apps_drive_survives_a_new_drive_letter(portable, monkeypatch):
    path = portable / "settings.json"
    target = portable.parent / "Output"
    target.mkdir()
    save_settings(Settings(destination=str(target)), path)
    stored = settings_module._read_raw(path)["destination"]
    assert not os.path.splitdrive(stored)[0] and stored.endswith("Output")
    assert os.path.normcase(load_settings(path).destination) == os.path.normcase(str(target))


def test_new_folder_one_level_down_is_kept(portable):
    path = portable / "settings.json"
    target = portable.parent / "NotYetCreated"
    save_settings(Settings(destination=str(target)), path)
    assert os.path.normcase(load_settings(path).destination) == os.path.normcase(str(target))


def test_folder_missing_on_this_pc_falls_back_to_default(portable):
    path = portable / "settings.json"
    path.write_text(json.dumps({"destination": "Q:\\Users\\someone\\Desktop\\Out"}))
    assert load_settings(path).destination == settings_module.default_destination()


@pytest.mark.skipif(sys.platform != "win32", reason="Uses Windows folder permissions")
def test_read_only_folder_loses_settings_without_hanging(portable):
    """tempfile.mkstemp retried a denied folder almost endlessly, freezing the app on close."""
    user = os.environ["USERNAME"]
    subprocess.run(["icacls", str(portable), "/deny", f"{user}:(WD,AD)"], capture_output=True, check=True)
    try:
        save_settings(Settings(destination="x"), portable / "settings.json")
        assert not (portable / "settings.json").exists()
    finally:
        subprocess.run(["icacls", str(portable), "/remove:d", user], capture_output=True, check=True)
