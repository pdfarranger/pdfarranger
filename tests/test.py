import os
import subprocess
import sys
import unittest
import time
import tempfile
import shutil

"""
Thoses tests are using Dogtail https://gitlab.com/dogtail/dogtail

Other tools using dogtail where you can get example on how to use it:

* https://gitlab.gnome.org/GNOME/gnome-boxes
* https://gitlab.gnome.org/GNOME/gnome-software
* https://gitlab.gnome.org/GNOME/gnome-characters
* https://gitlab.gnome.org/GNOME/eog
* https://github.com/kirienko/gourmet
* https://github.com/virt-manager/virt-manager
* https://gitlab.gnome.org/GNOME/gnome-weather/
* http://threedepict.sourceforge.net/
* https://salsa.debian.org/pkg-privacy-team/onioncircuits/-/tree/master/debian/tests

Example of Dogtail using a filechooser:

filechooser = app.child(roleName='file chooser')
treeview = filechooser.child(roleName='table', name='Files')
treeview.keyCombo('<ctrl>L')
treeview.typeText('qpdf-manual.pdf')
filechooser.button('Open').click()

You may need to run the following commands to run thoses tests in your current session instead of Xvfb:

* /usr/libexec/at-spi-bus-launcher --launch-immediately
* setxkbmap -v fr
* gsettings set org.gnome.desktop.interface toolkit-accessibility true

Tests need to be run with default window size (i.e rm ~/.config/pdfarranger/config.ini)

Some tips:

* Use to print widget tree (names and roles) self._app().dump()
"""


def group(title):
    if "GITHUB_ACTIONS" in os.environ:
        print("::group::" + title)


def endgroup():
    if "GITHUB_ACTIONS" in os.environ:
        print("::endgroup::")


class XvfbManager:
    """Base class for running offscreen tests"""

    def __init__(self, display=":99"):
        self.display = display
        env = os.environ.copy()
        env["DISPLAY"] = display
        self.xvfb_proc = None
        self.dbus_proc = None
        self.xvfb_proc = subprocess.Popen(["Xvfb", self.display])
        cmd = ["dbus-daemon", "--print-address=1", "--session"]
        self.dbus_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, text=True, env=env
        )
        self.dbus_addr = self.dbus_proc.stdout.readline().strip()
        self.dbus_proc.stdout.close()
        os.environ["DISPLAY"] = display
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = self.dbus_addr

    def kill(self):
        self.dbus_proc.kill()
        self.dbus_proc.wait()
        self.xvfb_proc.kill()
        self.xvfb_proc.wait()


class DogtailManager:
    def __init__(self):
        self.xvfb = None
        if "DISPLAY" not in os.environ:
            self.xvfb = XvfbManager()
        os.environ["LC_MESSAGES"] = "C"
        os.environ["GTK_MODULES"] = "gail:atk-bridge"
        cmd = "gsettings set org.gnome.desktop.interface toolkit-accessibility true"
        subprocess.check_call(cmd.split())
        # dogtail must be imported after setting DBUS_SESSION_BUS_ADDRESS
        from dogtail.config import config
        config.debugSleep = False
        # long duration at startup
        config.searchBackoffDuration = 1
        config.actionDelay = 0.01
        config.runInterval = 0.01
        config.defaultDelay = 0.1
        config.debugSearching = False
        config.searchCutoffCount = 30
        config.runTimeout = 1
        config.searchShowingOnly = True
        config.typingDelay = 0.05

    def kill(self):
        if self.xvfb is not None:
            self.xvfb.kill()


# dogtail does not support change of X11 server so it must be a singleton
dogtail_manager = DogtailManager()


class PdfArrangerManager:
    def __init__(self, args=None, coverage=True):
        self.process = None
        args = [] if args is None else args
        cmd = [sys.executable, "-u", "-X", "tracemalloc"]
        if coverage:
            cmd = cmd + ["-m", "coverage", "run", "-a"]
        self.process = subprocess.Popen(cmd + ["-m", "pdfarranger"] + args)

    def kill(self):
        self.process.kill()
        self.process.wait()

