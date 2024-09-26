This is a **b**uild **t**ool like Make with Python **b**uild **s**cripts.<br>
Python 3.12 is required.<br>
bt can exist in `PATH` or a project's subdirectory (a Git submodule for example).

```py
options = ["-std=c2x", "-trigraphs", "-Ofast"]
main = "main.c"

@task(export = False, output = main)
def generateSource():
	sh(f"""echo '
		#include <stdio.h>
		int main() {'{puts("foo bar");}'}' > {main}
	""")

@task(generateSource, default = True, output = main)
def compile():
	sh(Arguments("gcc -o main", options, generateSource.outputFiles))

@task(compile)
def run():
	sh("./main")
```
```sh
$ bt run
> generateSource

> compile

> run
foo bar

$ bt run
> run
foo bar
```

### Overview
The execution of bt is always accompanied by a build script.
bt lets the build script run and define [tasks](#tasks) and do any other setup.
When the build script exits, bt takes over.
It looks at the command line arguments that were passed and sets [parameters](#parameter) and determines which tasks to run.
Before running a task, bt runs all of its [dependencies](#dependencies) which may include tasks and callables.
Since tasks can take long, bt provides facilities for [caching](#cache) them so that they don't have to run every time.

### Running
bt can be run in 2 ways:
1. As an executable as seen above. The build script has to be in the current directory and named `bs` or `bs.py`.
2. As a library. In this case the build script is the main module and imports bt. bt starts when the build script ends.
This option allows people that don't have bt installed to use it.
The example below assumes that bt is cloned in the current directory.
```py
# ./build
#!/bin/env python
import bt

@task
def alfa():
	print("foo")
```
```sh
$ ./build alfa
> alfa
foo
```
If this build script is named `bs` or `bs.py` instead, then it additionally can be run by `bt` as in the first way.

### Usage
bt takes as arguments names of tasks to run and `name=value` pairs which set [parameters](#parameter) for the build.

### Tasks
Tasks are functions that can be run on demand from the command line or as [dependencies](#dependencies) of other tasks.<br>
A function can be declared a task by using the decorator `@task`. The task's name is the function's name.
```py
@task
def bravo():
	print("bar")
```
This declares a task `bravo` that prints `"bar"`.
```sh
$ bt bravo
> bravo
bar
```

#### Dependencies
Any non-keyword argument to `task` is considered as a dependency which may be another task or its name or a callable.
Before a task runs, its dependencies run first.

```py
@task
def charlie(): pass

@task(charlie)
def delta(): pass
```
Here `charlie` will always run before `delta`.
```sh
$ bt delta
> charlie

> delta

$ bt delta charlie
> charlie

> delta
```

#### Defaults
`task`'s parameter `default` controls whether the task runs when the command line has not specified any tasks.
```py
@task(default = True)
def echo():
	print("baz")
```
bt automatically runs `echo` when the user has not selected any tasks.
```sh
$ bt
> echo
baz
```

#### Exports
Any task can be run from the command line by default. This can be changed by the option `export`.
```py
@task(default = True, export = False)
def foxtrot():
	print("foo")
```
This will make `foxtrot` run by default but not runnable explicitly.
```sh
$ bt foxtrot
No task matched 'foxtrot'.
```

#### Cache
Inputs and outputs are objects that determine whether a task should be skipped.
Inputs may be anything and outputs are only files.
They can be modified through the options `input` and `output`.

If a task does not have inputs or outputs, then it is never skipped.
A task that has inputs or outputs is skipped only if its inputs have not changed, its outputs all exist, and its dependencies all either are [pure](#pure-tasks) or have been skipped.

Before bt exits, the `input` of every task that ran is written to a cache.
When a task is about to run, its `input` is checked against that in the cache: if they differ, then they have changed and the task runs.

File modification is tracked by mtime. If an input file does not exist, then an error is raised.

#### Input
```py
@task(input = "baz")
def golf(): pass
```
This task will run only once ever: Since `input` has not been cached before the first run, `golf` is run once.
Thereafter whenever the task is about to run, since `input` does not change, it matches the cached version and `golf` is skipped.
Therefore `golf` runs only once.
```sh
$ bt golf
> golf
$ bt golf
```

```py
@task(input = Files("foo"))
def hotel(): pass
```
When this task is called, it runs if this time is the first or `foo`'s mtime changed.
```sh
$ touch foo
$ bt hotel
> hotel
$ bt hotel
$ touch foo
$ bt hotel
> hotel
```

#### Output
```py
@task(output = "foo")
def india():
	sh("touch foo")
```
This task will be skipped if `foo` exists.
```sh
$ bt india
> india
$ bt india
```

#### Ignoring the cache
A task can be forced to run by passing as an argument its name suffixed by `!`.
```py
@task(default = True, input = 0)
def juliett(): pass

@task(juliett, input = 0)
def kilo(): pass

@task(kilo, input = 0)
def lima(): pass
```
```sh
$ bt lima
> juliett

> kilo

> lima

$ bt kilo
$ bt kilo!
> kilo
```

Passing `!` forces all initial tasks to run.
```sh
$ bt !
> juliett

$ bt kilo !
> kilo
```

Passing `!` twice forces all required tasks to run.
```sh
$ bt ! !
> juliett

$ bt kilo ! !
> juliett

> kilo
```

#### Pure tasks
Pure tasks act like they don't have side effects: their execution does not prevent tasks that depend on them from being skipped.

```py
@task(pure = True)
def mike(): pass

@task(mike, input = 0)
def november(): pass
```
When `november` is called after the first run, it will be skipped but `mike` will run.
```sh
$ bt november
> mike

> november

$ bt november
> mike
```

### API
Importing or running bt gives a build script direct access to module `bt`,
classes [`Arguments`](#arguments) and [`Files`](#files),
and functions [`parameter`](#parameter), [`sh`](#sh), and `task`.

#### `parameter`
A parameter `name` can be set to `"value"` by passing `name=value` in the command line.

The function `parameter(name, default = None, require = False)` allows the build script to read parameter values.
If the parameter is not set, then
- if `require`, then an error message is printed and the build is terminated
- otherwise `default` is returned.

#### `sh`
bt exports function `sh` for running shell commands.
`sh` forwards its parameters to `subprocess.run` and sets `shell = True` and `text = True` by default.
If the command line is an [`Arguments`](#arguments), then it is converted into a string.
```py
sh("tr ab ba", input = "abr abz")
```

#### `Arguments`
`Arguments` is a `list` derivative that stores a full or partial command line.
It flattens every added `Iterable`. Supported element types are `str` and `Iterable`.
Its string representation joins its elements with spaces.
Its method `split` splits its string representation into a list.
```py
source = ["main.c"]
exe = "foo"
options = ["-Ofast", "-std=c2x"]
sh(Arguments("gcc", source, "-o", exe, options))
```
