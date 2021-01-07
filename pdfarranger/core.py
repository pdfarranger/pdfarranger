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

__all__ = [
    "img2pdf_supported_img",
    "Page",
    "PageAdder",
    "PDFDoc",
    "PDFDocError",
    "PDFRenderer",
]

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
from gi.repository import Gtk

gi.require_version("Poppler", "0.18")
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
    def __init__(self, nfile, npage, zoom, copyname, angle, scale, crop, size, basename):
        #: The ID (from 1 to n) of the PDF file owning the page
        self.nfile = nfile
        #: The ID (from 1 to n) of the page in its owner PDF document
        self.npage = npage
        self.zoom = zoom
        #: Filepath to the temporary stored file
        self.copyname = copyname
        #: Left, right, top, bottom crop
        self.crop = list(crop)
        #: width and height
        self.size = list(size)
        self.angle = angle
        self.thumbnail = None
        self.resample = 2
        self.scale = scale
        #: The name of the original file
        self.basename = basename

    def description(self):
        shortname = os.path.splitext(self.basename)[0]
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
        ts = [self.copyname, self.npage, self.basename, self.angle, self.scale] + list(self.crop)
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

    def split(self, leftcrops, topcrops):
        """Split this page into a grid and return all but the top-left page."""
        newpages = []
        left, right, top, bottom = self.crop
        # If the page is cropped, adjust the new crop for the visible part of the page.
        hscale = 1 - (left + right)
        vscale = 1 - (top + bottom)
        leftcrops = [l * hscale for l in leftcrops]
        topcrops = [t * vscale for t in topcrops]
        for i in reversed(range(len(topcrops)-1)):
            topcrop = top + topcrops[i]
            row_height = topcrops[i+1] - topcrops[i]
            bottomcrop = 1 - (topcrop + row_height)
            for j in reversed(range(len(leftcrops)-1)):
                leftcrop = left + leftcrops[j]
                col_width = leftcrops[j+1] - leftcrops[j]
                rightcrop = 1 - (leftcrop + col_width)
                crop = [leftcrop, rightcrop, topcrop, bottomcrop]
                if i == 0 and j == 0:
                    # Update the original page
                    self.crop = crop
                else:
                    # Create a new cropped page
                    new = self.duplicate()
                    new.crop = crop
                    newpages.append(new)
        return newpages


class PDFDocError(Exception):
    def __init__(self, message):
        self.message = message


class _UnknownPasswordException(Exception):
    pass


class PasswordDialog(Gtk.Dialog):
    def __init__(self, parent, filename):
        super().__init__(
            title=_("Password required"),
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
            buttons=(
                Gtk.STOCK_CANCEL,
                Gtk.ResponseType.CANCEL,
                Gtk.STOCK_OK,
                Gtk.ResponseType.OK,
            ),
        )
        self.set_default_response(Gtk.ResponseType.OK)
        bottommsg = _("The password will be remembered until you close PDF-Arranger.")
        topmsg = _("The document “{}” is locked and requires a password before it can be opened.")
        label = Gtk.Label(label=topmsg.format(filename))
        label.set_max_width_chars(len(bottommsg)-6)
        label.set_line_wrap(True)
        label.set_size_request(0, -1)
        self.vbox.pack_start(label, False, False, 12)
        box = Gtk.HBox()
        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_activates_default(True)
        box.pack_start(Gtk.Label(label=_("Password")), False, False, 6)
        box.pack_start(self.entry, True, True, 6)
        self.vbox.pack_start(box, True, True, 0)
        self.vbox.pack_start(Gtk.Label(label=bottommsg), False, False, 12)
        self.set_resizable(False)

    def get_password(self):
        self.show_all()
        r = self.run()
        t = self.entry.props.text
        self.destroy()
        if r == Gtk.ResponseType.OK:
            return t
        else:
            raise _UnknownPasswordException()


class PDFDoc:
    """Class handling PDF documents."""

    def __from_file(self, parent, basename):
        uri = pathlib.Path(self.copyname).as_uri()
        askpass = False
        while True:
            try:
                if askpass:
                    self.password = PasswordDialog(parent, basename).get_password()
                self.document = Poppler.Document.new_from_file(uri, self.password)
                # When there is no encryption Poppler want None as password
                # while PikePDF want an empty string
                self.password = "" if self.password is None else self.password
                return
            except GLib.Error as e:
                askpass = e.message == "Document is encrypted"
                if not askpass:
                    raise e

    def __init__(self, filename, basename, tmp_dir, parent):
        self.filename = os.path.abspath(filename)
        self.mtime = os.path.getmtime(filename)
        if basename is None:  # When importing files
            self.basename = os.path.basename(filename)
        else:  # When copy-pasting
            self.basename = basename
        self.password = ""
        filemime = mimetypes.guess_type(self.filename)[0]
        if not filemime:
            raise PDFDocError(_("Unknown file format"))
        if filemime == "application/pdf":
            if self.filename.startswith(tmp_dir) and basename is None:
                # In the "Insert Blank Page" we don't need to copy self.filename
                self.copyname = self.filename
                self.basename = ""
            else:
                fd, self.copyname = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
                os.close(fd)
                shutil.copy(self.filename, self.copyname)
            try:
                self.__from_file(parent, self.basename)
            except GLib.Error as e:
                raise PDFDocError(e.message + ": " + filename)
        elif filemime.split("/")[0] == "image":
            if not img2pdf:
                raise PDFDocError(_("Image files are only supported with img2pdf"))
            if mimetypes.guess_type(filename)[0] in img2pdf_supported_img:
                fd, self.copyname = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
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

    def addpages(self, filename, page=-1, basename=None, angle=0, scale=1.0, crop=None):
        crop = [0] * 4 if crop is None else crop
        pdfdoc = None
        nfile = None
        # Check if added page or file already exist in pdfqueue
        for i, it_pdfdoc in enumerate(self.app.pdfqueue):
            if basename is not None and filename == it_pdfdoc.copyname:
                # File of copy-pasted page was found in pdfqueue
                pdfdoc = it_pdfdoc
                nfile = i + 1
                break
            elif (os.path.isfile(it_pdfdoc.filename)
                  and os.path.samefile(filename, it_pdfdoc.filename)
                  and os.path.getmtime(filename) == it_pdfdoc.mtime):
                # Imported file was found in pdfqueue
                pdfdoc = it_pdfdoc
                nfile = i + 1
                break

        if not pdfdoc:
            try:
                pdfdoc = PDFDoc(filename, basename, self.app.tmp_dir, self.app.window)
            except _UnknownPasswordException:
                return
            except PDFDocError as e:
                print(e.message, file=sys.stderr)
                self.app.error_message_dialog(e.message)
                return
            if pdfdoc.copyname != pdfdoc.filename and basename is None:
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
                    pdfdoc.copyname,
                    angle,
                    scale,
                    crop,
                    page.get_size(),
                    pdfdoc.basename,
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
        idx = -2  # signal rendering ended
        GObject.idle_add(
            self.emit, "update_thumbnail", idx, None, 0.0, priority=GObject.PRIORITY_LOW
        )

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
