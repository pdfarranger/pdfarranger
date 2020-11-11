Name:           pdfarranger
Version:        1.6.2
Release:        1%{?dist}
Summary:        PDF file merging, rearranging, and splitting

License:        GPLv3
URL:            https://github.com/jeromerobert/%{name}
Source0:        %{url}/archive/%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  python3-distutils-extra
BuildRequires:  python3-wheel
BuildRequires:  python3-pip

# For checks only
BuildRequires:  libappstream-glib
BuildRequires:  desktop-file-utils

Requires:       python3-pikepdf >= 1.15.1
Recommends:     python3-img2pdf >= 0.3.4

# These seem to be included in the default desktop install
Requires:       python3-gobject
Requires:       gtk3
Requires:       python3-cairo
Requires:       poppler-glib

%if 0%{?fedora} > 31
# replace pdfshuffler for Fedora 32+ since it is python2 only (#1738935)
Provides:       pdfshuffler = %{version}-%{release}
# Current pdfshuffler is 0.6.0-17. I obsolete everything < 0.6.1 here
# because there might be new releases but they won't add python3 support.
Obsoletes:      pdfshuffler < 0.6.1-1
%endif

%global app_id com.github.jeromerobert.pdfarranger
%global python3_wheelname %{name}-%{version}-py3-none-any.whl

%description
pdfarranger is a small Python GTK application, which helps the user to merge 
or split PDF documents and rotate, crop and rearrange their pages using an 
interactive and intuitive graphical interface. It is a front end for 
python-PyPDF2.
pdfarranger is a fork of Konstantinos Poulios's PDF-Shuffler.

%prep
%autosetup -n %{name}-%{version}

# py3_build / py3_install do not work with this setup.py but building
# a wheel works just fine
%build
%py3_build_wheel

%install
%py3_install_wheel %{python3_wheelname}
%find_lang %{name}
%if 0%{?fedora} > 31
ln -s %{_bindir}/pdfarranger %{buildroot}%{_bindir}/pdfshuffler
%endif

%check
desktop-file-validate %{buildroot}/%{_datadir}/applications/%{app_id}.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/*.metainfo.xml

%files -f %{name}.lang
%license COPYING
%doc README.md
%{python3_sitelib}/%{name}/
%{python3_sitelib}/%{name}-%{version}.dist-info/
%{_mandir}/man*/*.*
%{_datadir}/icons/hicolor/*/apps/%{app_id}.*
%{_metainfodir}/%{app_id}.metainfo.xml
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/%{name}/
%{_bindir}/pdfarranger
%if 0%{?fedora} > 31
%{_bindir}/pdfshuffler
%endif

%changelog
* Sat Aug 01 2020 David Auer <dreua@posteo.de> - 1.6.2-1
- Update to 1.6.2

* Tue Jul 28 2020 Fedora Release Engineering <releng@fedoraproject.org> - 1.6.0-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_33_Mass_Rebuild

* Thu Jul 16 2020 David Auer <dreua@posteo.de> - 1.6.0-2
- Recommend img2pdf

* Wed Jul 15 2020 David Auer <dreua@posteo.de> - 1.6.0-1
- Update to 1.6.0
- Require pikepdf >= 1.15.1 as suggested in Readme.

* Wed Jun 24 2020 David Auer <dreua@posteo.de> - 1.5.3-3
- Explicitly require python3-setuptools

* Tue May 26 2020 Miro Hrončok <mhroncok@redhat.com> - 1.5.3-2
- Rebuilt for Python 3.9

* Sun May 17 2020 David Auer <dreua@posteo.de> - 1.5.3-1
- Update to 1.5.3

* Mon Apr 20 2020 David Auer <dreua@posteo.de> - 1.5.1-1
- Update to 1.5.1 (#1823971)
- Fixes rhbz#1824017

* Wed Apr 15 2020 David Auer <dreua@posteo.de> - 1.5.0-1
- Update to 1.5.0 (#1823971)

* Tue Mar 17 2020 Fabian Affolter <mail@fabian-affolter.ch> - 1.4.2-1
- Update to new upstream version 1.4.2 (rhbz#1814032)

* Sun Feb 09 2020 Fedora Release Monitoring <release-monitoring@fedoraproject.org> - 1.4.1-1
- Update to 1.4.1 (#1800993)

* Sat Feb 01 2020 David Auer <dreua@posteo.de> - 1.4.0-1
- New version, see https://github.com/jeromerobert/pdfarranger/releases/tag/1.4.0
- Replace python3-PyPDF2 with python3-pikepdf

* Wed Jan 29 2020 Fedora Release Engineering <releng@fedoraproject.org> - 1.3.1-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_32_Mass_Rebuild

* Wed Sep 25 2019 David Auer <dreua@posteo.de> - 1.3.1-2
- replace pdfshuffler on f32+

* Sun Sep 22 2019 David Auer <dreua@posteo.de> - 1.3.1-1
- New version, see https://github.com/jeromerobert/pdfarranger/releases/tag/1.3.1

* Wed Sep 11 2019 David Auer <dreua@posteo.de> - 1.3.0-2
- Add missing dependency
- Remove unnecessary python_provide makro

* Sun Aug 11 2019 David Auer <dreua@posteo.de> - 1.3.0-1
- New version, see https://github.com/jeromerobert/pdfarranger/releases/tag/1.3.0
- Remove obsolete downstream fixes 

* Tue Jun 11 2019 David Auer <dreua@posteo.de> - 1.2.1-8
- Better source URL

* Mon May 20 2019 David Auer <dreua@posteo.de> - 1.2.1-7
- Fix directory ownership
- Replace obsolete srcname by name

* Mon May 20 2019 David Auer <dreua@posteo.de> - 1.2.1-6
- Name changed from python-pdfarranger to pdfarranger
- Remove shebang in __main__.py

* Sat May 18 2019 David Auer <dreua@posteo.de> - 1.2.1-5
- Fix rpmlint errors and warnings

* Sat May 18 2019 David Auer <dreua@posteo.de> - 1.2.1-4
- Buiding with wheel to get lang and icons right

* Sat May 18 2019 David Auer <dreua@posteo.de> - 1.2.1-3
- Move Requires to the right location

* Sat May 18 2019 David Auer <dreua@posteo.de> - 1.2.1-2
- Add missing requires

* Sat May 18 2019 David Auer <dreua@posteo.de> - 1.2.1
- Packaging pdfarranger based on pdfshuffler's spec file and https://docs.fedoraproject.org/en-US/packaging-guidelines/Python/#_example_python_spec_file


