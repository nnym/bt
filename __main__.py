#!/bin/env python
import os.path as path
import sys
from importlib import util as ilu, machinery as ilm

def main():
	if not (bt := sys.modules.get("bt", None)):
		spec = ilm.PathFinder().find_spec("bt", [path.dirname(path.dirname(path.realpath(__file__)))])
		bt = ilu.module_from_spec(spec)
		sys.modules[bt.__name__] = bt
		spec.loader.exec_module(bt)

	bt.main()

if __name__ == "__main__": main()
