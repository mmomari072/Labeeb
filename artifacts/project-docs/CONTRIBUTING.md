# Contributing to Labeeb

Thank you for your interest in contributing to **Labeeb**! We welcome contributions, bug fixes, feature enhancements, and documentation improvements.

---

## 1. Development Setup

Clone the repository and install in editable mode with development dependencies:

```bash
git clone https://github.com/mmomari072/Labeeb.git
cd Labeeb
pip install -e .[dev]
```

---

## 2. Code Quality Standards

* **PEP 8 Compliance**: Code must adhere to PEP 8 standards. Use `black` and `flake8` for formatting and linting.
* **Type Hints**: All functions, methods, and classes must include Python 3.8+ type annotations.
* **Import Order**: Use `isort` for standard import organization.
* **Docstrings**: Provide clear Google or Sphinx-style docstrings for public classes and functions.
* **Error Handling**: Use domain-specific exceptions from `labeeb.exceptions`.

---

## 3. Running Tests

Before submitting any code changes, ensure all tests pass cleanly:

```bash
# Run unit test suite
pytest

# Run tests with verbose output
pytest -v
```

---

## 4. Submitting Pull Requests

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Commit your changes with clear, descriptive commit messages.
3. Add corresponding test cases under `tests/`.
4. Ensure `pytest` passes with 100% success.
5. Submit a Pull Request targeting the `main` branch.
