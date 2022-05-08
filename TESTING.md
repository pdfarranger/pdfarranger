This file aims at listing all GUI operation one should do to test the whole PDF Arranger
source code. Those tests must currently be done manually. May one day, they'll
be done with [Dogtail](https://gitlab.com/dogtail/dogtail) or another GUI testing framework.

As testing is done manually this list should remain as short as possible.
Duplicate tests should be avoided and each step should test as many features as
possible. This list was created using
[Coverage.py](https://coverage.readthedocs.io).

-   Run `python3 -m pdfarranger mypdf.pdf`

-   Crop and rotate one page

-   Rotate a page 4 time

-   Split a page

-   Crop white border on another page

-   Edit PDF properties, change some properties, set multiple creators using json syntax
    then validate the dialog with cursor still in the text field.

-   Delete one page

-   Undo delete, redo delete

-   Zoom / unzoom

-   Move one page using drag and drop

-   Cut / paste within same PDF Arranger instance

-   Save As

-   Import an image

-   Import a PDF file

-   Copy (`ctrl+c` / `ctrl+v`) a PDF file from a file explorer

-   Drag a PDF file from a file explorer

-   Copy a PDF file from another PDF Arranger instance and paste it interleaved

-   Select all pages, copy then paste odd

-   Select even page, then invert selection

-   Drag a PDF file from a PDF Arranger to a other PDF Arranger instance

-   Duplicate a page

-   Reverse order

-   Rubberband selection with scrolling

-   Open the about dialog

-   Quit, cancel

-   Quit without saving

## Dogtail

Running Dogtail tests and coverage in Docker:

```
docker run -w /src -v $PWD:/src jeromerobert/pdfarranger-docker-ci sh -c "pip install .[image] ; python3 -X tracemalloc -u -m unittest discover -s tests -v -f ; python3 -m coverage combine ; python3 -m coverage html"
```

Running Dogtail tests with the legacy PikePDF in Podman:

```
podman run -w /src -v $PWD:/src docker.io/jeromerobert/pdfarranger-docker-ci:1.3.1 sh -c "pip install .[image] ; python3 -u -m unittest discover -s tests -v"
```