class PdfArrangerTest(unittest.TestCase):
    LAST=False
    def _app(self):
        # Cannot import at top level because of DBUS_SESSION_BUS_ADDRESS
        from dogtail.tree import root
        a = root.application("__main__.py")
        self.assertFalse(a.dead)
        return a

    def _mainmenu(self, action):
        mainmenu = self._app().child(roleName="toggle button", name="Menu")
        self._wait_cond(lambda: mainmenu.sensitive)
        mainmenu.click()
        if not isinstance(action, str):
            for submenu in action[:-1]:
                mainmenu.menu(submenu).point()
            action = action[-1]
        mainmenu.menuItem(action).click()

    def _wait_cond(self, cond):
        c = 0
        while not cond():
            time.sleep(0.1)
            self.assertLess(c, 30)
            c += 1

    def _assert_selected(self, selection):
        app = self._app()
        statusbar = app.child(roleName="status bar")
        self.assertEqual(statusbar.name, "Selected pages: " + selection)

    def _icons(self):
        """Return the list of page icons"""
        from dogtail import predicate
        viewport = self._app().child(roleName="viewport")
        return viewport.findChildren(predicate.GenericPredicate(roleName="icon"), showingOnly=False)

    def _popupmenu(self, page, action):
        """Run an action on a give page using the popup menu"""
        self._icons()[page].click(button=3)
        popupmenu = self._app().child(roleName="window")
        if not isinstance(action, str):
            for submenu in action[:-1]:
                popupmenu.menu(submenu).point()
            action = action[-1]
        button = popupmenu.menuItem(action)
        self._wait_cond(lambda: button.sensitive)
        button.click()

    def _process(self):
        return self.__class__.pdfarranger.process

    def _import_file(self, filename):
        """Try to import a file with a file chooser and return that file chooser object"""
        self._mainmenu("Import")
        filechooser = self._app().child(roleName='file chooser')
        treeview = filechooser.child(roleName="table", name="Files")
        treeview.keyCombo("<ctrl>L")
        treeview.typeText(os.path.abspath(filename))
        ob = filechooser.button("Open")
        self._wait_cond(lambda: ob.sensitive)
        ob.click()
        return filechooser

    @classmethod
    def setUpClass(cls):
        cls.pdfarranger = None
        cls.tmp = tempfile.mkdtemp()

    def setUp(self):
        group("Running " + self.id())

    def tearDown(self):
        endgroup()

    @classmethod
    def tearDownClass(cls):
        if cls.pdfarranger:
            cls.pdfarranger.kill()
        if cls.tmp:
            shutil.rmtree(cls.tmp)
        if cls.LAST:
            dogtail_manager.kill()


