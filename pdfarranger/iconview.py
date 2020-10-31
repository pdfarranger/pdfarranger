# Copyright (C) 2008-2017 Konstantinos Poulios, 2018-2019 Jerome Robert
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

from gi.repository import Gtk
from gi.repository import Gdk
from math import pi


class CellRendererImage(Gtk.CellRenderer):
    def __init__(self):
        Gtk.CellRenderer.__init__(self)
        self.th1 = 2.  # border thickness
        self.th2 = 3.  # shadow thickness
        self.page = None

    def set_page(self, page):
        self.page = page

    def get_geometry(self):

        rotation = int(self.page.angle) % 360
        rotation = round(rotation / 90) * 90
        if not self.page.thumbnail:
            s = self.page.size
            r = self.page.resample
            w0 = w1 = s[0] / r
            h0 = h1 = s[1] / r
        else:
            w0 = self.page.thumbnail.get_width()
            h0 = self.page.thumbnail.get_height()
            if rotation == 90 or rotation == 270:
                w1, h1 = h0, w0
            else:
                w1, h1 = w0, h0

        scale = self.page.resample * self.page.zoom
        c = self.page.crop
        w2 = int(0.5 + scale * (1. - c[0] - c[1]) * w1)
        h2 = int(0.5 + scale * (1. - c[2] - c[3]) * h1)

        return w0, h0, w1, h1, w2, h2, rotation

    def do_render(self, window, _widget, _background_area, cell_area, _expose_area):
        if not self.page.thumbnail:
            return

        w0, h0, w1, h1, w2, h2, rotation = self.get_geometry()
        th = int(2 * self.th1 + self.th2)
        w = w2 + th
        h = h2 + th

        x = cell_area.x
        y = cell_area.y
        if cell_area and w > 0 and h > 0:
            x += self.get_property('xalign') * (cell_area.width - w)
            y += self.get_property('yalign') * (cell_area.height - h)

        window.translate(x, y)

        x = self.page.crop[0] * w1
        y = self.page.crop[2] * h1

        # shadow
        window.set_source_rgb(0.5, 0.5, 0.5)
        window.rectangle(th, th, w2, h2)
        window.fill()

        # border
        window.set_source_rgb(0, 0, 0)
        window.rectangle(0, 0, w2 + 2 * self.th1, h2 + 2 * self.th1)
        window.fill()

        # image
        window.set_source_rgb(1, 1, 1)
        window.rectangle(self.th1, self.th1, w2, h2)
        window.fill_preserve()
        window.clip()

        window.translate(self.th1, self.th1)
        scale = self.page.resample * self.page.zoom
        window.scale(scale, scale)
        window.translate(-x, -y)
        if rotation > 0:
            window.translate(w1 / 2, h1 / 2)
            window.rotate(rotation * pi / 180)
            window.translate(-w0 / 2, -h0 / 2)

        window.set_source_surface(self.page.thumbnail)
        window.paint()

    def do_get_size(self, _widget, cell_area=None):
        x = y = 0
        _w0, _h0, _w1, _h1, w2, h2, _rotation = self.get_geometry()
        th = int(2 * self.th1 + self.th2)
        w = w2 + th
        h = h2 + th

        if cell_area and w > 0 and h > 0:
            x = self.get_property('xalign') * (
                    cell_area.width - w - self.get_property('xpad'))
            y = self.get_property('yalign') * (
                    cell_area.height - h - self.get_property('ypad'))
        w += 2 * self.get_property('xpad')
        h += 2 * self.get_property('ypad')
        return int(x), int(y), w, h


