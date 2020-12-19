# Copyright (C) 2020 pdfarranger contributors
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

import sys
import os
import mimetypes
import copy
import pathlib
import shutil
import tempfile
import threading
import gettext
import gi
from gi.repository import GObject
from gi.repository import GLib
gi.require_version('Poppler', '0.18')
from gi.repository import Poppler  # for the rendering of pdf pages
import cairo


try:
    import img2pdf

    img2pdf.Image.init()
    img2pdf_supported_img = [
        i for i in img2pdf.Image.MIME.values() if i.split("/")[0] == "image"
    ]
except ImportError:
    img2pdf_supported_img = []
    img2pdf = None


_ = gettext.gettext


class Page:
    def __init__(self, nfile, npage, zoom, filename, angle, scale, crop, size):
        #: The ID (from 1 to n) of the PDF file owning the page
        self.nfile = nfile
        #: The ID (from 1 to n) of the page in its owner PDF document
        self.npage = npage
        self.zoom = zoom
        self.filename = filename
        #: Left, right, top, bottom crop
        self.crop = list(crop)
        #: width and height
        self.size = list(size)
        self.angle = angle
        self.thumbnail = None
        self.resample = 2
        self.scale = scale

    def description(self):
        shortname = os.path.split(self.filename)[1]
        shortname = os.path.splitext(shortname)[0]
        return "".join([shortname, "\n", _("page"), " ", str(self.npage)])

    def width_in_points(self):
        """Return the page width in PDF points."""
        return (self.scale * self.size[0]) * (1 - self.crop[0] - self.crop[1])

    def height_in_points(self):
        """Return the page height in PDF points."""
        return (self.scale * self.size[1]) * (1 - self.crop[2] - self.crop[3])

    def size_in_points(self):
        """Return the page size in PDF points."""
        return (self.width_in_points(), self.height_in_points())

    def width_in_pixel(self):
        return int(0.5 + self.zoom * self.width_in_points())

    def height_in_pixel(self):
        return int(0.5 + self.zoom * self.height_in_points())

    def rotate(self, angle):
        rotate_times = int(round(((-angle) % 360) / 90) % 4)
        if rotate_times == 0:
            return False
        perm = [0, 2, 1, 3]
        for __ in range(rotate_times):
            perm.append(perm.pop(0))
        perm.insert(1, perm.pop(2))
        self.crop = [self.crop[x] for x in perm]
        self.angle = (self.angle + int(angle)) % 360
        return True

    def serialize(self):
        """Convert to string for copy/past operations."""
        ts = [self.filename, self.npage, self.angle, self.scale] + list(self.crop)
        return "\n".join([str(v) for v in ts])

    def duplicate(self, incl_thumbnail=True):
        r = copy.copy(self)
        r.crop = list(r.crop)
        r.size = list(r.size)
        if incl_thumbnail == False:
            del r.thumbnail  # to save ram
            r.thumbnail = None
        return r

    def set_size(self, size):
        """set this page size from the Poppler page."""
        self.size = list(size)
        rotation = int(self.angle) % 360
        rotation = round(rotation / 90) * 90
        if rotation == 90 or rotation == 270:
            self.size.reverse()

    def split(self):
        """Split this page and return the result right page."""
        newpage = self.duplicate()
        left, right = self.crop[:2]
        newcrop = (1 + left - right) / 2
        newpage.crop[0] = newcrop
        self.crop[1] = 1 - newcrop
        return newpage


class PDFDocError(Exception):
    def __init__(self, message):
        self.message = message


class PDFDoc:
    """Class handling PDF documents."""

    def __init__(self, filename, tmp_dir):
        self.filename = os.path.abspath(filename)
        self.mtime = os.path.getmtime(filename)
        filemime = mimetypes.guess_type(self.filename)[0]
        if not filemime:
            raise PDFDocError(_("Unknown file format"))
        if filemime == "application/pdf":
            try:
                fd, self.copyname = tempfile.mkstemp(dir=tmp_dir)
                os.close(fd)
                shutil.copy(self.filename, self.copyname)
                uri = pathlib.Path(self.copyname).as_uri()
                self.document = Poppler.Document.new_from_file(uri, None)
            except GLib.Error as e:
                raise PDFDocError(e.message + ": " + filename)
        elif filemime.split("/")[0] == "image":
            if not img2pdf:
                raise PDFDocError(_("Image files are only supported with img2pdf"))
            if mimetypes.guess_type(filename)[0] in img2pdf_supported_img:
                fd, self.copyname = tempfile.mkstemp(dir=tmp_dir)
                os.close(fd)
                with open(self.copyname, "wb") as f:
                    img = img2pdf.Image.open(filename)
                    if img.mode != "RGBA" and "transparency" in img.info:
                        # TODO: Find a way to keep image in P or L format and remove transparency.
                        # This will work but converting from 1, L, P to RGB is not optimal.
                        img = img.convert("RGBA")
                    if img.mode == "RGBA":
                        bg = img2pdf.Image.new("RGB", img.size, (255, 255, 255))
                        bg.paste(img, mask=img.split()[-1])
                        imgio = img2pdf.BytesIO()
                        bg.save(imgio, "PNG")
                        imgio.seek(0)
                        f.write(img2pdf.convert(imgio))
                    else:
                        f.write(img2pdf.convert(filename))
                uri = pathlib.Path(self.copyname).as_uri()
                self.document = Poppler.Document.new_from_file(uri, None)
            else:
                raise PDFDocError(_("Image format is not supported by img2pdf"))
        else:
            raise PDFDocError(_("File is neither pdf nor image"))


