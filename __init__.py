import contextlib
import dis
import glob
import importlib
import inspect
import itertools
import os
import pickle
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import typing
from collections.abc import Iterable, Iterator, Mapping, MutableSequence, Sequence
from dataclasses import dataclass
from enum import Enum
from os import path
from subprocess import CompletedProcess
from time import time_ns as ns
from types import FrameType as Frame
from typing import Any, Callable, Optional, Self

if sys.version_info < (3, 12): exit(print("bt requires Python 3.12 or newer."))

__version__ = 5
assert __name__ == "bt" or "bt" not in sys.modules, f'bt\'s module name is "{__name__}" but "bt" is already in sys.modules'

bt = sys.modules[__name__]
"bt's main module."

sys.modules["bt"] = bt

type Runnable = Callable[[], Any]
Runnable = Runnable.__value__
"A function that can be called without arguments."

type FileSpecifier = str | typing.Iterable[FileSpecifier] | Callable[[], FileSpecifier]
FileSpecifier = FileSpecifier.__value__
"""A path or collection of paths."""

class State(Enum):
	NORMAL = 0
	RUNNING = 1
	DONE = 2
	SKIPPED = 3

class FlatList(list):
	def transform(this, x):
		return x

	def copy(this):
		copy = type(this)()
		copy += this
		return copy

	def append(this, x):
		if x := this.transform(x):
			if isIterable(x): this.extend(x)
			elif x: super().append(x)

	def insert(this, i, x):
		if x := this.transform(x):
			if isIterable(x): this[i:i] = x
			elif x: super().insert(i, x)

	def extend(this, x):
		if x := this.transform(x):
			assert isIterable(x), f"{x!r} is a string or not iterable."
			super().extend(x)
		return this

	def __setitem__(this, i, x):
		if x := this.transform(x):
			if isinstance(x, Iterable):
				if not isinstance(i, slice): i = slice(i, i + 1)
				if isinstance(x, str): x = [x]

			super().__setitem__(i, x)

	def __iadd__(this, x):
		return this.extend(x)

	def __add__(this, x):
		return this.copy().extend(x)

class Arguments(FlatList):
	"""`Arguments` is a `list` derivative that stores a full or partial command line.

	Only `None`, strings and `Iterable`s may be added;
	`None` is discarded and every `Iterable` is flattened.

	```python
	source = ["main.c"]
	exe = "foo"
	options = "-Ofast -std=c2x"
	command = Arguments("gcc", source, "-o", exe, options, parameter("o"))
	print(command) # gcc main.c -o foo -Ofast -std=c2x
	print(command.split()) # ['gcc', 'main.c', '-o', 'foo', '-Ofast', '-std=c2x']
	"""

	def __init__(this, *arguments):
		for arg in arguments: this.append(arg)

	def set(this, *arguments): this[:] = Arguments(arguments)

	def transform(this, args):
		if isinstance(args, str): return args.strip()
		if isinstance(args, Arguments): return args
		if isinstance(args, Iterable): return Arguments(*args)
		if args: raise TypeError(f"{args!r} is not iterable or a string")

	def split(this):
		"Split this argument list's `__str__` into a list."
		return shlex.split(str(this))

	def __str__(this):
		"Return all elements joined by spaces."
		return " ".join(this)

@dataclass
class Files:
	def __init__(this, *files):
		this.files = {}

		def flatten(f):
			if isinstance(f, str): this.files[f] = None
			elif isinstance(f, Mapping): flatten(f.values())
			elif isinstance(f, Iterable):
				for e in f: flatten(e)
			elif callable(f): flatten(f())
			else: raise AssertionError(f"{output!r} cannot be converted to a file (is not a string, a list, or callable).")

		flatten(files)

	def __iter__(this): return iter(this.files)

	def __repr__(this): return f"Files({", ".join(this.files)})"

class Task:
	def __init__(this, task: Runnable, dependencies: list[Self], options: dict[str, object]):
		vars(this).update(options)
		this.name0 = this.name
		this.setFunction(task)
		this.dependencies = dependencies
		this.state = State.NORMAL
		this.force = False
		this.args = []
		this.sourceFiles = []
		this.outputFiles = []
		this.cache = []

	def setFunction(this, fn):
		this.fn = fn
		this.spec = inspect.getfullargspec(fn)
		if this.name0 is None: this.name = getattr(fn, "__name__", f"<{len(tasks)}>")
		
	def __call__(this, *args, **kw):
		if started: return this.fn(*args, *this.args[len(args):], **kw)

		del tasks[this.name]
		this.dependencies.insert(0, this.fn)
		this.setFunction(args[0])
		tasks[this.name] = this

		return this

	for state in State:
		vars()[state.name.lower()] = property((lambda state, this: this.state == state).__get__(state))

@contextlib.contextmanager
def measure(precision = 1e3):
	t0 = ns()
	try: yield None
	finally: print((ns() - t0) / (1e9 / precision))

def isIterable(x): return isinstance(x, Iterable) and not isinstance(x, str)

def first[A](iterator: Iterator[A]) -> Optional[A]:
	return next(iterator, None)

