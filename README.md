This is a **b**uild **t**ool like Make with Python **b**uild **s**cripts.
Python 3.12 or later is required.
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
bt takes as arguments names of tasks to run and `name=value` pairs which set [parameters](#parameters) for the build.

### Tasks
A task can be declared by using `@task`.
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
A task does not run until its dependencies are executed.

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
By default no task is executed so it has to be specified on the command line.
This can be changed by setting `default` in a `task` call.
```py
@task(default = True)
def echo():
	print("baz")
```
Now bt automatically runs `echo` when the user has not selected any tasks.
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

#### Caching
Inputs and outputs are objects that determine whether a task should be skipped.
Inputs may be anything and outputs are only files.
They can be modified through the options `input` and `output`.

If a task does not have inputs or outputs, then it is never skipped.
A task that has inputs or outputs is skipped only if its inputs have not changed, its outputs all exist, and its dependencies all either are [pure](#pure-tasks) or have been skipped.

Before bt exits, the `input` of every task that ran is written to a cache.
When a task is to run again, its `input` is checked against that in the cache: if they differ, then they have changed.

File modification is tracked by mtime. If an input file does not exist, then an error is raised.

```py
@task(input = "baz")
def golf(): pass
```
This task will run only once ever: Since `input` has not been cached before the first run, `golf` is run once. Thereafter whenever the task is about to run, since `input` does not change, it matches the cached version and `golf` is skipped. Therefore `golf` runs only once.
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

#### Pure tasks
Pure tasks act like they don't have side effects: their execution does not prevent tasks that depend on them from being skipped.

```py
@task(pure = True)
def juliett(): pass

@task(juliett, input = 0)
def kilo(): pass
```
When `kilo` is called after the first run, it will be skipped but `juliett` will run.
```sh
$ bt kilo
> juliett

> kilo

$ bt kilo
> juliett
```

### Parameters
A parameter `name` can be set to `"value"` by passing `name=value` in the command line.

The function `parameter(name, default = None, require = False)` allows the build script to read parameter values.
If the parameter is not set, then
- if `require`, then an error message is printed and the build is terminated
- otherwise `default` is returned.

### Command execution
bt exports function `sh` for running shell commands.
`sh` forwards its parameters to `subprocess.run` and sets `shell = True` and `text = True` by default.
If the command line is an [`Arguments`](#arguments), then it is converted into a string.
```py
sh("tr ab ba", input = "abr abz")
```

### `Arguments`
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
