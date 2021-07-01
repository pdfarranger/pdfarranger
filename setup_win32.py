VERSION='1.7.1'

from cx_Freeze import setup, Executable
import os
import sys
import distutils
import shutil
import glob

include_files = [
    ('data/pdfarranger.ui', 'share/pdfarranger/pdfarranger.ui'),
    ('data/menu.ui', 'share/pdfarranger/menu.ui'),
    ('data/icons/hicolor/scalable', 'share/icons/hicolor/scalable'),
    ('build/mo', 'share/locale'),
]


def addfile(relpath, warn_missing=False):
    global include_files
    f = os.path.join(sys.prefix, relpath)
    if warn_missing and not os.path.isfile(f):
        print("{} cannot be found.".format(f), file=sys.stderr)
    else:
        include_files.append((f, relpath))


def addlocale(name):
    for path in glob.glob(os.path.join(sys.prefix,
                                       "share/locale/*/LC_MESSAGES/{}.mo".format(name))):
        addfile(os.path.relpath(path, sys.prefix))


addlocale("gtk30")


def addicons():
    addfile("share/icons/hicolor/index.theme")
    addfile("share/icons/Adwaita/index.theme")
    for i in ['places/folder', 'mimetypes/text-x-generic', 'status/image-missing']:
        addfile(os.path.join('share/icons/Adwaita/16x16/', i + '.png'))
    icons = [
        'places/user-desktop',
        'places/user-home',
        'actions/bookmark-new',
        'actions/document-open-recent',
        'actions/folder-new',
        'actions/list-add',
        'actions/list-remove',
        'actions/media-eject',
        'actions/document-save',
        'actions/document-save-as',
        'actions/insert-image',
        'actions/object-rotate-left',
        'actions/object-rotate-right',
        'actions/open-menu',
        'actions/zoom-in',
        'actions/zoom-out',
        'ui/pan-down',
        'ui/pan-end',
        'ui/pan-start',
        'ui/pan-up',
        'ui/window-close',
        'ui/window-maximize',
        'ui/window-minimize',
        'ui/window-restore',
        'devices/drive-harddisk',
        'devices/drive-optical',
        'places/folder-documents',
        'places/folder-download',
        'places/folder-music',
        'places/folder-pictures',
        'places/folder-videos',
        'places/user-trash',
    ]

    for i in icons:
        addfile(os.path.join('share/icons/Adwaita/scalable/', i + '-symbolic.svg'))

required_dlls = [
    'gtk-3-0',
    'gdk-3-0',
    'epoxy-0',
    'gdk_pixbuf-2.0-0',
    'pango-1.0-0',
    'pangocairo-1.0-0',
    'pangoft2-1.0-0',
    'pangowin32-1.0-0',
    'atk-1.0-0',
    'poppler-glib-8',
    'xml2-2',
    'rsvg-2-2',
]

for dll in required_dlls:
    fn = 'lib' + dll + '.dll'
    include_files.append((os.path.join(sys.prefix, 'bin', fn), fn))

# zlib1 is first loaded by a DLL located in lib
include_files.append((os.path.join(sys.prefix, 'bin', 'zlib1.dll'),
                      os.path.join('lib', 'zlib1.dll'),))

required_gi_namespaces = [
    "Gtk-3.0",
    "Gdk-3.0",
    "cairo-1.0",
    "Pango-1.0",
    "GObject-2.0",
    "GLib-2.0",
    "Gio-2.0",
    "GdkPixbuf-2.0",
    "GModule-2.0",
    "Atk-1.0",
    "Poppler-0.18",
    "HarfBuzz-0.0"
]

for ns in required_gi_namespaces:
    addfile("lib/girepository-1.0/{}.typelib".format(ns))

addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.dll")
addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-png.dll")
addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders.cache")
addfile("share/glib-2.0/schemas/gschemas.compiled")
addicons()

build_options = dict(
    packages=['gi', 'packaging', 'pikepdf'],
    excludes=['tkinter', 'test'],
    # manually added to the lib folder
    bin_excludes=['zlib1.dll'],
    include_files=include_files,
)


def get_target_name(suffix):
    return 'pdfarranger-{}-windows-{}'.format(VERSION, suffix)


msi_options = dict(
    target_name=get_target_name('installer.msi'),
    upgrade_code='{ab1752a6-575c-42e1-a261-b85cb8a6b524}'
)


class bdist_zip(distutils.cmd.Command):
    """ Minimalist command to create a Windows portable .zip distribution """
    description = "create a \"zip\" distribution"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        build_base = self.get_finalized_command('build').build_base
        build_exe = self.get_finalized_command('build_exe')
        fullname = self.distribution.get_fullname()
        build_exe.build_exe = os.path.join(build_base, fullname)
        build_exe.run()
        dist_dir = self.get_finalized_command('bdist').dist_dir
        archname = os.path.join(dist_dir, get_target_name('portable'))
        self.make_archive(archname, 'zip', root_dir=build_base, base_dir=fullname)
        shutil.rmtree(build_exe.build_exe)


setup(name='pdfarranger',
      version=VERSION,
      description='A simple application for PDF Merging, Rearranging, and Splitting',
      options=dict(build_exe=build_options, bdist_msi=msi_options),
      cmdclass={'bdist_zip': bdist_zip},
      executables=[Executable('pdfarranger/__main__.py',
                              base='Win32GUI' if sys.platform == 'win32' else None,
                              targetName='pdfarranger.exe',
                              icon='data/pdfarranger.ico',
                              shortcutName='PDF Arranger',
                              shortcutDir='StartMenuFolder'
                              )])