class TestBatch1(PdfArrangerTest):
    def test_01_import_img(self):
        self.__class__.pdfarranger = PdfArrangerManager(["data/screenshot.png"])
        # check that process is actually running
        self.assertIsNone(self._process().poll())
        self._app()
        from dogtail.config import config
        # Now let's go faster
        config.searchBackoffDuration = 0.1

    def test_02_properties(self):
        self._mainmenu("Edit Properties")
        dialog = self._app().child(roleName="dialog")
        creatorlab = dialog.child(roleName="table cell", name="Creator")
        creatorid = creatorlab.parent.children.index(creatorlab) + 1
        creatorval = creatorlab.parent.children[creatorid]
        creatorval.keyCombo("enter")
        from dogtail import rawinput
        rawinput.typeText('["Frodo", "Sam"]')
        dialog.child(name="OK").click()
        self._mainmenu("Edit Properties")
        dialog = self._app().child(roleName="dialog")
        rawinput.keyCombo("enter")
        rawinput.typeText('Memories')
        rawinput.keyCombo("enter")
        dialog.child(name="OK").click()

    def test_03_zoom(self):
        app = self._app()
        zoomoutb = app.child(roleName="push button", description="Zoom Out")
        zoominb = app.child(roleName="push button", description="Zoom In")
        # maximum dezoom whatever the initial zoom level
        for _ in range(10):
            zoomoutb.click()
        for _ in range(3):
            zoominb.click()

    def test_04_rotate_undo(self):
        app = self._app()
        self._assert_selected("")
        app.keyCombo("<ctrl>a")  # select all
        self._assert_selected("1")
        app.keyCombo("<ctrl>Left")  # rotate left
        app.keyCombo("<ctrl>z")  # undo
        app.keyCombo("<ctrl>y")  # redo
        app.keyCombo("<ctrl>a")
        app.keyCombo("<ctrl>Right")  # rotate right
        app.keyCombo("<ctrl>Right")  # rotate right

    def test_05_duplicate(self):
        self._popupmenu(0, "Duplicate")
        app = self._app()
        self.assertEqual(len(self._icons()), 2)
        app.keyCombo("<ctrl>a")
        app.keyCombo("<ctrl>c")
        for __ in range(3):
            app.keyCombo("<ctrl>v")
        self.assertEqual(len(self._icons()), 8)
        app.keyCombo("Right")
        app.keyCombo("Left")
        app.keyCombo("Down")
        self._assert_selected("5")
        app.keyCombo("Up")
        self._assert_selected("2")

    def test_06_page_format(self):
        self._popupmenu(0, ["Select", "Select Odd Pages"])
        self._assert_selected("1, 3, 5, 7")
        self._popupmenu(0, "Page Format")
        dialog = self._app().child(roleName="dialog")
        croppanel = dialog.child(name="Crop Margins")
        from dogtail import predicate
        cropbuttons = croppanel.findChildren(predicate.GenericPredicate(roleName="spin button"))
        for i in range(4):
            cropbuttons[i].click()
            cropbuttons[i].text = str((i+1)*4)
        scalebutton = dialog.child(roleName="spin button")
        scalebutton.click()
        scalebutton.text = "120"
        dialog.child(name="OK").click()
        # TODO: find the condition which could replace this ugly sleep
        time.sleep(0.5)
        self._wait_cond(lambda: dialog.dead)

    def test_07_split_page(self):
        lp = self._app().child(roleName="layered pane")
        lp.grabFocus()
        lbefore = len(self._icons())
        self._popupmenu(0, ["Select", "Select Even Pages"])
        self._assert_selected("2, 4, 6, 8")
        self._mainmenu(["Edit", "Split Pages"])
        dialog = self._app().child(roleName="dialog")
        dialog.child(name="OK").click()
        self._wait_cond(lambda: dialog.dead)
        self.assertEqual(len(self._icons()), lbefore + 4)

    def test_08_zoom_pages(self):
        self._app().child(roleName="layered pane").keyCombo("Home")
        self._assert_selected("1")
        self._app().keyCombo("f")

    def test_09_save_as(self):
        self._mainmenu("Save")
        filechooser = self._app().child(roleName="file chooser")
        tmp = self.__class__.tmp
        filename = os.path.join(tmp, "foobar.pdf")
        filechooser.child(roleName="text").text = filename
        saveb = filechooser.button("Save")
        self._wait_cond(lambda: saveb.sensitive)
        filechooser.button("Save").click()
        self._wait_cond(lambda: os.path.isfile(filename))

    def test_10_reverse(self):
        self._popupmenu(0, ["Select", "Same Page Format"])
        self._assert_selected("1, 4, 7, 10")
        self._popupmenu(0, ["Select", "All From Same File"])
        self._assert_selected("1-12")
        self._popupmenu(0, "Reverse Order")

    def test_11_quit(self):
        self._mainmenu("Quit")
        dialog = self._app().child(roleName="alert")
        dialog.child(name="Cancel").click()
        self._app().keyCombo("<ctrl>s")
        self._app().keyCombo("<ctrl>q")
        # check that process actually exit
        self._process().wait(timeout=22)


