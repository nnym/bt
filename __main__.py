#!/usr/bin/env python
import os.path as osp
import sys
from importlib import machinery as ilm

def loadModule(name, path):
	return ilm.SourceFileLoader(name, path).load_module()

def main():
	(sys.modules.get("bt", None) or loadModule("bt", osp.join(osp.dirname(osp.realpath(__file__)), "__init__.py"))).main(loadModule)

if __name__ == "__main__": main()
