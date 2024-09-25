import functools
import importlib
import inspect
import os
import pickle
import re
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from ordered_set import OrderedSet
from os import path
from typing import Callable, Optional, Self

Runnable = Callable[[], None]

CACHE = ".bt"

bt = sys.modules["bt"]
assert bt == sys.modules[__name__]

class State(Enum):
	NORMAL = 0
	RUNNING = 1
	DONE = 2
	SKIPPED = 3

class FlatList(list):
	def transform(this, x, single, multiple):
		return x

	def append(this, x):
		x = this.transform(x)
		if isinstance(x, Iterable) and not isinstance(x, str): this.extend(x)
		elif x: super().append(x)

	def insert(this, i, x):
		x = this.transform(x)
		if isinstance(x, Iterable) and not isinstance(x, str): this[i:i] = x
		elif x: super().insert(i, x)

	def extend(this, x):
		if x := this.transform(x):
			assert isinstance(x, Iterable), f"{x!r} is not iterable."
			super().extend(x)
		return this

	def __setitem__(this, i, x):
		if x := this.transform(x):
			if isinstance(x, Iterable) and not isinstance(x, str) and not isinstance(i, slice): i = slice(i, i + 1)
			super().__setitem__(i, x)

	def __iadd__(this, x):
		return this.extend(x)

	def __add__(this, x):
		return this.copy().extend(x)

class Arguments(FlatList):
	def __init__(this, *arguments):
		for arg in arguments:
			this.append(arg)

	def set(this, *arguments): this[:] = Arguments(arguments)

	def transform(this, args):
		if isinstance(args, str): return args.strip()
		if isinstance(args, Arguments): return args
		if isinstance(args, Iterable): return Arguments(*args)
		if args: raise TypeError(f"{args!r} is not iterable or a string")

	def __str__(this): return join(this)

	def split(this): return shlex.split(str(this))

@dataclass
class Files:
	def __init__(this, *files):
		this.files = OrderedSet()

		def flatten(f):
			if isinstance(f, str): this.files.add(f)
			elif isinstance(f, Mapping): flatten(f.values())
			elif isinstance(f, Iterable):
				for e in f: flatten(e)
			elif callable(f): flatten(f())
			else: raise AssertionError(f"{output!r} cannot be converted to a file (is not a string, a list, or callable).")

		flatten(files)

	def __iter__(this): return iter(this.files)

	def __repr__(this): return f"Files({", ".join(this.files)})"

class Task:
	def __init__(this, task: Runnable, dependencies: list[Self], kw: dict[str, object]):
		this.name = task.__name__
		this.fn = task
		this.dependencies = dependencies
		this.state = State.NORMAL
		this.force = False
		this.default = kw.get("default", False)
		this.export = kw.get("export", True)
		this.pure = kw.get("pure", False)
		this.input = kw.get("input", None)
		this.output = kw.get("output", [])
		this.inputFiles = []
		this.outputFiles = []

	def __call__(this, *args, **kw):
		if not kw and len(args) == 1 and callable(args[0]):
			tasks.pop(this.name)
			return registerTask(*args, [this.fn], kw)

		return this.fn()

	for state in State:
		vars()[state.name.lower()] = property(functools.partial(lambda this, state: this.state == state, state = state))

def first(iterator):
	return next(iterator, None)

def findTask(task: str | Runnable | Task, error = True, convert = True, command = False) -> Optional[Task]:
	if isinstance(task, Task): return task

	if match := first(t for t in tasks.values() if task in [t, t.fn, t.name] and (not command or t.export)): return match

	if match := first(t for t in tasks.values() if task == t.name + "!" and (not command or t.export)):
		match.force = True
		return match

	if convert and callable(task): return registerTask(task, kw = {"export": False, "pure": True})
	if error: return exit(print(f'No task matched {task!r}.'))

def registerTask(fn: Runnable, dependencies: list = [], kw = {}):
	task = Task(fn, [findTask(d) for d in dependencies], kw)
	tasks[task.name if task.export else task] = task
	return task

def task(*args, **kw):
	if kw or len(args) != 1 or not callable(args[0]) or isinstance(args[0], Task):
		return lambda fn: registerTask(fn, args, kw)

	return registerTask(*args, [], kw)

def parameter(name: str, default = None, require = False):
	assert isinstance(name, str), f"Parameter name ({name!r}) must be a string."
	value = parameters.get(name, default)
	if not value and require: exit(print(f'Parameter "{name}" must be set.'))
	return value

def join(args: Iterable[str]):
	return " ".join(args)

