# writing code

- Python
- Use type annotations in code
- add comments , but not too much
- add docstrings to modules and methods. Docstrings should be max 5-9 lines
- Use f-strings for string formatting
- Use snake_case for variable and function names
- Use CamelCase for class names
- Use 4 spaces for indentation
- Use double quotes for strings

# Speed and performance

- this is a CLI tool and loading speed is important
- Use lazy loading for modules and packages where possible
- Use generators for large data sets

# dependencies

- Use uv pip for package management
- the project is handled by poetry and all dependencies should be added to the pyproject.toml file
- minimize the number of dependencies
-

# Writing tests

- Use pytest for testing
- Use pytest fixtures for setup and teardown
- Use assert statements for testing
- all tests shouod be located in a tests/ directory
- Use descriptive names for test functions
- Use pytest.mark.parametrize for parameterized tests
- Use pytest.raises for testing exceptions
- for database testing make use of the test database int tests/data
