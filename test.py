#! /usr/bin/env python3

import os
import subprocess
import sys
import unittest

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


class XvfbTest(unittest.TestCase):
    """Base class for running offscreen tests"""

    def __init__(self, methodName, display=":99"):
        super().__init__(methodName)
        self.display = display
        os.environ["DISPLAY"] = display
        self.environ = os.environ.copy()
        self.xvfb_proc = None
        self.dbus_proc = None

    def setUp(self):
        self.xvfb_proc = subprocess.Popen(["Xvfb", self.display])
        self.dbus_proc = subprocess.Popen(
            ["dbus-daemon", "--print-address=1", "--session"],
            stdout=subprocess.PIPE,
            text=True,
            env=self.environ,
        )
        dbus_addr = self.dbus_proc.stdout.readline().strip()
        self.dbus_proc.stdout.close()
        self.environ["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = dbus_addr
        print(dbus_addr)

    def tearDown(self):
        self.dbus_proc.kill()
        self.dbus_proc.wait()
        self.xvfb_proc.kill()
        self.xvfb_proc.wait()


class OnscreenTest(unittest.TestCase):
    """Base class for onscreen test (to debug tests)"""

    def __init__(self, methodName):
        super().__init__(methodName)
        self.environ = os.environ.copy()


# Inherit OnscreenTest instead of XvfbTest to debug tests
class DogtailTest(XvfbTest):
    def __init__(self, methodName):
        super().__init__(methodName)
        self.environ["LC_MESSAGES"] = "C"
        self.environ["GTK_MODULES"] = "gail:atk-bridge"
        os.environ["GTK_MODULES"] = "gail:atk-bridge"

    def setUp(self):
        super().setUp()
        subprocess.check_call(
            [
                "gsettings",
                "set",
                "org.gnome.desktop.interface",
                "toolkit-accessibility",
                "true",
            ],
            env=self.environ,
        )
        # dogtail must be imported after setting DBUS_SESSION_BUS_ADDRESS
        from dogtail.config import config
        config.debugSleep = True
        # long duration at startup
        config.searchBackoffDuration = 1
        config.actionDelay = 0.01
        config.runInterval = 0.01
        config.defaultDelay = 1
        config.debugSearching = True
        config.searchCutoffCount = 10
        config.runTimeout = 1

    def tearDown(self):
        super().tearDown()


class PdfArrangerTest(DogtailTest):
    def __init__(self, methodName, args=None):
        super().__init__(methodName)
        self.process = None
        self.args = [] if args is None else args

    def setUp(self):
        super().setUp()
        cmd = [sys.executable, "-u", "-X", "tracemalloc"]
        self.process = subprocess.Popen(
            cmd + ["-m", "pdfarranger"] + self.args, env=self.environ
        )

    def tearDown(self):
        self.process.kill()
        self.process.wait()
        super().tearDown()


class ImportQuitTest(PdfArrangerTest):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName, ["data/screenshot.png"])

    def runTest(self):
        # Cannot import at top level because of DBUS_SESSION_BUS_ADDRESS
        from dogtail.tree import root
        # check that process is actually running
        self.assertIsNone(self.process.poll())
        app = root.application("__main__.py")
        from dogtail.config import config
        config.searchBackoffDuration = 0.1
        mainmenu = app.child(roleName="toggle button", name="Menu")
        mainmenu.click()
        mainmenu.child(roleName="menu item", name="Quit", showingOnly=True).click()
        # check that process actually exit
        self.process.wait(timeout=0.5)
