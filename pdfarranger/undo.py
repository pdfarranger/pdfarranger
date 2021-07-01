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

    def commit(self, label):
        """
        Must be called *BEFORE* each undoable actions
        :param label: label of the action
        """
        self.states = self.states[:self.current]
        self.states.append(([row[0].duplicate(False) for row in self.model], self.label,))
        self.current += 1
        self.label = label
        self.__refresh()

    def undo(self, _action, _param, _unused):
        if self.current == len(self.states):
            self.states.append(([row[0].duplicate(False) for row in self.model], self.label,))
        state, self.label = self.states[self.current - 1]
        self.__set_state(state)
        self.current -= 1
        self.__refresh()

    def redo(self, _action, _param, _unused):
        state, self.label = self.states[self.current + 1]
        self.__set_state(state)
        self.current += 1
        self.__refresh()

    def set_actions(self, undo, redo):
        self.undoaction = undo
        self.redoaction = redo
        self.__refresh()

    def __set_state(self, state):
        self.app.quit_rendering()
        self.app.model_lock()
        self.model.clear()
        for page in state:
            # Do not reset the zoom level
            page.zoom = self.app.zoom_scale
            self.model.append([page, page.description()])
        self.app.model_unlock()
        self.app.zoom_set(self.app.zoom_level)
        self.app.silent_render()

    def __refresh(self):
        if self.undoaction:
            self.undoaction.set_enabled(self.current >= 1)
        if self.redoaction:
            self.redoaction.set_enabled(self.current + 1 < len(self.states))
        # TODO: This is where to update the undo/redo menu items label to
        # show which action is going to be undone/redone. Because GtkImageMenuItem
        # will leads to many changes in translations this is currently postponed.
