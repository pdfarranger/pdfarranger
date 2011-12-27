#!/usr/bin/python
# -*- coding: utf-8 -*-

"""

 PdfShuffler 0.6.0 - GTK+ based utility for splitting, rearrangement and
 modification of PDF documents.
 Copyright (C) 2008-2011 Konstantinos Poulios
 <https://sourceforge.net/projects/pdfshuffler>

 This file is part of PdfShuffler.

 PdfShuffler is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; either version 3 of the License, or
 (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License along
 with this program; if not, write to the Free Software Foundation, Inc.,
 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""

import gtk
import gobject
import cairo

class CellRendererImage(gtk.GenericCellRenderer):
    __gproperties__ = {
            "image": (gobject.TYPE_OBJECT, "Image",
                     "Image", gobject.PARAM_READWRITE),
    }

    def __init__(self):
        self.__gobject_init__()
        self.page = None

    def do_set_property(self, pspec, value):
        setattr(self, pspec.name, value)

    def do_get_property(self, pspec):
        return getattr(self, pspec.name)

    def on_render(self, window, widget, background_area, cell_area, \
                 expose_area, flags):
        if not self.image:
            return

        x = cell_area.x
        y = cell_area.y
        w = self.image.surface.get_width()
        h = self.image.surface.get_height()
        if cell_area and w > 0 and h > 0:
            x += self.get_property('xalign') * \
                 (cell_area.width - w - self.get_property('xpad'))
            y += self.get_property('yalign') * \
                 (cell_area.height - h - self.get_property('ypad'))

        pix_rect = gtk.gdk.Rectangle()
        pix_rect.x = x
        pix_rect.y = y
        pix_rect.width = w
        pix_rect.height = h

        draw_rect = cell_area.intersect(pix_rect)

        cr = window.cairo_create()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(draw_rect.x, draw_rect.y, draw_rect.width, draw_rect.height)
        cr.fill()
        cr.set_source_surface(self.image.surface, draw_rect.x, draw_rect.y)
        cr.paint()

    def on_get_size(self, widget, cell_area=None):
        if not self.image:
            return 0, 0, 0, 0

        x = y = 0
        w = self.image.surface.get_width()
        h = self.image.surface.get_height()
        if cell_area and w > 0 and h > 0:
            x = self.get_property('xalign') * \
                (cell_area.width - w - self.get_property('xpad'))
            y = self.get_property('yalign') * \
                (cell_area.height - h - self.get_property('ypad'))
        w += 2 * self.get_property('xpad')
        h += 2 * self.get_property('ypad')
        return int(x), int(y), w, h


class CairoImage(gobject.GObject):

    def __init__(self, format, width, height):
        gobject.GObject.__init__(self)
        self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        self.context = cairo.Context(self.surface)


