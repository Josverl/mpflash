# how to run tests

To install test dependencies, use:
```
poetry install --with test
```

To run all tests, use:
```
pytest
```

To run tests with coverage report:
```
pytest --cov
```

To generate an HTML coverage report:
```
pytest --cov=mpflash --cov-report=html
```
Open the generated `htmlcov/index.html` in your browser to view the coverage report.



Database tests
-----------------

The majority of thests is run using a (copy) of a populated database located in tests/data/mpflash.db

A number of fixtures have been setup in tests/conftest.py to simplify using the session or engine in tests. The fixtures are:
- session_fx: a session object that is used to run tests
- engine_fx: an engine object that is used to run tests
- db_fx: a database object that is used to run tests
  