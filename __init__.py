import builtins
import sys
from os import path

if not (bt := getattr(builtins, "bt", None)):
	from . import __main__ as bt

globals().update(vars(bt) | globals())
bt.supplyExports()
