#!/bin/bash

# Update translation files, after updating pdfarranger.pot
#   - all translation files if no argument is passed
#   - $1.po if an argument is passed (for example `updatepo.sh fr` for french locale)

#
# pdfarranger - GTK+ based utility for splitting, rearrangement and
# modification of PDF documents.
# Copyright (C) 2008-2017 Konstantinos Poulios
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
#

cd "$(dirname "$0")/.."

updatepo() {
  msgmerge --backup none -U "$1" po/pdfarranger.pot
  msgattrib --no-obsolete --clear-fuzzy --empty -o "$1" "$1"
}

# Make sure pdfarranger.pot is up-to-date
po/genpot.sh

if [[ "$1" = "" ]]; then
  for po in po/*.po
  do
    updatepo "$po"
  done
else
  if [ -f "po/$1.po" ]; then
    updatepo "po/$1.po"
  else
    echo "No such translation locale: $1."
    read -r -p "Would you like to create new translation locale $1? [y/N] " response
    case "$response" in
      [yY][eE][sS]|[yY]) 
        cp po/pdfarranger.pot "po/$1.po"
        ;;
      *)
        echo "Unknown translation: $1"
        exit 1
        ;;
    esac
  fi
fi
