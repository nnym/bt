#!/bin/env python
import importlib
import os.path as path
import sys

spec = importlib.machinery.PathFinder().find_spec("bt", [path.dirname(path.dirname(path.realpath(__file__)))])
bt = importlib.util.module_from_spec(spec)
bt.MAIN = 1
sys.modules[bt.__name__] = bt
spec.loader.exec_module(bt)
