import importlib

import pytest

PACKAGES = ["ingestion", "features", "models", "serving", "orchestration"]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    importlib.import_module(name)
