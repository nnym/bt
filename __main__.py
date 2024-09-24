#!/bin/env python
import importlib
import os.path as path
import sys

spec = importlib.util.spec_from_file_location("bt", path.join(path.dirname(path.realpath(__file__)), "__init__.py"))
bt = importlib.util.module_from_spec(spec)
bt.MAIN = 1
sys.modules[bt.__name__] = bt
spec.loader.exec_module(bt)
