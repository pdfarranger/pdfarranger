VERSION='1.11.1'

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


def clean_build():
    dirs = os.listdir('build')
    keep = ['mo', 'lib']
    for d in dirs:
        if d not in keep:
            shutil.rmtree(os.path.join('build', d))


clean_build()


def addfile(relpath, warn_missing=False):
    f = os.path.join(sys.prefix, relpath)
    if warn_missing and not os.path.isfile(f):
        print("{} cannot be found.".format(f), file=sys.stderr)
    else:
        include_files.append((f, relpath))


def addlocale(name):
    langs = os.listdir('build/mo')
    for path in glob.glob(os.path.join(sys.prefix,
                                       "share/locale/*/LC_MESSAGES/{}.mo".format(name))):
        lang = os.path.split(os.path.split(os.path.split(path)[0])[0])[1]
        if lang in langs:
            addfile(os.path.relpath(path, sys.prefix))


addlocale("gtk30")


def addicons():
    addfile("share/icons/hicolor/index.theme")
    addfile("share/icons/Adwaita/index.theme")
    for i in ['places/folder', 'mimetypes/text-x-generic']:
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
        'actions/document-open',
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
        addfile(os.path.join('share/icons/Adwaita/symbolic/', i + '-symbolic.svg'))

required_dlls = [
    'poppler-glib-8',
    'handy-1-0',
]

for dll in required_dlls:
    fn = 'lib' + dll + '.dll'
    include_files.append((os.path.join(sys.prefix, 'bin', fn), fn))

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
    "HarfBuzz-0.0",
    "Handy-1",
    "freetype2-2.0",
]

for ns in required_gi_namespaces:
    addfile("lib/girepository-1.0/{}.typelib".format(ns))

addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-bmp.dll")
addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders/pixbufloader_svg.dll")
addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-png.dll")
addfile("lib/gdk-pixbuf-2.0/2.10.0/loaders.cache")
addfile("share/glib-2.0/schemas/gschemas.compiled")
addicons()


# gspawn-helper is needed for website link in AboutDialog
from_path = os.path.join(sys.prefix, 'bin', 'gspawn-win64-helper.exe')
to_path = 'gspawn-win64-helper.exe'
include_files.append((from_path, to_path))


build_options = dict(
    packages=['gi', 'packaging', 'pikepdf'],
    excludes=['tkinter', 'test'],
    include_files=include_files,
)


def get_target_name(suffix):
    return 'pdfarranger-{}-windows-{}'.format(VERSION, suffix)


msi_options = dict(
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
        config_ini = os.path.join(build_exe.build_exe, 'config.ini')
        f = open(config_ini, 'w')
        f.close()
        dist_dir = self.get_finalized_command('bdist').dist_dir
        archname = os.path.join(dist_dir, get_target_name('portable'))
        self.make_archive(archname, 'zip', root_dir=build_base, base_dir=fullname)
        shutil.rmtree(build_exe.build_exe)


setup(name='PDF Arranger',
      author='The PDF Arranger team',
      version=VERSION,
      description='A simple application for PDF Merging, Rearranging, and Splitting',
      options=dict(build_exe=build_options, bdist_msi=msi_options),
      cmdclass={'bdist_zip': bdist_zip},
      packages=['pdfarranger'],
      executables=[Executable('pdfarranger/__main__.py',
                              base='Win32GUI' if sys.platform == 'win32' else None,
                              target_name='pdfarranger.exe',
                              icon='data/pdfarranger.ico',
                              shortcut_name='PDF Arranger',
                              shortcut_dir='StartMenuFolder'
                              )])


def rename_msi():
    # cx_freeze 6.15: Workaround for having different filename and "ProductName" for the msi.
    dist_dir = os.path.join(os.getcwd(), 'dist')
    msi = [f for f in os.listdir(dist_dir) if f.endswith('.msi')]
    if len(msi) > 0:
        old_name = os.path.join(dist_dir, msi[0])
        new_name = os.path.join(dist_dir, get_target_name('installer.msi'))
        shutil.move(old_name, new_name)

if 'bdist_msi' in sys.argv:
    rename_msi()
