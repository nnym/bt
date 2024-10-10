import inspect
import os
import re
import sphinx
import sys
import textwrap
from sphinx import application
from sphinx.ext.autodoc import Documenter, FunctionDocumenter, ModuleDocumenter
from typing import TypeAliasType as TypeAlias

project = "bt"
extensions = ["sphinx.ext.autodoc"]
html_theme = "furo"
html_static_path = ["."]
html_css_files = ["style.css"]
autodoc_default_options = {
	"members": True, 
	"special-members": True
}

codeBlock = re.compile(r"```(\w+)\s*?\n([\s\S]*?)(```|$)")
inlineCode = re.compile(r"(`[^`]*?`)(\w*)")

class BtDocumenter(ModuleDocumenter):
	def sort_members(this, members: list[tuple[Documenter, bool]], order: str) -> list[tuple[Documenter, bool]]:
		super().sort_members(members, order)
		members.sort(key = lambda m: {"data": 0, "class": 2, "function": 4}[m[0].objtype] + m[0].name[m[0].name.rindex(":") + 1].isupper())
		return members

def skip(app, scope, name, ob, skip, options):
	if name in options.get("exclude-members", []): return True
	if scope == "module" and not callable(ob) and "__doc__" in dir(ob): return False

	if scope == "class":
		try: return (skip or (name[0] == "_" and not callable(ob)) or not ob.__doc__
			or not os.path.samefile(inspect.getsourcefile(ob), sys.modules["bt"].__file__))
		except: return True

def docstring(app, type, name, ob, options, lines):
	doc = "\n".join(lines)
	doc = codeBlock.sub(lambda m: f".. code-block:: {m[1]}\n\n" + textwrap.indent(m[2], "    "), doc)
	lines[:] = inlineCode.sub(lambda m: m[1] + "\\" + m[2] if m[2] else m[0], doc).split("\n")
	
def setup(app: application.Sphinx):
	app.add_autodocumenter(BtDocumenter, True)
	app.connect("autodoc-skip-member", skip)
	app.connect("autodoc-process-docstring", docstring)