def group[A, B](iterable: Iterable[A], key: Callable[[A], B]) -> dict[list[B]]:
	return {it[0]: list(it[1]) for it in itertools.groupby(sorted(iterable, key = key), key)}

def findTask(task: str | Runnable | Task, error = True, command = False) -> Optional[Task]:
	if callable(task): return task

	if (match := tasks.get(task, None)) and (match.export or not command):
		return match

	if task[-1:] == "!" and (match := tasks.get(task[:-1], None)) and (match.export or not command):
		match.force = True
		return match

	if error: exit(print(f'No task matched {task!r}.'))

def registerTask(fn: Runnable, dependencies: Iterable, options):
	task = Task(fn, [findTask(d) for d in dependencies], options)
	tasks[task.name] = task
	return task

def require(version: int):
	"Exit with an error message if the version of bt is older than `version`."
	if __version__ < version: exit(print(f"bt is version {__version__} but version {version} or newer is required."))

def task(*dependencies: str | Task | Runnable, name: Optional[str] = None, default = False, export = True, pure = False,
	source: FileSpecifier = [], input: Optional[Any] = None, output: FileSpecifier = []):
	"""Declare a task named `name` to be run at most once from the command line or as a dependency.
	Each dependency will run before the task.

	If `default`, then the task will run when no tasks are specified in the command line.\n
	If `export`, then it will be available in the command line.\n
	If `pure`, then dependent tasks may be skipped even if this task runs.

	If `source` or `output` is not an empty list or `input` is not `None`, then caching will be enabled.

	`source` and `output` will be searched for files recursively.
	Callables found therein will be converted into their results.

	All routines (as determined by `inspect.isroutine`) found recursively in `input`
	will be evaluated just before the task runs.

	The task will be skipped if
	- caching is enabled
	- no task dependency runs
	- `input` and the source files' mtimes are the same values from the task's previous run
	- and all output files exist."""

	options = dict(list(locals().items())[:-1])

	if dependencies and callable(dependencies[0]) and not isinstance(dependencies[0], Task):
		return registerTask(dependencies[0], dependencies[1:], options)

	return lambda fn: registerTask(fn, dependencies, options)

def parameter(name: str, default = None, require = False):
	"""Return the value of the parameter `name` if it's set or else `default`.
	If it's unset and not `require`, then print an error message and exit."""

	assert isinstance(name, str), f"Parameter name ({name!r}) must be a string."
	value = parameters.get(name, default)
	if not value and require: exit(print(f'Parameter "{name}" must be set.'))
	return value

def sh(*commandLine: Optional[str | Arguments | Iterable], shell = True, text = True, **kwargs) -> CompletedProcess[str]:
	"""Wrap `subprocess.run` with the defaults `shell = True` and `text = True`.
	Convert `commandLine` into an `Arguments` and then a string."""
	return subprocess.run(str(Arguments(commandLine)), shell = shell, text = text, **kwargs)

def shout(*args, capture_output = True, **kwargs) -> str:
	"Wrap `sh` with `capture_output = True` and return the command's `stdout`."
	return sh(*args, capture_output = capture_output, **kwargs).stdout

def read(file: str) -> str:
	"`open`, read and close the `file` and return its contents."
	with open(file) as fo: return fo.read()

def write(file: str, contents: str):
	"`open`, write `contents` to and close the `file`."
	with open(file, "w") as fo: fo.write(contents)

def rm(path: str):
	"Remove the specified path recursively if it exists."
	if os.path.isdir(path) and not os.path.islink(path): shutil.rmtree(path)
	elif os.path.exists(path): os.remove(path)

