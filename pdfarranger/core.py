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
import traceback
import mimetypes
import copy
import pathlib
import shutil
import tempfile
import threading
from typing import NamedTuple, Optional, Tuple, Union
import gettext
import gi
from gi.repository import GObject
from gi.repository import GLib
from gi.repository import Gtk

gi.require_version("Poppler", "0.18")
from gi.repository import Poppler  # for the rendering of pdf pages
import cairo
from math import pi


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

Numeric = Union[float, int]


class Sides(NamedTuple):
    left: Numeric = 0
    right: Numeric = 0
    top: Numeric = 0
    bottom: Numeric = 0

    def __neg__(self) -> "Sides":
        """
        Pointwise unary minus

        Example:

        >>> -Sides(9, 3, 12, 6)
        Sides(left=-9, right=-3, top=-12, bottom=-6)
        """
        return Sides(*(-self[i] for i in range(4)))

    def __add__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise addition

        Example:

        >>> Sides(9, 3, 12, 6) + Sides(1, 2, 3, 4)
        Sides(left=10, right=5, top=15, bottom=10)
        >>> Sides(9, 3, 12, 6) + 1
        Sides(left=10, right=4, top=13, bottom=7)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] + other[i] for i in range(4)))
        else:
            return Sides(*(self[i] + other for i in range(4)))

    def __sub__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise subtraction

        Example:

        >>> Sides(9, 3, 12, 6) - Sides(1, 2, 3, 4)
        Sides(left=8, right=1, top=9, bottom=2)
        >>> Sides(9, 3, 12, 6) - 3
        Sides(left=6, right=0, top=9, bottom=3)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] - other[i] for i in range(4)))
        else:
            return Sides(*(self[i] -+ other for i in range(4)))

    def __mul__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise multiplication

        Example:

        >>> Sides(9, 3, 12, 6) * Sides(1, 2, 3, 4)
        Sides(left=9, right=6, top=36, bottom=24)
        >>> Sides(9, 3, 12, 6) * 3
        Sides(left=27, right=9, top=36, bottom=18)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] * other[i] for i in range(4)))
        else:
            return Sides(*(self[i] * other for i in range(4)))

    def __truediv__(self, other: Union["Sides", Numeric]) -> "Sides":
        """
        Pointwise division

        Example:

        >>> Sides(9, 3, 12, 6) / Sides(1, 2, 3, 4)
        Sides(left=9.0, right=1.5, top=4.0, bottom=1.5)
        >>> Sides(9, 3, 12, 6) / 3
        Sides(left=3.0, right=1.0, top=4.0, bottom=2.0)
        """
        if isinstance(other, Sides):
            return Sides(*(self[i] / other[i] for i in range(4)))
        else:
            return Sides(*(self[i] / other for i in range(4)))

    def rotated(self, times: int) -> "Sides":
        """
        Rotate 90 degrees counter-clockwise 'times' times

        Examples:

        >>> Sides(9,3,12,6).rotated(1)
        Sides(left=12, right=6, top=3, bottom=9)
        >>> Sides(9,3,12,6).rotated(-3) == Sides(9,3,12,6).rotated(1)
        True
        """
        perm = (0, 2, 1, 3)
        return Sides(*(self[perm[(x + times) % 4]] for x in perm))


