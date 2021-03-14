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
        w0 = self.page.thumbnail.get_width()
        h0 = self.page.thumbnail.get_height()
        if rotation == 90 or rotation == 270:
            w1, h1 = h0, w0
        else:
            w1, h1 = w0, h0
        w2 = self.page.width_in_pixel()
        h2 = self.page.height_in_pixel()

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
        window.translate(int(0.5 + x), int(0.5 + y))

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
        x = int(self.page.crop[0] * w1)
        y = int(self.page.crop[2] * h1)
        window.translate(-x, -y)
        if rotation > 0:
            window.translate(w1 / 2, h1 / 2)
            window.rotate(rotation * pi / 180)
            window.translate(-w0 / 2, -h0 / 2)

        window.set_source_surface(self.page.thumbnail)
        window.paint()

    def do_get_size(self, _widget, cell_area=None):
        x = y = 0
        th = int(2 * self.th1 + self.th2)
        w = self.page.width_in_pixel() + th
        h = self.page.height_in_pixel() + th

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


class IconviewDragSelect:
    """
    Drag-select when clicking between items and dragging mouse pointer.

    Click + drag-select selects the range from click location to drag location.
    Shift + click + drag-select adds more items to selection.
    Control + click + drag-select toggles selection.
    """
    def __init__(self, app):
        self.app = app
        self.iconview = app.iconview
        self.model = app.iconview.get_model()
        self.range_start = 0
        self.range_end = 0
        self.click_location = None
        self.cursor_name_old = 'default'

    def click(self, event):
        """Store the click location."""
        if len(self.model) == 0:
            return
        self.last_cell = self.iconview.get_cell_rect(self.model[-1].path)[1]
        self.click_location = self.get_location(event)
        if self.click_location:
            self.set_mouse_cursor('text')
            self.range_start = int(self.click_location + 0.5)
            self.range_end = self.range_start
            self.control_is_pressed = event.state & Gdk.ModifierType.CONTROL_MASK
            self.shift_is_pressed = event.state & Gdk.ModifierType.SHIFT_MASK
            if self.control_is_pressed or self.shift_is_pressed:
                self.selection_list = []
                for row in self.model:
                    self.selection_list.append(self.iconview.path_is_selected(row.path))

    def motion(self, event):
        """Get drag location and select or deselect items."""
        if not self.click_location:
            return
        drag_location = self.get_location(event)
        if drag_location is None:
            return
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            self.control_is_pressed = False
        if not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.shift_is_pressed = False
        selection_changed = self.select(drag_location)
        return selection_changed

    def select(self, drag_location):
        """Select or deselect items between click location and current mouse pointer location."""
        range_start_old = self.range_start
        range_end_old = self.range_end
        if drag_location > self.click_location:
            self.range_start = int(self.click_location + 0.5)
            self.range_end = int(drag_location + 1)
        else:
            self.range_start = int(drag_location + 0.5)
            self.range_end = int(self.click_location + 1)
        if self.range_start == range_start_old and self.range_end == range_end_old:
            return
        changed_range_start = min(self.range_start, range_start_old)
        changed_range_end = max(self.range_end, range_end_old)
        for page_nr in range(changed_range_start, changed_range_end):
            path = Gtk.TreePath.new_from_indices([page_nr])
            if self.control_is_pressed:
                if page_nr in range(self.range_start, self.range_end):
                    if self.selection_list[page_nr]:
                        self.iconview.unselect_path(path)
                    else:
                        self.iconview.select_path(path)
                else:
                    if self.selection_list[page_nr]:
                        self.iconview.select_path(path)
                    else:
                        self.iconview.unselect_path(path)
            elif self.shift_is_pressed:
                if page_nr in range(self.range_start, self.range_end):
                    self.iconview.select_path(path)
                elif not self.selection_list[page_nr]:
                    self.iconview.unselect_path(path)
            else:
                if page_nr in range(self.range_start, self.range_end):
                    self.iconview.select_path(path)
                else:
                    self.iconview.unselect_path(path)
        return True

    def get_location(self, event):
        """
        Get mouse pointer location.

        E.g. Location is 2.0 when pointer is on item 2.
             Location is 2.5 when pointer is between item 2 and 3.
        """
        location = None
        search_positions = [(event.x, event.y, 0),
                            (event.x + self.last_cell.width / 2, event.y, -0.5),
                            (event.x - self.last_cell.width / 2, event.y, 0.5)]
        for x_s, y_s, offset in search_positions:
            path = self.iconview.get_path_at_pos(x_s, y_s)
            if path:
                location = Gtk.TreePath.get_indices(path)[0] + offset
                return location
        if (event.y > self.last_cell.y + self.last_cell.height) or (
            event.y > self.last_cell.y and event.x > self.last_cell.x + self.last_cell.width):
            location = len(self.model) - 0.5
        elif event.y < self.app.vp_css_margin * -1:
            location = -0.5
        return location

    def set_mouse_cursor(self, cursor_name):
        """Set the cursor type specified by cursor_name."""
        if cursor_name == self.cursor_name_old:
            return
        cursor = Gdk.Cursor.new_from_name(Gdk.Display.get_default(), cursor_name)
        self.iconview.get_window().set_cursor(cursor)
        self.cursor_name_old = cursor_name
