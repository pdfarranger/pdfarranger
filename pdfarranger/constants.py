import sys

import pikepdf

APPNAME = "PDF Arranger"
VERSION = "1.14.0"
WEBSITE = "https://github.com/pdfarranger/pdfarranger"

DOMAIN = "pdfarranger"
ICON_ID = "com.github.jeromerobert." + DOMAIN

PIKEPDF_VERSION = pikepdf.__version__
LIBQPDF_VERSION = pikepdf.__libqpdf_version__
PYTHON_VERSION = "{}.{}.{}".format(
    sys.version_info.major, sys.version_info.minor, sys.version_info.micro
)