def start():
	global started
	started = True
	erred = False

	def error(task: Optional[Task], message: str = None):
		nonlocal erred
		erred = not print(f"Task {task.name}: {message}." if message else task)

	for task in tasks.values():
		if not isinstance(task.default, bool): error(task, f"default ({task.default!r}) is not a bool")
		if not isinstance(task.export, bool): error(task, f"export ({task.export!r}) is not a bool")
		if len(task.spec.kwonlyargs or []) != len(task.spec.kwonlydefaults or []): error(task, f"can't run with a non-default keyword-only parameter")

	initialTasks = [findTask(task, command = True) or task for task in cmdTasks] or [task for task in tasks.values() if task.default]
	if initialTasks: initialTasks[-1].args = args

	for task in initialTasks:
		arity = len(task.spec.args)
		min = arity - len(task.spec.defaults or [])
		count = len(task.args)

		if count < min or count > arity and not task.spec.varargs:
			error(task, f"received {count} argument{["s", ""][count == 1]} instead of {arity if min == arity else f"{min}-{arity}"}")

	if [not error(f'"{task}" does not match an exported task') for task in initialTasks if isinstance(task, str)]:
		print("Exported tasks are listed below.", *(name for name, task in tasks.items() if isinstance(name, str)), sep = "\n")

	if erred: return

	cache = {}

	if path.exists(CACHE):
		with open(CACHE, "br") as file:
			try:
				c = pickle.load(file)
				assert isinstance(c, Mapping)
				cache = c
			except Exception as e:
				print(CACHE + " is corrupt.")
				print(e)

	linesWritten = 0

	def run(task: Task, parent: Task = None, initial = False):
		if task.running: error(f'Circular dependency detected between tasks "{parent.name}" and "{task.name}".')
		if not task.normal: return

		task.state = State.RUNNING
		skip = True

		for dependency in task.dependencies:
			if isinstance(dependency, Task):
				run(dependency, task)
				if dependency.done and not dependency.pure: skip = False
			else: dependency()

		global current
		current = task

		def getFiles(source, flat, errorMessage, container = None):
			if container is None: container = source

			if isinstance(source, str): flat.append(source)
			elif isinstance(source, Mapping): getFiles(source.values(), flat, errorMessage, container)
			elif isinstance(source, Iterable):
				for o in source: getFiles(o, flat, errorMessage, container)
			elif callable(source): getFiles(source(), flat, errorMessage, container)
			else: error(task, errorMessage(source))

		if task.source != []:
			files = []
			getFiles(task.source, files, lambda source: f"source file {source!r} is not a string, iterable, or callable")

			for file in files:
				if glob.has_magic(file): task.sourceFiles += glob.glob(file, include_hidden = True, recursive = True)
				elif not path.exists(file): error(task, f'source file "{file}" does not exist')
				else: task.sourceFiles.append(file)

		if task.input is not None:
			def flatten(inputs):
				if inspect.isroutine(inputs): inputs = inputs()

				if isinstance(inputs, Mapping): inputs = list(inputs.values())
				elif isinstance(inputs, Iterable) and not isinstance(inputs, str | MutableSequence): inputs = list(inputs)

				if isIterable(inputs):
					for i, input in enumerate(inputs):
						inputs[i] = flatten(input)

				return inputs

			task.cache = flatten(task.input or 0)

		task.cache = task.cache, [path.getmtime(source) for source in task.sourceFiles]

		if task.output != []: getFiles(task.output, task.outputFiles, lambda o: f"output {o!r} is not a file (a string, iterable, or callable)")

		if erred: return

		if (skip and not (task.force or force == 1 and initial or force >= 2) and task.cache == cache.get(task.name, None)
		and (task.source != [] or task.input is not None or task.outputFiles) and all(path.exists(output) for output in task.outputFiles)):
			task.state = State.SKIPPED
			return

		for directory in {path.dirname(path.abspath(output)) for output in task.outputFiles}:
			os.makedirs(directory, exist_ok = True)

		nonlocal linesWritten

		if debug:
			if linesWritten > 1: print()
			print(">", task.name)

		linesWritten = 0

		def redirect(stream):
			write0 = stream.write

			def write(s):
				nonlocal linesWritten
				linesWritten += s.count("\n")
				write0(s)

			stream.write = write
			return write0

		write10, write20 = redirect(sys.stdout), redirect(sys.stderr)
		try: task()
		finally: sys.stdout.write, sys.stderr.write = write10, write20

		task.state = State.DONE

	for task in initialTasks: run(task, initial = True)

	cache.update((task.name, task.cache) for task in tasks.values() if task.done)

	with open(CACHE, "bw") as file:
		pickle.dump(cache, file)

def main(loadModule):
	if entry := first(entry for entry in ["bs", "bs.py"] if path.exists(entry)):
		try: loadModule("bs", entry)
		except Exception as e:
			tb = e.__traceback__
			while tb and tb.tb_frame.f_code.co_filename != entry: tb = tb.tb_next
			if tb: e.__traceback__ = tb
			raise e.with_traceback(tb)
	else: exit(print("No build script (bs or bs.py) was found."))

	start()

debug = False
"""Whether to print debugging information.
Currently only names of tasks before they run are printed."""

current: Task = None
"The task that is currently running."

exports = bt, Arguments, Files, Task, parameter, require, read, rm, sh, shout, task, write
exports = {export.__name__: export for export in exports} | {"FileSpecifier": FileSpecifier, "Runnable": Runnable, "path": path}
__all__ = list(exports.keys())

CACHE = ".bt"

tasks: dict[str, Task] = {}

started = False

args0 = sys.argv[1:]

if "--" in args0 and ~(split := args0.index("--")):
	args0, args = args0[:split], args0[split + 1:]
else: args = []

args1 = [a for a in args0 if a != "!"]
force = len(args0) - len(args1)
args1 = group(args1, lambda a: "=" in a)
cmdTasks = args1.get(False, [])
parameters: dict[str, str] = dict(arg.split("=", 2) for arg in args1.get(True, []))

f: Frame = sys._getframe()

while f := f.f_back:
	if dis.opname[(co := f.f_code).co_code[i := f.f_lasti]] in ["IMPORT_NAME", "IMPORT_FROM"] and "__main__" not in co.co_names[co.co_code[i + 1]]:
		os.chdir(path.dirname(path.realpath(sys.argv[0])))
		caller = threading.current_thread()
		thread = threading.Thread(target = lambda: (caller.join(), start()), daemon = False)
		thread.start()
		hook, threading.excepthook = threading.excepthook, lambda args: thread._stop() if args.thread == caller else hook(args)

		break
