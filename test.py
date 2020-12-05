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

    def kill(self):
        if self.xvfb is not None:
            self.xvfb.kill()


class PdfArrangerManager:
    def __init__(self, args=None, coverage=True):
        self.dogtail = DogtailManager()
        self.process = None
        args = [] if args is None else args
        cmd = [sys.executable, "-u", "-X", "tracemalloc"]
        if coverage:
            cmd = cmd + ["-m", "coverage", "run"]
        self.process = subprocess.Popen(cmd + ["-m", "pdfarranger"] + args)

    def kill(self):
        self.process.kill()
        self.process.wait()
        self.dogtail.kill()


class PdfArrangerTest(unittest.TestCase):
    @staticmethod
    def app():
        # Cannot import at top level because of DBUS_SESSION_BUS_ADDRESS
        from dogtail.tree import root
        return root.application("__main__.py")

    def __mainmenu(self, action):
        mainmenu = self.app().child(roleName="toggle button", name="Menu")
        self.__wait_cond(lambda: mainmenu.sensitive)
        mainmenu.click()
        if not isinstance(action, str):
            for submenu in action[:-1]:
                mainmenu.menu(submenu).point()
            action = action[-1]
        mainmenu.menuItem(action).click()

    def __wait_cond(self, cond):
        c = 0
        while not cond():
            time.sleep(0.1)
            self.assertLess(c, 30)
            c += 1

    def __assert_selected(self, selection):
        app = self.app()
        statusbar = app.child(roleName="status bar")
        self.assertEqual(statusbar.name, "Selected pages: " + selection)

    def __icons(self):
        """Return the list of page icons"""
        from dogtail import predicate
        viewport = self.app().child(roleName="viewport")
        return viewport.findChildren(predicate.GenericPredicate(roleName="icon"), showingOnly=False)

    def __popupmenu(self, page, action):
        """Run an action on a give page using the popup menu"""
        self.__icons()[page].click(button=3)
        popupmenu = self.app().child(roleName="window")
        if not isinstance(action, str):
            for submenu in action[:-1]:
                popupmenu.menu(submenu).point()
            action = action[-1]
        button = popupmenu.menuItem(action)
        self.__wait_cond(lambda: button.sensitive)
        button.click()

    @classmethod
    def setUpClass(cls):
        cls.pdfarranger = None
        cls.tmp = tempfile.mkdtemp()

    def setUp(self):
        group("Running " + self.id())

    def process(self):
        return self.__class__.pdfarranger.process

    def test_01_import_img(self):
        self.__class__.pdfarranger = PdfArrangerManager(["data/screenshot.png"])
        # check that process is actually running
        self.assertIsNone(self.process().poll())
        self.app()
        from dogtail.config import config
        # Now let's go faster
        config.searchBackoffDuration = 0.1

    def test_02_properties(self):
        self.__mainmenu("Edit Properties")
        dialog = self.app().child(roleName="dialog")
        creatorlab = dialog.child(roleName="table cell", name="Creator")
        creatorid = creatorlab.parent.children.index(creatorlab) + 1
        creatorval = creatorlab.parent.children[creatorid]
        creatorval.keyCombo("enter")
        from dogtail import rawinput
        rawinput.typeText('["Frodo", "Sam"]')
        dialog.child(name="OK").click()
        self.__mainmenu("Edit Properties")
        dialog = self.app().child(roleName="dialog")
        rawinput.keyCombo("enter")
        rawinput.typeText('Memories')
        rawinput.keyCombo("enter")
        dialog.child(name="OK").click()

    def test_03_zoom(self):
        app = self.app()
        zoomoutb = app.child(roleName="push button", description="Zoom Out")
        zoominb = app.child(roleName="push button", description="Zoom In")
        # maximum dezoom whatever the initial zoom level
        for _ in range(10):
            zoomoutb.click()
        for _ in range(3):
            zoominb.click()

    def test_04_rotate_undo(self):
        app = self.app()
        self.__assert_selected("")
        app.keyCombo("<ctrl>a")  # select all
        self.__assert_selected("1")
        app.keyCombo("<ctrl>Left")  # rotate left
        app.keyCombo("<ctrl>z")  # undo
        app.keyCombo("<ctrl>y")  # redo
        app.keyCombo("<ctrl>a")
        app.keyCombo("<ctrl>Right")  # rotate right
        app.keyCombo("<ctrl>Right")  # rotate right

    def test_05_duplicate(self):
        self.__popupmenu(0, "Duplicate")
        app = self.app()
        self.assertEqual(len(self.__icons()), 2)
        app.keyCombo("<ctrl>a")
        app.keyCombo("<ctrl>c")
        for __ in range(3):
            app.keyCombo("<ctrl>v")
        self.assertEqual(len(self.__icons()), 8)
        app.keyCombo("Right")
        app.keyCombo("Left")
        app.keyCombo("Down")
        self.__assert_selected("5")
        app.keyCombo("Up")
        self.__assert_selected("2")

    def test_06_page_format(self):
        self.__popupmenu(0, ["Select", "Select Odd Pages"])
        self.__assert_selected("1, 3, 5, 7")
        self.__popupmenu(0, "Page Format")
        dialog = self.app().child(roleName="dialog")
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

    def test_07_split_page(self):
        lbefore = len(self.__icons())
        self.__popupmenu(0, ["Select", "Select Even Pages"])
        self.__assert_selected("2, 4, 6, 8")
        self.__mainmenu(["Edit", "Split Pages"])
        self.assertEqual(len(self.__icons()), lbefore + 4)

    def test_08_zoom_pages(self):
        self.app().keyCombo("Home")
        self.__assert_selected("1")
        self.app().keyCombo("f")

    def test_09_save_as(self):
        self.__mainmenu("Save")
        filechooser = self.app().child(roleName="file chooser")
        tmp = self.__class__.tmp
        filename = os.path.join(tmp, "foobar.pdf")
        filechooser.child(roleName="text").text = filename
        saveb = filechooser.button("Save")
        self.__wait_cond(lambda: saveb.sensitive)
        filechooser.button("Save").click()
        self.__wait_cond(lambda: os.path.isfile(filename))

    def test_10_about(self):
        self.__mainmenu("About")
        dialog = self.app().child(roleName="dialog")
        dialog.child(name="Close").click()

    def test_11_reverse(self):
        self.__popupmenu(0, ["Select", "Same Page Format"])
        self.__assert_selected("1, 4, 7, 10")
        self.__popupmenu(0, ["Select", "All From Same File"])
        self.__assert_selected("1-12")
        self.__popupmenu(0, "Reverse Order")

    def test_12_quit(self):
        self.__mainmenu("Quit")
        dialog = self.app().child(roleName="alert")
        dialog.child(name="Cancel").click()
        self.app().keyCombo("<ctrl>s")
        self.app().keyCombo("<ctrl>q")
        # check that process actually exit
        self.process().wait(timeout=22)

    def tearDown(self):
        endgroup()

    @classmethod
    def tearDownClass(cls):
        if cls.pdfarranger:
            cls.pdfarranger.kill()
        if cls.tmp:
            shutil.rmtree(cls.tmp)
