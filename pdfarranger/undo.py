# Copyright (C) 2018-2019 Jerome Robert
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

"""
undo/redo implemented with the memento design pattern.

The memento pattern is simpler than the command pattern.
Here the memory cost of memento is affordable because we
only store snapshots of the GtkListStore object, not of
the whole PDF files.
"""

from gi.repository import GObject
from dataclasses import dataclass
from .core import Page


@dataclass
class State:
    label: str
    pages: list[Page]
    selection: list[int]
    vadj_percent: float


class Manager(object):
    """
    Stack of GtkListStore models (Memento design pattern)
    """

    def __init__(self, app):
        self.app = app
        self.model = app.model
        self.states = []
        #: label of the previous undoable action
        self.label = None
        #: id of the current state
        self.current = 0
        self.undoaction = None
        self.redoaction = None

    def clear(self):
        self.states = []
        self.label = None
        self.current = 0

    def commit(self, label):
        """
        Must be called *BEFORE* each undoable actions
        :param label: label of the action
        """
        self.states = self.states[:self.current]
        self.states.append(self.get_state())
        self.current += 1
        self.label = label
        self.__refresh()

    def get_state(self):
        """
        Get the content which should be saved:

        1. The label of the action
        2. The pages
        3. Which page numbers are selected
        4. The vertical adjustment percent value
        """
        pages = [row[0].duplicate(False) for row in self.model]
        s = self.app.iconview.get_selected_items()
        selection = [path.get_indices()[0] for path in s]
        vadj_percent = self.app.vadj_percent_handler()
        return State(self.label, pages, selection, vadj_percent)

    def undo(self, _action, _param, _unused):
        if self.current == len(self.states):
            self.states.append(self.get_state())
        self.__set_state(self.states[self.current - 1])
        self.current -= 1
        self.app.set_unsaved(True)
        self.__refresh()

    def redo(self, _action, _param, _unused):
        self.__set_state(self.states[self.current + 1])
        self.current += 1
        self.app.set_unsaved(True)
        self.__refresh()

    def set_actions(self, undo, redo):
        self.undoaction = undo
        self.redoaction = redo
        self.__refresh()

    def __set_state(self, state):
        self.app.quit_rendering()
        self.app.iconview.unselect_all()
        with self.app.render_lock():
            self.model.clear()
            for page in state.pages:
                # Do not reset the zoom level
                page.zoom = self.app.zoom_scale
                page.resample = -1
                self.model.append([page, page.description])
        for num in state.selection:
            self.app.iconview.select_path(self.model[num].path)
        self.app.vadj_percent = state.vadj_percent
        self.app.update_iconview_geometry()
        self.app.update_max_zoom_level()
        self.app.retitle()
        self.app.iv_selection_changed()
        self.app.silent_render()

    def __refresh(self):
        if self.undoaction:
            self.undoaction.set_enabled(self.current >= 1)
        if self.redoaction:
            self.redoaction.set_enabled(self.current + 1 < len(self.states))
        # TODO: This is where to update the undo/redo menu items label to
        # show which action is going to be undone/redone. Because GtkImageMenuItem
        # will leads to many changes in translations this is currently postponed.
