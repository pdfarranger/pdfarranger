# Testing

The code is tested using [unittest](https://docs.python.org/3/library/unittest.html) and [dogtail](https://gitlab.com/dogtail/dogtail). Currently there are 3 files:
1. `test.py` which test the GUI
2. `test_core.py` which test Page and LayerPage class
3. `test_exporter.py` which test that exported pdf is as expected

When a PR is made a test is automatically run. If the test fail it (should be) because the PR introduce a new bug, or because the behavior of the app is changed and the tests are not updated to reflect the change.

The tests can be run locally using the examples below.

Some more info is found in beginning of test.py

## Run tests locally (with visible GUI)

```sh
# Make folder tests/ as a package
touch tests/__init__.py
# Run whole GUI test
python3 -X tracemalloc -u -m unittest -v -f tests.test
# Run only TestBatch5
python3 -X tracemalloc -u -m unittest -v -f tests.test.TestBatch5
# Run test_core
python3 -X tracemalloc -u -m unittest -v -f tests.test_core
# Run test_exporter
python3 -X tracemalloc -u -m unittest -v -f tests.test_exporter
```

## Run tests in Docker (GUI not visible)

```sh
# Run all tests in test.py
docker run -w /src -v $PWD:/src jeromerobert/pdfarranger-docker-ci:1.5.0 sh -c "pip install .[image] ; python3 -X tracemalloc -u -m unittest tests.test"
# Run all tests (test.py, test_core.py, test_exporter.py) and coverage
docker run -w /src -v $PWD:/src jeromerobert/pdfarranger-docker-ci:1.5.0 sh -c "pip install .[image] ; python3 -X tracemalloc -u -m unittest discover -s tests -v -f ; python3 -m coverage combine ; python3 -m coverage html"
```