class Dims(NamedTuple):
    width: Numeric
    height: Numeric

    def __neg__(self) -> "Dims":
        """
        Pointwise unary minus

        Example:

        >>> -Dims(612, 792)
        Dims(width=-612, height=-792)
        """
        return Dims(*(-self[i] for i in range(2)))

    def __add__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise addition

        Example:

        >>> Dims(612, 792) + Dims(612, 792)
        Dims(width=1224, height=1584)
        >>> Dims(612, 792) + 100
        Dims(width=712, height=892)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] + other[i] for i in range(2)))
        else:
            return Dims(*(self[i] + other for i in range(2)))

    def __sub__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise subtraction

        Example:

        >>> Dims(612, 792) - Dims(306, 396)
        Dims(width=306, height=396)
        >>> Dims(612, 792) - 100
        Dims(width=512, height=692)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] - other[i] for i in range(2)))
        else:
            return Dims(*(self[i] -+ other for i in range(2)))

    def __mul__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise multiplication

        Example:

        >>> Dims(612, 792) * Dims(0.5, 0.25)
        Dims(width=306.0, height=198.0)
        >>> Dims(612, 792) * 2
        Dims(width=1224, height=1584)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] * other[i] for i in range(2)))
        else:
            return Dims(*(self[i] * other for i in range(2)))

    def __truediv__(self, other: Union["Dims", Numeric]) -> "Dims":
        """
        Pointwise division

        Example:

        >>> Dims(612, 792) / Dims(2, 4)
        Dims(width=306.0, height=198.0)
        >>> Dims(612, 792) / 2
        Dims(width=306.0, height=396.0)
        """
        if isinstance(other, Dims):
            return Dims(*(self[i] / other[i] for i in range(2)))
        else:
            return Dims(*(self[i] / other for i in range(2)))

    def flipped(self) -> "Dims":
        """Swap height and width"""
        return Dims(self.height, self.width)

    def scaled(self, factor: float) -> "Dims":
        """Scale by factor"""
        return Dims(self.width * factor, self.height * factor)

    def int_scaled(self, factor: float) -> "Dims":
        """Scale by factor and round to nearest int"""
        return Dims(int(self.width * factor + 0.5), int(self.height * factor + 0.5))

    def cropped(self, crop: Sides) -> "Dims":
        """Crop using crop array"""
        return Dims(self.width * (1 - crop.left - crop.right), self.height * (1 - crop.top - crop.bottom))


class BasePage:
    """Common base class for Page and LayerPage"""

    def __init__(self, nfile, npage, copyname, angle, scale, crop: Sides, size_orig: Dims):
        self.nfile = nfile
        """The ID (from 1 to n) of the PDF file owning the page"""
        self.npage = npage
        """The ID (from 1 to n) of the page in its owner PDF document"""
        self.copyname = copyname
        """Filepath to the temporary stored file"""
        self.angle = angle
        self.scale = scale
        self.crop = crop
        """Left, right, top, bottom crop"""
        self.size_orig = size_orig
        """Width and height of the original page"""
        self.size = size_orig if angle in [0, 180] else size_orig.flipped()
        """Width and height"""

    def width_in_points(self) -> Numeric:
        """Return the page width in PDF points."""
        return self.size_in_points().width

    def height_in_points(self) -> Numeric:
        """Return the page height in PDF points."""
        return self.size_in_points().height

    def size_in_points(self) -> Dims:
        """Return the page size in PDF points."""
        return self.size.scaled(self.scale).cropped(self.crop)

    def width_in_pixel(self):
        return self.size_in_pixel().width

    def height_in_pixel(self):
        return self.size_in_pixel().height

    def size_in_pixel(self):
        return self.size_in_points().int_scaled(self.zoom)

    @staticmethod
    def rotate_times(angle: int) -> int:
        """Convert an angle in degree to a number of 90° rotation (integer)."""
        return round((-angle  / 90) % 4)


