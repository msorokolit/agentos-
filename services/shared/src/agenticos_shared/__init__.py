"""AgenticOS shared library."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agenticos-shared")
except PackageNotFoundError:  # pragma: no cover - dev install
    __version__ = "0.0.0"

__all__ = ["__version__"]
