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
from gi.repository import GObject
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