class TestBatch2(PdfArrangerTest):
    def test_01_open_empty(self):
        from dogtail.config import config
        config.searchBackoffDuration = 1
        self.__class__.pdfarranger = PdfArrangerManager()
        # check that process is actually running
        self.assertIsNone(self._process().poll())
        self._app()
        # Now let's go faster
        config.searchBackoffDuration = 0.1

    def test_02_import(self):
        filechooser = self._import_file("tests/test.pdf")
        self._wait_cond(lambda: filechooser.dead)
        self.assertEqual(len(self._icons()), 2)

    def test_03_cropborder(self):
        self._popupmenu(0, "Crop White Borders")

    def test_04_export(self):
        self._mainmenu(["Export", "Export All Pages to Individual Files…"])
        filechooser = self._app().child(roleName="file chooser")
        tmp = self.__class__.tmp
        filename = os.path.join(tmp, "alltosingle.pdf")
        filename2 = os.path.join(tmp, "alltosingle2.pdf")
        filechooser.child(roleName="text").text = filename
        saveb = filechooser.button("Save")
        self._wait_cond(lambda: saveb.sensitive)
        filechooser.button("Save").click()
        self._wait_cond(lambda: os.path.isfile(filename) and os.path.isfile(filename2))

    def test_05_clear(self):
        self._popupmenu(1, "Delete")
        self.assertEqual(len(self._icons()), 1)

    def test_06_about(self):
        self._mainmenu("About")
        dialog = self._app().child(roleName="dialog")
        dialog.child(name="Close").click()
        self._wait_cond(lambda: dialog.dead)

    def test_07_quit(self):
        self._app().child(roleName="layered pane").keyCombo("<ctrl>q")
        dialog = self._app().child(roleName="alert")
        dialog.child(name="Don’t Save").click()
        # check that process actually exit
        self._process().wait(timeout=22)


class TestBatch3(PdfArrangerTest):
    # Kill X11 after that batch
    LAST=True
    def test_01_open_encrypted(self):
        from dogtail.config import config
        config.searchBackoffDuration = 1
        filename = os.path.join(self.__class__.tmp, "other_encrypted.pdf")
        shutil.copyfile("tests/test_encrypted.pdf", filename)
        self.__class__.pdfarranger = PdfArrangerManager([filename])
        # check that process is actually running
        self.assertIsNone(self._process().poll())
        app = self._app()
        # Now let's go faster
        config.searchBackoffDuration = 0.1
        dialog = app.child(roleName="dialog")
        passfield = dialog.child(roleName="password text")
        passfield.text = "foobar"
        dialog.child(name="OK").click()
        self._wait_cond(lambda: dialog.dead)

    def test_02_import_wrong_pass(self):
        filechooser = self._import_file("tests/test_encrypted.pdf")
        dialog = self._app().child(roleName="dialog")
        passfield = dialog.child(roleName="password text")
        passfield.text = "wrong"
        dialog.child(name="OK").click()
        dialog = self._app().child(roleName="dialog")
        passfield = dialog.child(roleName="password text")
        dialog.child(name="Cancel").click()
        self._wait_cond(lambda: dialog.dead)
        self._wait_cond(lambda: filechooser.dead)
        self.assertEqual(len(self._icons()), 2)

    def test_03_quit(self):
        self._app().child(roleName="layered pane").keyCombo("<ctrl>q")
        dialog = self._app().child(roleName="alert")
        dialog.child(name="Save").click()
        filechooser = self._app().child(roleName="file chooser")
        filechooser.button("Save").click()
        dialog = self._app().child(roleName="alert")
        dialog.child(name="Replace").click()
        # check that process actually exit
        self._process().wait(timeout=22)