class Page(BasePage):
    def __init__(self, nfile, npage, zoom, copyname, angle, scale, crop: Sides, size_orig: Dims, basename, layerpages):
        super().__init__(nfile, npage, copyname, angle, scale, Sides(*crop), size_orig)
        self.zoom = zoom
        self.thumbnail = None
        self.resample = -1
        self.preview = None
        """A low resolution thumbnail"""
        #: The name of the original file
        self.basename = basename
        """The name of the original file"""
        self.layerpages = list(layerpages)

    def __repr__(self):
        return (f"Page({self.nfile}, {self.npage}, {self.zoom}, '{self.copyname}', {self.angle}, "
                f"{self.scale}, {self.crop}, {self.size_orig}, '{self.basename}', {self.layerpages})")

    def description(self):
        shortname = os.path.splitext(self.basename)[0]
        return "".join([shortname, "\n", _("page"), " ", str(self.npage)])

    def rotate(self, angle: int):
        rt = self.rotate_times(angle)
        if rt == 0:
            return False
        self.crop = self.crop.rotated(rt)
        self.angle = (self.angle + int(angle)) % 360
        self.size = self.size_orig if self.angle in [0, 180] else self.size_orig.flipped()
        for lp in self.layerpages:
            lp.rotate(rt)
        return True

    def unmodified(self):
        u = self.angle == 0 and self.crop == Sides() and self.scale == 1 and len(self.layerpages) == 0
        return u

    def serialize(self):
        """Convert to string for copy/past operations."""
        lpdata = [lp.serialize() for lp in self.layerpages]
        ts = [self.copyname, self.npage, self.basename, self.angle, self.scale]
        ts += list(self.crop) + list(lpdata)
        return "\n".join([str(v) for v in ts])

    def duplicate(self, incl_thumbnail=True):
        r = copy.copy(self)
        r.layerpages = [lp.duplicate() for lp in r.layerpages]
        if incl_thumbnail == False:
            del r.thumbnail  # to save ram
            r.thumbnail = None
            r.preview = None
        return r

    def split(self, vcrops, hcrops):
        """Split this page into a grid and return all but the top-left page."""
        newpages = []
        left, right, top, bottom = self.crop
        # If the page is cropped, adjust the new crop for the visible part of the page.
        hscale = 1 - (left + right)
        vscale = 1 - (top + bottom)
        vcrops = [(l * hscale, r * hscale) for (l, r) in vcrops]
        hcrops = [ (t * vscale, b * vscale) for (t, b) in hcrops]

        for (t, b) in reversed(hcrops):
            topcrop = top + t
            row_height = b - t
            bottomcrop = 1 - (topcrop + row_height)
            for (l, r) in reversed(vcrops):
                leftcrop = left + l
                col_width = r - l
                rightcrop = 1 - (leftcrop + col_width)
                crop = Sides(leftcrop, rightcrop, topcrop, bottomcrop)
                if l == 0.0 and t == 0.0:
                    # Update the original page
                    self.crop = crop
                else:
                    # Create a new cropped page
                    new = self.duplicate()
                    new.crop = crop
                    newpages.append(new)
        return newpages


class LayerPage(BasePage):
    """Page added as overlay or underlay on a Page."""

    def __init__(self, nfile, npage, copyname, angle, scale, crop, offset, laypos, size_orig: Dims):
        super().__init__(nfile, npage, copyname, angle, scale, Sides(*crop), size_orig)
        self.offset = Sides(*offset)
        """Left, right, top, bottom offset from dest page edges"""
        self.laypos = laypos
        """OVERLAY or UNDERLAY"""

    def __repr__(self):
        return (f"LayerPage({self.nfile}, {self.npage}, '{self.copyname}', {self.angle}, "
                f"{self.scale}, {self.crop}, {self.offset}, '{self.laypos}', {self.size_orig})")

    def rotate(self, times: int):
        if times != 0:
            self.crop = self.crop.rotated(times)
            self.offset = self.offset.rotated(times)
            self.angle = (self.angle - 90 * times) % 360
            self.size = self.size if times % 2 == 0 else self.size.flipped()

    def serialize(self):
        """Convert to string for copy/past operations."""
        ts = [self.copyname, self.npage, self.angle, self.scale, self.laypos]
        ts += list(self.crop) + list(self.offset)
        return "\n".join([str(v) for v in ts])

    def duplicate(self):
        r = copy.copy(self)
        return r


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
                "_Cancel",
                Gtk.ResponseType.CANCEL,
                "_OK",
                Gtk.ResponseType.OK,
            ),
        )
        self.set_default_response(Gtk.ResponseType.OK)
        bottommsg = _("The password will be remembered until you close PDF Arranger.")
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


