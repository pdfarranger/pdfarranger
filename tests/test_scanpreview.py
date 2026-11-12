# SPDX-License-Identifier: GPL-3.0-or-later
"""Correctness and resource checks for the restricted JPEG preview path."""
import gc
import hashlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cairo
import pikepdf
from PIL import Image, ImageChops, ImageStat
import gi
gi.require_version("Poppler", "0.18")
from gi.repository import Poppler
from pdfarranger import scanpreview as module
from pdfarranger.core import PDFDoc, PDFRenderer

# scanpreview-p3.icc is an original generated CC0 fixture: Display P3 primaries,
# D65 white and the sRGB transfer curve; no profile from a user's PDF is included.


class ScanPreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.previews = []
        self.counter = 0

    def tearDown(self):
        for preview in self.previews:
            if preview.pdf is not None:
                preview.pdf.close()
                preview.pdf = None
        self.previews.clear()
        gc.collect()
        self.tmp.cleanup()

    def document(self, modify=None, icc=False, angle=0, pages=1, encrypted=False):
        pixels = Image.new("RGB", (32, 48), (190, 210, 170))
        for y in range(48):
            for x in range(32):
                pixels.putpixel((x, y), (x * 7, y * 5, (x * 3 + y * 2) % 256))
        encoded = io.BytesIO()
        pixels.save(encoded, "JPEG", quality=90)
        pdf = pikepdf.Pdf.new()
        image = pdf.make_stream(encoded.getvalue())
        image.Type, image.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        image.Width, image.Height, image.BitsPerComponent = 32, 48, 8
        image.Filter = pikepdf.Name.DCTDecode
        image.ColorSpace = pikepdf.Name.DeviceRGB
        if icc:
            profile = pdf.make_stream((Path(__file__).parent / "scanpreview-p3.icc").read_bytes())
            profile.N = 3
            profile.Alternate = pikepdf.Name.DeviceRGB
            image.ColorSpace = pikepdf.Array([pikepdf.Name.ICCBased, profile])
        for _ in range(pages):
            page = pdf.add_blank_page(page_size=(72, 108))
            page.Rotate = angle
            page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
            page.Contents = pdf.make_stream(b"q\n72 0 0 108 0 0 cm\n/Im0 Do\nQ\n")
            if modify:
                modify(pdf, page, image)
        self.counter += 1
        path = self.folder / f"sample-{self.counter}.pdf"
        kwargs = {"encryption": pikepdf.Encryption(owner="owner", user="reader", R=4)} if encrypted else {}
        pdf.save(path, **kwargs)
        pdf.close()
        return path

    def preview(self, path, password=""):
        preview = module.ScanPreview(str(path), password)
        self.previews.append(preview)
        return preview

    def surface(self, angle=0):
        width, height = (108, 72) if angle in (90, 270) else (72, 108)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        return surface, cairo.Context(surface)

    @staticmethod
    def pillow(surface):
        buffer = io.BytesIO()
        surface.write_to_png(buffer)
        buffer.seek(0)
        return Image.open(buffer).convert("RGBA")

    def test_icc_and_rotations_match_poppler(self):
        if module.ImageCms is None:
            self.skipTest("Pillow has no ImageCms support")
        for angle in (0, 90, 180, 270):
            with self.subTest(angle=angle):
                path = self.document(icc=True, angle=angle)
                fast, cr = self.surface(angle)
                self.assertTrue(self.preview(path).paint(cr, 0))
                original, context = self.surface(angle)
                doc = Poppler.Document.new_from_file(path.as_uri(), None)
                doc.get_page(0).render(context)
                error = ImageStat.Stat(ImageChops.difference(self.pillow(fast), self.pillow(original))).mean
                self.assertLess(max(error), 1.0, error)
                doc = None

    def test_context_and_source_file_unchanged(self):
        path = self.document()
        before = hashlib.sha256(path.read_bytes()).digest()
        surface, cr = self.surface()
        cr.translate(2, 3)
        cr.scale(.5, .5)
        cr.set_source_rgb(.1, .2, .3)
        cr.rectangle(1, 2, 3, 4)
        matrix, source, old_path = tuple(cr.get_matrix()), cr.get_source().get_rgba(), list(cr.copy_path())
        self.assertTrue(self.preview(path).paint(cr, 0))
        self.assertEqual(tuple(cr.get_matrix()), matrix)
        self.assertEqual(cr.get_source().get_rgba(), source)
        self.assertEqual(list(cr.copy_path()), old_path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), before)

    def test_unsupported_content_returns_false_without_painting(self):
        def text(pdf, page, image):
            page.Contents = pdf.make_stream(b"q 72 0 0 108 0 0 cm /Im0 Do Q BT /F1 12 Tf (OCR) Tj ET")
        cases = {
            "text_or_ocr": text,
            "annotation": lambda pdf, page, im: setattr(page, "Annots", pikepdf.Array([pikepdf.Dictionary(
                Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Text, Rect=pikepdf.Array([1, 1, 10, 10]))])),
            "crop": lambda pdf, page, im: setattr(page, "CropBox", pikepdf.Array([1, 1, 70, 100])),
            "transparency_group": lambda pdf, page, im: setattr(page, "Group", pikepdf.Dictionary(S=pikepdf.Name.Transparency)),
            "soft_mask": lambda pdf, page, im: setattr(im, "SMask", pdf.make_stream(b"mask")),
            "color_key_mask": lambda pdf, page, im: setattr(im, "Mask", pikepdf.Array([0, 0, 0, 0, 0, 0])),
            "decode": lambda pdf, page, im: setattr(im, "Decode", pikepdf.Array([1, 0, 1, 0, 1, 0])),
            "decode_parameters": lambda pdf, page, im: setattr(im, "DecodeParms", pikepdf.Dictionary(ColorTransform=0)),
            "cmyk": lambda pdf, page, im: setattr(im, "ColorSpace", pikepdf.Name.DeviceCMYK),
            "user_unit": lambda pdf, page, im: setattr(page, "UserUnit", 2),
            "different_intent": lambda pdf, page, im: setattr(im, "Intent", pikepdf.Name.Perceptual),
            "extra_drawing": lambda pdf, page, im: setattr(page, "Contents", pdf.make_stream(
                b"q 72 0 0 108 0 0 cm /Im0 Do Q 0 0 5 5 re f")),
            "output_intent": lambda pdf, page, im: setattr(pdf.Root, "OutputIntents", pikepdf.Array([pikepdf.Dictionary(S=pikepdf.Name.GTS_PDFA1)])),
            "optional_content": lambda pdf, page, im: setattr(pdf.Root, "OCProperties", pikepdf.Dictionary(OCGs=pikepdf.Array([pikepdf.Dictionary(Name="Layer")]))),
            "default_color_space": lambda pdf, page, im: setattr(page.Resources, "ColorSpace", pikepdf.Dictionary(DefaultRGB=pikepdf.Name.DeviceRGB)),
        }
        for name, modify in cases.items():
            with self.subTest(case=name):
                path = self.document(modify)
                surface, cr = self.surface()
                before = bytes(surface.get_data())
                self.assertFalse(self.preview(path).paint(cr, 0))
                self.assertEqual(bytes(surface.get_data()), before)

    def test_bad_jpeg_falls_back(self):
        path = self.document(lambda pdf, page, image: image.write(b"not a jpeg", filter=pikepdf.Name.DCTDecode))
        _, cr = self.surface()
        self.assertFalse(self.preview(path).paint(cr, 0))

    def test_missing_optional_color_support_falls_back(self):
        path = self.document(icc=True)
        old = module.ImageCms
        module.ImageCms = None
        try:
            _, cr = self.surface()
            self.assertFalse(self.preview(path).paint(cr, 0))
        finally:
            module.ImageCms = old

    def test_encrypted_scan(self):
        path = self.document(encrypted=True)
        _, cr = self.surface()
        self.assertTrue(self.preview(path, "reader").paint(cr, 0))

    def test_renderer_fallback_preserves_extra_drawing(self):
        path = self.document(lambda pdf, page, image: setattr(page, "Contents", pdf.make_stream(
            b"q 72 0 0 108 0 0 cm /Im0 Do Q 1 0 0 rg 0 0 36 54 re f")))
        doc = PDFDoc(str(path), None, None, None, self.tmp.name, None)
        self.previews.append(doc.scan_preview)
        renderer = PDFRenderer([], [doc], (0, 0), 1)
        actual, cr = self.surface()
        renderer.render(cr, SimpleNamespace(nfile=1, npage=1))
        expected, cr = self.surface()
        doc.get_page(0).render(cr)
        self.assertEqual(bytes(actual.get_data()), bytes(expected.get_data()))
        self.assertIsNone(doc.scan_preview.checked[0])
        doc.document = None

    def test_cache_bound_eviction_and_release(self):
        self.assertEqual(module._CACHE_BYTES, 0)
        path = self.document(pages=2)
        preview = self.preview(path)
        old_limit = module._CACHE_LIMIT
        cost = 32 * 48 * 4
        module._CACHE_LIMIT = cost * 2 - 1
        try:
            _, cr = self.surface()
            self.assertTrue(preview.paint(cr, 0))
            first = module._CACHE[(preview.token, 0)]
            self.assertTrue(preview.paint(cr, 0))
            self.assertIs(module._CACHE[(preview.token, 0)], first)
            self.assertTrue(preview.paint(cr, 1))
            self.assertNotIn((preview.token, 0), module._CACHE)
            self.assertLessEqual(module._CACHE_BYTES, module._CACHE_LIMIT)
            token = preview.token
            self.previews.remove(preview)
            del preview
            gc.collect()
            self.assertFalse(any(key[0] is token for key in module._CACHE))
            self.assertEqual(module._CACHE_BYTES, 0)
        finally:
            module._CACHE_LIMIT = old_limit


if __name__ == "__main__":
    unittest.main()
