"""Prop firm trading bot (crypto + NQ futures). Module 1: core infrastructure and risk."""

__version__ = "0.1.0"

import logging as _logging

# Library convention: silent until the application calls setup_logging().
_logging.getLogger("trading_bot").addHandler(_logging.NullHandler())
