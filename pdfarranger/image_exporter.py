# Copyright (C) 2025 pdfarranger contributors
#
# pdfarranger is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


import cairo
import img2pdf
import pikepdf
import traceback

from math import pi
from gi.repository import Gtk, GObject

from .core import PDFRenderer, _img_to_pdf
from .exporter import _set_meta
from .metadata import merge


class ImageExporter:
    """Export to png, jpg or rasterized pdf (with png or jpg images)"""
    def __init__(self, files, pages, metadata, files_out, config, pdfqueue, exportmode, export_msg):
        self.files = files
        self.model = Gtk.ListStore(GObject.TYPE_PYOBJECT)
        for page in pages:
            page.zoom = config.image_ppi() / 72  # pdf is 72 dpi
            page.resample = -1
            self.model.append([page])
        self.ppi = config.image_ppi()
        self.optimize = config.optimize()
        self.greyscale = config.greyscale()
        self.metadata = metadata
        self.files_out = files_out
        self.pdfqueue = pdfqueue
        self.exportmode = exportmode
        self.export_msg = export_msg
        self.rendering_thread = None
        if exportmode in ['SELECTED_TO_PDF_PNG', 'SELECTED_TO_PDF_JPG']:
            self.pdf_out = pikepdf.Pdf.new()
        self.is_saving = True
        self.exitcode = 1  # unhandled exception

    def start(self):
        prange = [0, len(self.model) - 1]
        self.rendering_thread = PDFRenderer(self.model, self.pdfqueue, prange, 1, max_nqueue=3)
        self.rendering_thread.connect('update_thumbnail', self.create_page)
        self.rendering_thread.start()

    def join(self, timeout=None):
        if not self.rendering_thread:
            return
        self.rendering_thread.quit = True
        self.rendering_thread.join(timeout)
        self.is_saving = False

    def is_alive(self):
        return self.is_saving

    def create_page(self, _obj, ref, thumbnail, _zoom, _scale, _is_preview):
        if self.rendering_thread.quit:
            return
        if thumbnail is None:
            # Rendering has ended
            if self.exportmode in ['SELECTED_TO_PDF_PNG', 'SELECTED_TO_PDF_JPG']:
                self.save_pdf()
            self.is_saving = False
            return
        path = ref.get_path()
        page = self.model[path][0]
        ind = Gtk.TreePath.get_indices(path)[0]

        w = thumbnail.get_width()
        h = thumbnail.get_height()
        w1, h1 = (h, w) if page.angle in [90, 270] else (w, h)
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, w1, h1)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(0, 0, w1, h1)
        cr.fill()

        if page.angle > 0:
            cr.translate(w1 / 2, h1 / 2)
            cr.rotate(page.angle * pi / 180)
            cr.translate(-w / 2, -h / 2)
        cr.set_source_surface(thumbnail)
        cr.paint()

        imgpil = self.surface_to_pil(surface)
        if self.greyscale:
            imgpil = imgpil.convert('L')

        ext = 'png' if self.exportmode in ['SELECTED_TO_PNG', 'SELECTED_TO_PDF_PNG'] else 'jpeg'
        if self.exportmode in ['SELECTED_TO_PNG', 'SELECTED_TO_JPG']:
            self.save_image(imgpil, ext, self.files_out[ind])
        else:
            self.add_to_pdf(imgpil, ext, page.size_in_points())
        self.rendering_thread.nqueue -= 1

    @staticmethod
    def surface_to_pil(surface):
        size = (surface.get_width(), surface.get_height())
        stride = surface.get_stride()
        with surface.get_data() as memory:
            return img2pdf.Image.frombuffer('RGB', size, memory.tobytes(), 'raw', 'BGRX', stride)

    def save_image(self, imgpil, ext, filename):
        try:
            imgpil.save(filename, ext, dpi=(self.ppi, self.ppi), optimize=self.optimize)
        except OSError as e:
            self.exception_handler(e)
        self.exitcode = 0

    def add_to_pdf(self, imgpil, ext, page_size):
        imgio = img2pdf.BytesIO()
        try:
            imgpil.save(imgio, ext, dpi=(self.ppi, self.ppi), optimize=self.optimize)
        except OSError as e:
            self.exception_handler(e)
            return
        imgio.seek(0)
        pdf = _img_to_pdf([imgio], tmp_dir=None, page_size=page_size)
        src = pikepdf.Pdf.open(pdf)
        self.pdf_out.pages.extend(src.pages)

    def save_pdf(self):
        m = merge(self.metadata, self.files)
        _set_meta(m, [], self.pdf_out)
        try:
            self.pdf_out.save(self.files_out[0])
        except OSError as e:
            self.exception_handler(e)
        if len(self.pdf_out.pages) == len(self.model):
            self.exitcode = 0
        else:
            self.exitcode = 10  # exception in add_to_pdf()

    def exception_handler(self, e):
        print(traceback.format_exc())
        self.export_msg.put([str(e), Gtk.MessageType.ERROR])
        self.join()
