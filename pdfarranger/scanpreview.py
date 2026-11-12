# Copyright (C) 2026 pdfarranger contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview-only fast path for a single opaque, full-page JPEG scan.

Anything outside this deliberately small PDF subset is rendered by Poppler.
The original PDF and the export code are never modified by this module.
"""
from collections import OrderedDict
import io
import logging
import math
import os
import sys
import threading
import time

import cairo
import pikepdf
try:
    from PIL import Image
except ImportError:
    Image = None
try:
    from PIL import ImageCms
except ImportError:
    ImageCms = None


_CACHE = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LIMIT = 64 * 1024 * 1024
_CACHE_LOCK = threading.Lock()
_TRANSFORMS = OrderedDict()
_TRANSFORM_LOCK = threading.Lock()
_LOG = logging.getLogger(__name__)


def log_render(page, backend, started, **details):
    _LOG.debug("page=%d backend=%s ms=%.2f %s", page + 1, backend,
              (time.perf_counter() - started) * 1000,
              " ".join(f"{k}={v}" for k, v in details.items()))


def _inherited(obj, key, default=None):
    for _ in range(100):
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        if obj is None:
            return default
    return default


def _same(a, b):
    return len(a) == len(b) and all(math.isclose(float(x), float(y), abs_tol=1e-5, rel_tol=1e-8)
                                    for x, y in zip(a, b))


def _color_transform(profile_data):
    with _TRANSFORM_LOCK:
        transform = _TRANSFORMS.get(profile_data)
        if transform is not None:
            _TRANSFORMS.move_to_end(profile_data)
            return transform
        profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_data))
        transform = ImageCms.buildTransformFromOpenProfiles(
            profile, ImageCms.createProfile("sRGB"), "RGB", "RGB",
            renderingIntent=1, flags=0x2000)  # Relative colorimetric + black point compensation.
        _TRANSFORMS[profile_data] = transform
        while len(_TRANSFORMS) > 8:
            _TRANSFORMS.popitem(last=False)
        return transform


class ScanPreview:
    def __init__(self, filename, password=""):
        self.filename = filename
        self.password = password
        self.pdf = None
        self.checked = {}
        self.token = object()
        self.disabled = Image is None or os.environ.get("PDFARRANGER_SCAN_PREVIEW", "1") == "0"

    def __del__(self):
        # Do not keep a temporary PDF file locked after the document is removed.
        global _CACHE_BYTES
        try:
            if self.pdf is not None:
                self.pdf.close()
            with _CACHE_LOCK:
                for key in [k for k in _CACHE if k[0] is self.token]:
                    old = _CACHE.pop(key)
                    _CACHE_BYTES -= old.get_stride() * old.get_height()
        except Exception:
            pass  # The interpreter may already have released module globals.

    def _scan(self, number):
        if self.pdf is None:
            self.pdf = pikepdf.open(self.filename, password=self.password)
        page = self.pdf.pages[number]
        if self.pdf.Root.get("/OutputIntents") or self.pdf.Root.get("/OCProperties"):
            return None
        obj = page.obj
        if obj.get("/Annots") or obj.get("/Group") or obj.get("/AA"):
            return None
        angle = float(_inherited(obj, "/Rotate", 0)) % 360
        if angle not in (0, 90, 180, 270) or float(obj.get("/UserUnit", 1)) != 1:
            return None
        box = _inherited(obj, "/MediaBox")
        crop = _inherited(obj, "/CropBox", box)
        if box is None or not _same(box, crop) or not _same(list(box)[:2], [0, 0]):
            return None
        width, height = float(box[2]), float(box[3])
        if width <= 0 or height <= 0:
            return None
        # No text, clipping, graphics state, optional content, or extra drawing.
        ops = list(pikepdf.parse_content_stream(page))
        if len(ops) != 4 or [str(op.operator) for op in ops] != ["q", "cm", "Do", "Q"]:
            return None
        if ops[0].operands or ops[3].operands or len(ops[2].operands) != 1:
            return None
        if not _same(ops[1].operands, [width, 0, 0, height, 0, 0]):
            return None
        resources = _inherited(obj, "/Resources")
        if resources is None or resources.get("/ColorSpace") or resources.get("/DefaultRGB"):
            return None
        image = resources.XObject[ops[2].operands[0]]
        if str(image.get("/Subtype")) != "/Image" or str(image.get("/Filter")) != "/DCTDecode":
            return None
        for key in ("/SMask", "/Mask", "/Decode", "/DecodeParms", "/OC", "/Alternates"):
            if key in image:
                return None
        if image.get("/ImageMask", False) or int(image.get("/BitsPerComponent", 0)) != 8:
            return None
        if str(image.get("/Intent", "/RelativeColorimetric")) != "/RelativeColorimetric":
            return None
        iw, ih = int(image.Width), int(image.Height)
        # Keep a corrupt or enormous image out of the eager decoder.
        if iw <= 0 or ih <= 0 or iw * ih > 24_000_000:
            return None
        colorspace = image.get("/ColorSpace")
        profile = None
        if str(colorspace) == "/DeviceRGB":
            pass
        elif isinstance(colorspace, pikepdf.Array) and len(colorspace) == 2 and str(colorspace[0]) == "/ICCBased":
            if ImageCms is None:
                return None
            icc = colorspace[1]
            if int(icc.get("/N", 0)) != 3 or "/Range" in icc:
                return None
            if len(icc.read_bytes()) > 4 * 1024 * 1024:
                return None
            profile = icc
        else:
            return None
        return image, width, height, iw, ih, profile, angle

    def paint(self, cr, number):
        global _CACHE_BYTES
        if self.disabled:
            return False
        started = time.perf_counter()
        try:
            if number not in self.checked:
                self.checked[number] = self._scan(number)
            descriptor = self.checked[number]
            if descriptor is None:
                return False
            image, width, height, iw, ih, profile, angle = descriptor
            key = (self.token, number)
            with _CACHE_LOCK:
                surface = _CACHE.get(key)
                if surface is not None:
                    _CACHE.move_to_end(key)
            cache_hit = surface is not None
            if surface is None:
                with Image.open(io.BytesIO(image.read_raw_bytes())) as decoded:
                    if decoded.mode != "RGB" or decoded.size != (iw, ih):
                        self.checked[number] = None
                        return False
                    pixels = decoded.copy()
                if profile is not None:
                    pixels = ImageCms.applyTransform(pixels, _color_transform(profile.read_bytes()))
                data = bytearray(pixels.tobytes("raw", "BGRX" if sys.byteorder == "little" else "XRGB"))
                surface = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, iw, ih, iw * 4)
                cost = len(data)
                if cost <= _CACHE_LIMIT:
                    with _CACHE_LOCK:
                        while _CACHE and _CACHE_BYTES + cost > _CACHE_LIMIT:
                            _, old = _CACHE.popitem(last=False)
                            _CACHE_BYTES -= old.get_stride() * old.get_height()
                        _CACHE[key] = surface
                        _CACHE_BYTES += cost
            original_path = cr.copy_path()
            cr.save()
            try:
                if angle == 90:
                    cr.translate(height, 0)
                    cr.rotate(math.pi / 2)
                elif angle == 180:
                    cr.translate(width, height)
                    cr.rotate(math.pi)
                elif angle == 270:
                    cr.translate(0, width)
                    cr.rotate(-math.pi / 2)
                cr.scale(width / iw, height / ih)
                cr.set_source_surface(surface, 0, 0)
                cr.get_source().set_filter(cairo.FILTER_GOOD)
                cr.get_source().set_extend(cairo.EXTEND_PAD)
                # Keep the fast path within the page when used as an overlay.
                cr.new_path()
                cr.rectangle(0, 0, iw, ih)
                cr.clip()
                cr.paint()
            finally:
                cr.restore()
                cr.new_path()
                cr.append_path(original_path)
            log_render(number, "jpeg", started, cache=int(cache_hit), pixels=f"{iw}x{ih}")
            return True
        except Exception as error:
            # Unsupported or malformed content always uses the original renderer.
            self.checked[number] = None
            _LOG.debug("page=%d backend=fallback reason=%s", number + 1, type(error).__name__)
            return False
