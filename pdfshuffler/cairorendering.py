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

from math import pi as M_PI

class CellRendererImage(gtk.GenericCellRenderer):
    __gproperties__ = {
            "image": (gobject.TYPE_OBJECT, "Image", "Image",
                      gobject.PARAM_READWRITE),
            "width": (gobject.TYPE_DOUBLE, "Width", "Width",
                      0., 1.e4, 0., gobject.PARAM_READWRITE),
            "height": (gobject.TYPE_DOUBLE, "Height", "Height",
                       0., 1.e4, 0., gobject.PARAM_READWRITE),
            "rotation": (gobject.TYPE_INT, "Rotation", "Rotation",
                         0, 360, 0, gobject.PARAM_READWRITE),
            "scale": (gobject.TYPE_DOUBLE, "Scale", "Scale",
                      0.01, 100., 1., gobject.PARAM_READWRITE),
            "cropL": (gobject.TYPE_DOUBLE, "CropL", "CropL",
                      0., 1., 0., gobject.PARAM_READWRITE),
            "cropR": (gobject.TYPE_DOUBLE, "CropR", "CropR",
                      0., 1., 0., gobject.PARAM_READWRITE),
            "cropT": (gobject.TYPE_DOUBLE, "CropT", "CropT",
                      0., 1., 0., gobject.PARAM_READWRITE),
            "cropB": (gobject.TYPE_DOUBLE, "CropB", "CropB",
                      0., 1., 0., gobject.PARAM_READWRITE),
    }

    def __init__(self):
        self.__gobject_init__()
        self.th1 = 2. # border thickness
        self.th2 = 3. # shadow thickness

    def get_geometry(self):

        rotation = int(self.rotation) % 360
        rotation = ((rotation + 45) / 90) * 90
        if not self.image.surface:
            w0 = w1 = self.width
            h0 = h1 = self.height
        else:
            w0 = self.image.surface.get_width()
            h0 = self.image.surface.get_height()
            if rotation == 90 or rotation == 270:
                w1, h1 = h0, w0
            else:
                w1, h1 = w0, h0

        x = self.cropL * w1
        y = self.cropT * h1

        w2 = int(self.scale * (1. - self.cropL - self.cropR) * w1)
        h2 = int(self.scale * (1. - self.cropT - self.cropB) * h1)
        
        return w0,h0,w1,h1,w2,h2,rotation

    def do_set_property(self, pspec, value):
        setattr(self, pspec.name, value)

    def do_get_property(self, pspec):
        return getattr(self, pspec.name)

    def on_render(self, window, widget, background_area, cell_area, \
                 expose_area, flags):
        if not self.image.surface:
            return

        w0,h0,w1,h1,w2,h2,rotation = self.get_geometry()
        th = int(2*self.th1+self.th2)
        w = w2 + th
        h = h2 + th

        x = cell_area.x
        y = cell_area.y
        if cell_area and w > 0 and h > 0:
            x += self.get_property('xalign') * \
                 (cell_area.width - w - self.get_property('xpad'))
            y += self.get_property('yalign') * \
                 (cell_area.height - h - self.get_property('ypad'))

        cr = window.cairo_create()
        cr.translate(x,y)

        x = self.cropL * w1
        y = self.cropT * h1

        #shadow
        cr.set_source_rgb(0.5, 0.5, 0.5)
        cr.rectangle(th, th, w2, h2)
        cr.fill()

        #border
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(0, 0, w2+2*self.th1, h2+2*self.th1)
        cr.fill()

        #image
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(self.th1, self.th1, w2, h2)
        cr.fill_preserve()
        cr.clip()

        cr.translate(self.th1,self.th1)
        cr.scale(self.scale, self.scale)
        cr.translate(-x,-y)
        if rotation > 0:
            cr.translate(w1/2,h1/2)
            cr.rotate(rotation * M_PI / 180)
            cr.translate(-w0/2,-h0/2)

        cr.set_source_surface(self.image.surface)
        cr.paint()

    def on_get_size(self, widget, cell_area=None):
        x = y = 0
        w0,h0,w1,h1,w2,h2,rotation = self.get_geometry()
        th = int(2*self.th1+self.th2)
        w = w2 + th
        h = h2 + th

        if cell_area and w > 0 and h > 0:
            x = self.get_property('xalign') * \
                (cell_area.width - w - self.get_property('xpad'))
            y = self.get_property('yalign') * \
                (cell_area.height - h - self.get_property('ypad'))
        w += 2 * self.get_property('xpad')
        h += 2 * self.get_property('ypad')
        return int(x), int(y), w, h


class CairoImage(gobject.GObject):

    def __init__(self, width=0, height=0):
        gobject.GObject.__init__(self)
        if width > 0 and height > 0:
            self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        else:
            self.surface = None