class IconviewCursor(object):
    """Move cursor, select pages and scroll with navigation keys."""
    def __init__(self, app):
        self.app = app
        self.model = self.app.iconview.get_model()
        self.move_cursor = True
        self.event = None
        self.iconview = None
        self.sel_start_page = None
        self.cursor_page_nr = 0
        self.cursor_page_nr_new = 0
        self.cursor_is_visible = False

    def handler(self, iconview, event):
        """Do all steps involved in cursor moving."""
        self.iconview = iconview
        self.event = event
        self.set_initial()
        self.set_selection_start_page()
        self.move()
        self.select()
        self.scroll_iconview()

    def set_initial(self):
        """Cursor initial set."""
        self.move_cursor = True
        selection = self.iconview.get_selected_items()
        if len(selection) == 0:
            self.cursor_is_visible = False
        if selection and not self.iconview.get_cursor()[1] in selection:
            selection.sort(key=lambda x: x.get_indices()[0])
            self.iconview.set_cursor(selection[-1], None, False)
            if self.event.state & Gdk.ModifierType.SHIFT_MASK:
                self.sel_start_page = Gtk.TreePath.get_indices(selection[-1])[0]
                self.iconview.unselect_all()
        elif not self.iconview.get_cursor()[0]:
            if self.event.keyval == Gdk.KEY_End:
                self.cursor_page_nr_new = len(self.model) - 1
            else:
                self.cursor_page_nr_new = 0
            cursor_path_new = Gtk.TreePath.new_from_indices([self.cursor_page_nr_new])
            self.iconview.set_cursor(cursor_path_new, None, False)
            self.move_cursor = False
            self.iconview.unselect_all()

    def set_selection_start_page(self):
        """Set selection start page when shift + navigation keys are used."""
        if self.sel_start_page is None and self.event.state & Gdk.ModifierType.SHIFT_MASK:
            self.sel_start_page = Gtk.TreePath.get_indices(self.iconview.get_cursor()[1])[0]
            self.iconview.unselect_all()
        elif not self.event.state & Gdk.ModifierType.SHIFT_MASK:
            self.sel_start_page = None

    def move(self):
        """Move iconview cursor with navigation keys."""
        columns_nr = self.iconview.get_columns()
        if self.move_cursor:
            cursor_path = self.iconview.get_cursor()[1]
            self.cursor_page_nr = Gtk.TreePath.get_indices(cursor_path)[0]
            if self.event.keyval == Gdk.KEY_Up:
                step = 0 if self.cursor_page_nr - columns_nr < 0 else columns_nr
                self.cursor_page_nr_new = self.cursor_page_nr - step
            elif self.event.keyval == Gdk.KEY_Down:
                step = 0 if self.cursor_page_nr + columns_nr > len(self.model) - 1 else columns_nr
                self.cursor_page_nr_new = self.cursor_page_nr + step
            elif self.event.keyval == Gdk.KEY_Left:
                self.cursor_page_nr_new = max(self.cursor_page_nr - 1, 0)
            elif self.event.keyval == Gdk.KEY_Right:
                self.cursor_page_nr_new = min(self.cursor_page_nr + 1, len(self.model) - 1)
            elif self.event.keyval == Gdk.KEY_Home:
                self.cursor_page_nr_new = 0
            elif self.event.keyval == Gdk.KEY_End:
                self.cursor_page_nr_new = len(self.model) - 1
            cursor_path = Gtk.TreePath.new_from_indices([self.cursor_page_nr])
            self.iconview.unselect_path(cursor_path)
            if not self.cursor_is_visible:
                self.iconview.emit('move-cursor', Gtk.MovementStep.DISPLAY_LINES, 0)
                self.cursor_is_visible = True
                self.iconview.unselect_all()
            cursor_path_new = Gtk.TreePath.new_from_indices([self.cursor_page_nr_new])
            self.iconview.set_cursor(cursor_path_new, None, False)

    def select(self):
        """Select iconview pages with shift + navigation keys."""
        if self.event.state & Gdk.ModifierType.SHIFT_MASK:
            if self.cursor_page_nr_new > self.sel_start_page > self.cursor_page_nr:
                for page_nr in range(self.cursor_page_nr, self.sel_start_page):
                    path = Gtk.TreePath.new_from_indices([page_nr])
                    self.iconview.unselect_path(path)
            elif self.cursor_page_nr_new < self.sel_start_page < self.cursor_page_nr:
                for page_nr in range(self.sel_start_page, self.cursor_page_nr):
                    path = Gtk.TreePath.new_from_indices([page_nr])
                    self.iconview.unselect_path(path)
            elif self.cursor_page_nr_new == self.sel_start_page:
                self.iconview.unselect_all()
            step = -1 if self.cursor_page_nr_new < self.sel_start_page else 1
            for page_nr in range(self.cursor_page_nr_new, self.cursor_page_nr + step, step):
                path = Gtk.TreePath.new_from_indices([page_nr])
                self.iconview.unselect_path(path)
            for page_nr in range(self.sel_start_page, self.cursor_page_nr_new + step, step):
                path = Gtk.TreePath.new_from_indices([page_nr])
                self.iconview.select_path(path)
        else:
            self.iconview.unselect_all()
            cursor_path_new = Gtk.TreePath.new_from_indices([self.cursor_page_nr_new])
            self.iconview.select_path(cursor_path_new)

    def scroll_iconview(self):
        """Scroll in order to keep cursor visible in window."""
        sw_vadj = self.app.sw.get_vadjustment()
        sw_vpos = sw_vadj.get_value()
        cursor_path_new = Gtk.TreePath.new_from_indices([self.cursor_page_nr_new])
        cell_height = self.iconview.get_cell_rect(cursor_path_new)[1].height
        cell_y = self.iconview.get_cell_rect(cursor_path_new)[1].y
        sw_height = self.app.sw.get_allocated_height()
        sw_vpos = min(sw_vpos, cell_y + self.app.vp_css_margin - 6)
        sw_vpos = max(sw_vpos, cell_y + self.app.vp_css_margin + 6 - sw_height + cell_height)
        sw_vadj.set_value(sw_vpos)
