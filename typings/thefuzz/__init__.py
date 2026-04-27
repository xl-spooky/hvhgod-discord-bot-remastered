"""Local type stub package for thefuzz.

This shim allows static analysis to resolve imports without requiring the
runtime dependency to be installed in the current environment.
"""

from .process import Processor, Scorer, extract

__all__ = ["Processor", "Scorer", "extract"]