def _img_to_pdf(filename, tmp_dir):
    """Wrap img2pdf.convert to handle some corner cases"""
    fd, pdf_file_name = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
    os.close(fd)
    with open(pdf_file_name, "wb") as f:
        img = img2pdf.Image.open(filename)
        if (img.mode == "LA") or (img.mode != "RGBA" and "transparency" in img.info):
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
            try:
                # Try to handle invalid EXIF rotation
                rot = img2pdf.Rotation.ifvalid
            except AttributeError:
                # img2pdf is too old so we can't support invalid EXIF rotation
                rot = None
            f.write(img2pdf.convert(filename, rotation=rot))
    return pdf_file_name


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

    def __init__(self, filename, basename, stat, tmp_dir, parent):
        self.render_lock = threading.Lock()
        self.filename = os.path.abspath(filename)
        self.stat = stat
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
                self.copyname = _img_to_pdf(filename, tmp_dir)
                uri = pathlib.Path(self.copyname).as_uri()
                self.document = Poppler.Document.new_from_file(uri, None)
            else:
                raise PDFDocError(_("Image format is not supported by img2pdf"))
            if filename.startswith(tmp_dir) and filename.endswith(".png"):
                os.remove(filename)
                self.basename = _("Clipboard image")
        else:
            raise PDFDocError(_("File is neither pdf nor image"))

        self.transparent_link_annots_removed = [False] * self.document.get_n_pages()

    def get_page(self, n_page):
        """Get a page where transparent link annotations are removed.

        By removing them memory usage will be lower.
        """
        page = self.document.get_page(n_page)
        if self.transparent_link_annots_removed[n_page]:
            return page
        annot_mapping_list = page.get_annot_mapping()
        for annot_mapping in annot_mapping_list:
            a = annot_mapping.annot
            if a.get_annot_type() == Poppler.AnnotType.LINK and a.get_color() is None:
                page.remove_annot(a)
        self.transparent_link_annots_removed[n_page] = True
        return page

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
        self.stat_cache = {}
        self.content = []
        self.pdfqueue_used = True

    def move(self, treerowref, before):
        """Insert pages at the given location."""
        self.before = before
        self.treerowref = treerowref

    def get_pdfdoc(self, filename: str, basename: Optional[str] = None) -> Optional[Tuple[PDFDoc, int, bool]]:
        """Get the pdfdoc object for the filename.

        pdfqueue is searched for the filename. If it is not found a pdfdoc is created
        and added to pdfqueue.
        Returns: pdfdoc object, it's file number, if a new pdfdoc was created.
        """
        for i, it_pdfdoc in enumerate(self.app.pdfqueue):
            if filename == it_pdfdoc.copyname:
                # File of copy-pasted page was found in pdfqueue.
                # Files in tmp_dir are never modified by the app and are not expected
                # to be modified by the user either -> files are equal if names match.
                return it_pdfdoc, i + 1, False

        if not filename in self.stat_cache:
            try:
                s = os.stat(filename)
                self.stat_cache[filename] = s.st_dev, s.st_ino, s.st_mtime
            except OSError as e:
                print(traceback.format_exc())
                self.app.error_message_dialog(e)
                return None
        for i, it_pdfdoc in enumerate(self.app.pdfqueue):
            if self.stat_cache[filename] == it_pdfdoc.stat:
                # Imported file was found in pdfqueue
                return it_pdfdoc, i + 1, False

        try:
            pdfdoc = PDFDoc(filename, basename, self.stat_cache[filename],
                            self.app.tmp_dir, self.app.window)
            self.app.pdfqueue.append(pdfdoc)
            return pdfdoc, len(self.app.pdfqueue), True
        except _UnknownPasswordException:
            return None
        except PDFDocError as e:
            print(e.message, file=sys.stderr)
            self.app.error_message_dialog(e.message)
            return None

    def get_layerpages(self, layerdata):
        """Create LayerPage objects from layerdata."""
        layerpages = []
        if layerdata is None:
            return layerpages
        for filename, npage, angle, scale, laypos, crop, offset in layerdata:
            doc_data = self.get_pdfdoc(filename)
            if doc_data is None:
                return None
            pdfdoc, nfile, _ = doc_data
            copyname = pdfdoc.copyname
            size = Dims(*pdfdoc.get_page(npage - 1).get_size())
            ld = nfile, npage, copyname, angle, scale, crop, offset, laypos, size
            layerpages.append(LayerPage(*ld))
        return layerpages

    def addpages(self, filename, page=-1, basename=None, angle=0, scale=1.0, crop=Sides(0, 0, 0, 0), layerdata=None):
        c = 'pdf' if page == -1 and os.path.splitext(filename)[1].lower() == '.pdf' else 'other'
        self.content.append(c)
        self.pdfqueue_used = len(self.app.pdfqueue) > 0

        doc_data = self.get_pdfdoc(filename, basename)
        if doc_data is None:
            return
        pdfdoc, nfile, doc_added = doc_data

        if (doc_added and pdfdoc.copyname != pdfdoc.filename and basename is None and not
                (filename.startswith(self.app.tmp_dir) and filename.endswith(".png"))):
            self.app.import_directory = os.path.split(filename)[0]
            self.app.export_directory = self.app.import_directory

        n_end = pdfdoc.document.get_n_pages()
        n_start = min(n_end, max(1, page))
        if page != -1:
            n_end = max(n_start, min(n_end, page))

        layerpages = self.get_layerpages(layerdata)
        if layerpages is None:
            return

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
                    Dims(*page.get_size()),
                    pdfdoc.basename,
                    layerpages,
                )
            )

    def commit(self, select_added, add_to_undomanager):
        if len(self.pages) == 0:
            return False
        if add_to_undomanager:
            self.app.undomanager.commit("Add")
            if self.pdfqueue_used or len(self.content) > 1 or self.content[0] != 'pdf':
                self.app.set_unsaved(True)
            self.content = []
        with self.app.render_lock():
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
        if add_to_undomanager:
            self.app.update_iconview_geometry()
            GObject.idle_add(self.app.retitle)
            self.app.update_max_zoom_level()
            self.app.silent_render()
            self.app.update_statusbar()
            self.scroll()
        self.pages = []
        return True

    def scroll(self):
        """Scroll to first added page."""
        if len(self.app.model) - len(self.pages) == 0:
            return
        if self.treerowref:
            iref = self.treerowref.get_path().get_indices()[0]
        else:
            iref = len(self.app.model) - 1 - len(self.pages)
            self.before = False
        if self.before:
            scroll_path = Gtk.TreePath.new_from_indices([max(iref - len(self.pages), 0)])
        else:
            scroll_path = Gtk.TreePath.new_from_indices([max(iref + 1, 0)])
        self.app.iconview.scroll_to_path(scroll_path, False, 0, 0)