def sh(commandLine: str, *args, shell = True, text = True, **kwargs):
	if isinstance(commandLine, Arguments): commandLine = str(commandLine)
	return subprocess.run(commandLine, *args, shell = shell, text = text, **kwargs)

def main():
	erred = False

	def error(task: Optional[Task], message: str = None):
		nonlocal erred
		erred = not print(f"Task {task.name}: {message}." if message else task)

	for task in tasks.values():
		if not isinstance(task.default, bool): error(task, f"default ({task.default!r}) is not a bool")
		if not isinstance(task.export, bool): error(task, f"export ({task.export!r}) is not a bool")

	cmdTasks = [findTask(task, command = True) or task for task in args[:split]]

	if [not error(f'"{task}" does not match an exported task') for task in cmdTasks if isinstance(task, str)]:
		print("Exported tasks are listed below.", *(name for name, task in tasks.items() if isinstance(name, str)), sep = "\n")

	if erred: return

	started = False
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

	def run(task: Task, parent: Task = None):
		if task.running: error(f'Circular dependency detected between tasks "{parent.name}" and "{task.name}".')
		if not task.normal: return

		task.state = State.RUNNING
		skip = True

		for dependency in task.dependencies:
			run(dependency, task)
			if dependency.done and not dependency.pure: skip = False

		if task.input:
			def flatten(inputs):
				if inspect.isroutine(inputs): inputs = inputs()

				if isinstance(inputs, Files): task.inputFiles.extend(inputs.files)
				elif isinstance(inputs, Mapping): inputs = list(inputs.values())
				elif isinstance(inputs, Iterable) and not isinstance(inputs, Sequence): inputs = list(inputs)

				if isinstance(inputs, Sequence) and not isinstance(inputs, str):
					for i, input in enumerate(inputs):
						inputs[i] = flatten(input)

				return inputs

			task.input = [flatten(task.input or 0), [os.path.getmtime(input) for input in task.inputFiles]]

		if task.output:
			def flatten(output):
				if isinstance(output, str): task.outputFiles.append(output)
				elif isinstance(output, Mapping): flatten(output.values())
				elif isinstance(output, Iterable):
					for o in output: flatten(o)
				elif callable(output): flatten(output())
				else: error(task, f"{output!r} is not a file (a string, iterable, or callable)")

			flatten(task.output)

		if [not error(task, f'input file "{input}" does not exist') for input in task.inputFiles if not path.exists(input)]:
			exit()

		if (skip and not task.force and task.input == cache.get(task.name, None)
		and (task.input != None or task.outputFiles) and all(path.exists(output) for output in task.outputFiles)):
			task.state = State.SKIPPED
			return

		nonlocal started
		if started: print()
		else: started = True
		print(">", task.name)
		task.fn()
		task.state = State.DONE

	if cmdTasks:
		for task in cmdTasks: run(task)
	else:
		for task in tasks.values():
			if task.default: run(task)

	for task in tasks.values():
		if task.done:
			cache[task.name] = task.input

	with open(CACHE, "bw") as file:
		pickle.dump(cache, file)

exports = {export.__name__: export for export in [bt, Arguments, Files, Task, join, parameter, sh, task]}
frames = inspect.getouterframes(inspect.currentframe())[1:]

if importer := first(f for f in frames if f.frame.f_code.co_code[f.frame.f_lasti] in [0x6b, 0x6c]):
	for name, export in exports.items():
		importer.frame.f_globals[name] = export

tasks: dict[str, Task] = {}
parameters: dict[str, str] = {}

args = sorted(sys.argv[1:], key = lambda a: "=" in a)
split = next((i for i, a in enumerate(args) if "=" in a), len(args))
parameters.update(arg.split("=", 2) for arg in args[split:])

mainPath = path.realpath(sys.argv[0])
mainDirectory = path.dirname(mainPath)

if "MAIN" in globals():
	if entry := first(entry for entry in ["bs", "bs.py"] if path.exists(entry)):
		sys.path.append(mainDirectory if path.isdir(mainPath) else path.dirname(mainDirectory))
		with open(entry) as script: exec(compile(script.read(), path.abspath(entry), "exec"), exports)
	else: exit(print("No build script (bs or bs.py) was found."))

	main()
else:
	os.chdir(mainDirectory)
	caller = threading.current_thread()
	thread = threading.Thread(target = lambda: (caller.join(), main()), daemon = False)
	thread.start()
	hook, threading.excepthook = threading.excepthook, lambda args: thread._stop() if args.thread == caller else hook(args)