class PageAdder:
    """Helper class to add pages to the current model."""

    def __init__(self, app):
        #: A PdfArranger instance
        self.app = app
        #: The pages which will be added by the commit method
        self.pages = []
        #: Where to insert pages relatively to treerowref
        self.before = False
        #: Where to insert pages. If None pages are inserted at the end
        self.treerowref = None

    def move(self, treerowref, before):
        """Insert pages at the given location."""
        self.before = before
        self.treerowref = treerowref

    def addpages(self, filename, page=-1, angle=0, scale=1.0, crop=None):
        crop = [0] * 4 if crop is None else crop
        pdfdoc = None
        nfile = None
        for i, it_pdfdoc in enumerate(self.app.pdfqueue):
            if (
                os.path.isfile(it_pdfdoc.filename)
                and os.path.samefile(filename, it_pdfdoc.filename)
                and os.path.getmtime(filename) is it_pdfdoc.mtime
            ):
                pdfdoc = it_pdfdoc
                nfile = i + 1
                break

        if not pdfdoc:
            try:
                pdfdoc = PDFDoc(filename, self.app.tmp_dir)
            except PDFDocError as e:
                print(e.message, file=sys.stderr)
                self.app.error_message_dialog(e.message)
                return
            self.app.import_directory = os.path.split(filename)[0]
            self.app.export_directory = self.app.import_directory
            self.app.pdfqueue.append(pdfdoc)
            nfile = len(self.app.pdfqueue)

        n_end = pdfdoc.document.get_n_pages()
        n_start = min(n_end, max(1, page))
        if page != -1:
            n_end = max(n_start, min(n_end, page))

        for npage in range(n_start, n_end + 1):
            page = pdfdoc.document.get_page(npage - 1)
            self.pages.append(
                Page(
                    nfile,
                    npage,
                    self.app.zoom_scale,
                    pdfdoc.filename,
                    angle,
                    scale,
                    crop,
                    page.get_size(),
                )
            )

    def commit(self, select_added, add_to_undomanager):
        if len(self.pages) == 0:
            return False
        if add_to_undomanager:
            self.app.undomanager.commit("Add")
            self.app.set_unsaved(True)
        for p in self.pages:
            m = [p, p.description()]
            if self.treerowref:
                iter_to = self.app.model.get_iter(self.treerowref.get_path())
                if self.before:
                    it = self.app.model.insert_before(iter_to, m)
                else:
                    it = self.app.model.insert_after(iter_to, m)
            else:
                it = self.app.model.append(m)
            if select_added:
                path = self.app.model.get_path(it)
                self.app.iconview.select_path(path)
            self.app.update_geometry(it)
        GObject.idle_add(self.app.retitle)
        GObject.idle_add(self.app.render)
        self.pages = []
        return True


class PDFRenderer(threading.Thread, GObject.GObject):
    def __init__(self, model, pdfqueue, resample, start_p):
        threading.Thread.__init__(self)
        GObject.GObject.__init__(self)
        self.model = model
        self.pdfqueue = pdfqueue
        self.resample = resample
        self.quit = False
        self.start_p = start_p

    def run(self):
        idx = -1  # signal rendering (re)started for progressbar
        GObject.idle_add(
            self.emit, "update_thumbnail", idx, None, 0.0, priority=GObject.PRIORITY_LOW
        )
        if self.start_p == 0:
            for idx, row in enumerate(self.model):
                self.update(idx, row)
        else:
            # Rendering order: begin from start_p, then expand around start_p
            self.update(self.start_p, self.model[self.start_p])
            for cnt in range(1, len(self.model)):
                previous_p = self.start_p - cnt
                next_p = self.start_p + cnt
                if previous_p < 0 and next_p > len(self.model):
                    return
                if previous_p >= 0:
                    self.update(previous_p, self.model[previous_p])
                if next_p < len(self.model):
                    self.update(next_p, self.model[next_p])

    def update(self, idx, row):
        p = row[0]
        if self.quit:
            return
        pdfdoc = self.pdfqueue[p.nfile - 1]
        page = pdfdoc.document.get_page(p.npage - 1)
        w, h = page.get_size()
        scale = p.scale / self.resample
        thumbnail = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, int(w * scale), int(h * scale)
        )
        cr = cairo.Context(thumbnail)
        if scale != 1.0:
            cr.scale(scale, scale)
        page.render(cr)
        GObject.idle_add(
            self.emit,
            "update_thumbnail",
            idx,
            thumbnail,
            self.resample,
            priority=GObject.PRIORITY_LOW,
        )