class PDFRenderer(threading.Thread, GObject.GObject):
    def __init__(self, model, pdfqueue, visible_range, columns_nr):
        threading.Thread.__init__(self)
        GObject.GObject.__init__(self)
        self.model = model
        self.pdfqueue = pdfqueue
        self.visible_start = visible_range[0]
        self.visible_end = visible_range[1]
        self.columns_nr = columns_nr
        self.mem_usage = 0
        self.model_lock = threading.Lock()
        self.quit = False

    def run(self):
        """Render thumbnails and less memory consuming previews.

        Thumbnails are rendered for the visible range and its near area. Memory usage is estimated
        and if it goes too high distant thumbnails are replaced with previews. Previews will be
        rendered for all pages.
        """
        for num in range(self.visible_start, self.visible_end + 1):
            if self.quit:
                return
            with self.model_lock:
                if not 0 <= num < len(self.model):
                    break
                path = Gtk.TreePath.new_from_indices([num])
                ref = Gtk.TreeRowReference.new(self.model, path)
                p = self.model[path][0].duplicate()
            if p.resample != 1 / p.zoom:
                self.update(p, ref, p.zoom, False)
        mem_limit = False
        for off in range(1, len(self.model)):
            for num in self.visible_end + off, self.visible_start - off:
                if self.quit:
                    return
                with self.model_lock:
                    if not 0 <= num < len(self.model):
                        continue
                    path = Gtk.TreePath.new_from_indices([num])
                    ref = Gtk.TreeRowReference.new(self.model, path)
                    p = self.model[path][0].duplicate()
                if off <= self.columns_nr * 5:
                    # Thumbnail
                    zoom = p.zoom
                    is_preview = False
                elif mem_limit or p.resample < 0:
                    # Preview. Always render to about 4000 pixels = about 16kb
                    zoom = (1 / p.scale) * (4000 / (p.size[0] * p.size[1])) ** .5
                    is_preview = True
                else:
                    # Thumbnail is distant and total mem usage is small
                    # -> don't update thumbnail, just take memory usage into account
                    zoom = 1 / p.resample
                if p.resample != 1 / zoom:
                    size = self.update(p, ref, zoom, is_preview)
                else:
                    size = p.thumbnail.get_width(), p.thumbnail.get_height()
                mem_limit = self.mem_at_limit(size)
        self.finish()

    def mem_at_limit(self, size):
        """Estimate memory usage of rendered thumbnails. Return True when mem_usage > mem_limit."""
        mem_limit = 300  # Mb (About. Size will depend on thumbnail content.)
        if self.mem_usage > mem_limit:
            return True
        self.mem_usage += size[0] * size[1] * 4 / (1024 * 1024)  # 4 byte/pixel
        return False

    def render(self, cr, p):
        if self.quit:
            return
        pdfdoc = self.pdfqueue[p.nfile - 1]
        page = pdfdoc.get_page(p.npage - 1)
        with pdfdoc.render_lock:
            page.render(cr)

    def update(self, p: Page, ref, zoom, is_preview):
        """Render and emit updated thumbnails."""
        if (is_preview and p.preview) and (p.resample != -1):
            # Reuse the preview if it exist, unless it is marked for re-render
            thumbnail = p.preview
        else:
            wpoi = p.size.width * (1 - p.crop.left - p.crop.right)
            hpoi = p.size.height * (1 - p.crop.top - p.crop.bottom)
            wpix = int(0.5 + wpoi * p.scale * zoom)
            hpix = int(0.5 + hpoi * p.scale * zoom)
            wpix0, hpix0 = (wpix, hpix) if p.angle in [0, 180] else (hpix, wpix)
            rotation = round((int(p.angle) % 360) / 90) * 90

            thumbnail = cairo.ImageSurface(cairo.FORMAT_ARGB32, wpix0, hpix0)
            cr = cairo.Context(thumbnail)
            if rotation > 0:
                cr.translate(wpix0 / 2, hpix0 / 2)
                cr.rotate(-rotation * pi / 180)
                cr.translate(-wpix / 2, -hpix / 2)
            cr.scale(wpix / wpoi, hpix / hpoi)
            cr.translate(-p.crop.left * p.size.width, -p.crop.top * p.size.height)
            self.add_layers(cr, p, layer='UNDERLAY')
            cr.save()
            if rotation > 0:
                cr.translate(*p.size.scaled(0.5))
                cr.rotate(rotation * pi / 180)
                cr.translate(*p.size_orig.scaled(-0.5))
            self.render(cr, p)
            cr.restore()
            self.add_layers(cr, p, layer='OVERLAY')
        if self.quit:
            return 0, 0

        GObject.idle_add(
            self.emit,
            "update_thumbnail",
            ref,
            thumbnail,
            zoom,
            p.scale,
            is_preview,
            priority=GObject.PRIORITY_LOW,
        )
        return thumbnail.get_width(), thumbnail.get_height()

    def add_layers(self, cr, p: Page, layer):
        layerpages = p.layerpages if layer == 'OVERLAY' else reversed(p.layerpages)
        for lp in layerpages:
            if self.quit:
                return
            if layer != lp.laypos:
                continue
            cr.save()
            cr.translate(p.size.width * lp.offset.left, p.size.height * lp.offset.top)
            cr.scale(lp.scale / p.scale, lp.scale / p.scale)
            x = lp.size.width * lp.crop.left
            y = lp.size.height * lp.crop.top
            w = lp.size.width * (1 - lp.crop.left - lp.crop.right)
            h = lp.size.height * (1 - lp.crop.top - lp.crop.bottom)
            cr.translate(-x, -y)
            cr.rectangle(x, y, w, h)
            cr.clip()
            rotation = round((int(lp.angle) % 360) / 90) * 90
            if rotation > 0:
                cr.translate(*lp.size.scaled(0.5))
                cr.rotate(rotation * pi / 180)
                cr.translate(*lp.size_orig.scaled(-0.5))
            self.render(cr, lp)
            cr.restore()

    def finish(self):
        """Signal rendering ended (for statusbar and malloc_trim)."""
        GObject.idle_add(
            self.emit,
            "update_thumbnail",
            None,
            None,
            0,
            0,
            False,
            priority=GObject.PRIORITY_LOW,
        )
