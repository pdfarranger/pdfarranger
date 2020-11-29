import os
import subprocess
import sys
import unittest
import time
import tempfile

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
        config.defaultDelay = 0.5
        config.debugSearching = False
        config.searchCutoffCount = 10
        config.runTimeout = 1

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


class ImportQuitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdfarranger = None

    def setUp(self):
        group("Running " + self.id())

    def app(self):
        # Cannot import at top level because of DBUS_SESSION_BUS_ADDRESS
        from dogtail.tree import root
        return root.application("__main__.py")

    def process(self):
        return self.__class__.pdfarranger.process

    def test_1_import_img(self):
        self.__class__.pdfarranger = PdfArrangerManager(["data/screenshot.png"])
        # check that process is actually running
        self.assertIsNone(self.process().poll())
        self.app()
        from dogtail.config import config
        # Now let's go faster
        config.searchBackoffDuration = 0.1

    def test_2_zoom(self):
        app = self.app()
        zoomoutb = app.child(roleName="push button", description="Zoom Out")
        zoominb = app.child(roleName="push button", description="Zoom In")
        # maximum dezoom whatever the initial zoom level
        for i in range(10):
            zoomoutb.click()
        for i in range(3):
            zoominb.click()

    def __assert_selected(self, selection):
        app = self.app()
        statusbar = app.child(roleName="status bar")
        self.assertEqual(statusbar.name, "Selected pages: " + selection)

    def test_3_rotate_undo(self):
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

    def test_4_duplicate(self):
        from dogtail import predicate
        app = self.app()
        viewport = app.child(roleName="viewport")
        page1 = viewport.child(roleName="icon")
        page1.click(button=3)
        popupmenu = app.child(roleName="window")
        popupmenu.menuItem("Duplicate", showingOnly=None).click()
        icons = viewport.findChildren(predicate.GenericPredicate(roleName="icon"))
        self.assertEqual(len(icons), 2)
        app.keyCombo("<ctrl>a")
        app.keyCombo("<ctrl>c")
        for __ in range(3):
            app.keyCombo("<ctrl>v")
        icons = viewport.findChildren(predicate.GenericPredicate(roleName="icon"))
        self.assertEqual(len(icons), 8)
        app.keyCombo("Right")
        app.keyCombo("Left")
        app.keyCombo("Down")
        self.__assert_selected("5")

    def __click_mainmenu(self, action):
        mainmenu = self.app().child(roleName="toggle button", name="Menu")
        mainmenu.click()
        mainmenu.child(roleName="menu item", name=action, showingOnly=True).click()

    def __wait_cond(self, cond):
        c = 0
        while not cond():
            time.sleep(0.1)
            self.assertLess(c, 10)
            c += 1

    def test_5_save_as(self):
        self.__click_mainmenu("Save")
        filechooser = self.app().child(roleName="file chooser")
        with tempfile.TemporaryDirectory() as tmp:
            filename = os.path.join(tmp, "foobar.pdf")
            filechooser.child(roleName="text").text = filename
            saveb = filechooser.button("Save")
            self.__wait_cond(lambda: saveb.sensitive)
            filechooser.button("Save").click()
            self.__wait_cond(lambda: os.path.isfile(filename))

    def test_6_quit(self):
        self.__click_mainmenu("Quit")
        # check that process actually exit
        self.process().wait(timeout=22)

    def tearDown(self):
        endgroup()

    @classmethod
    def tearDownClass(cls):
        if cls.pdfarranger:
            cls.pdfarranger.kill()
