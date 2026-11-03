"""Fresh source modules selected by imports from one custom.py generation."""
import builtins
import importlib
import importlib.machinery
import importlib.util
import os
import sys
import threading
import types
from contextlib import contextmanager
from importlib.abc import Loader
from typing import cast

_import_lock = threading.RLock()


class _NamespaceLoader:
    def __init__(self, generation):
        self.generation = generation

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.generation.modules[module.__name__] = module


class _SourceLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, name, filename, generation):
        super().__init__(name, filename)
        self.generation = generation

    def get_code(self, fullname):
        # Ignore timestamp/size-based pyc caches, including same-second edits.
        return self.source_to_code(self.get_data(self.path), self.path)

    def exec_module(self, module):
        self.generation.modules[module.__name__] = module
        module.__dict__["__builtins__"] = self.generation.builtins
        super().exec_module(module)


class ConfigModules:
    def __init__(self, roots, previous=None):
        self.roots = tuple(os.path.normcase(os.path.realpath(root)) for root in roots)
        self.modules = {}
        self.saved = {}
        self.pending = True
        self.active = True
        self.builtins = dict(vars(builtins), __import__=self.import_module)
        # Only selected sources see this view; leave the shared importlib intact.
        self.importlib = types.ModuleType("importlib")
        if previous is not None:
            for name, module in previous.modules.items():
                if sys.modules.get(name) is module:
                    self.saved[name] = sys.modules.pop(name)
        importlib.invalidate_caches()

    def contains(self, filename):
        if not filename or not filename.endswith(".py"):
            return False
        filename = os.path.normcase(os.path.realpath(filename))
        return any(filename.startswith(root + os.sep) for root in self.roots)

    def local_namespace(self, paths):
        return paths is not None and any(self.contains(os.path.join(path, "__init__.py")) for path in paths)

    def contains_module(self, module):
        filename = getattr(module, "__file__", None)
        return self.contains(filename) or (filename is None and self.local_namespace(getattr(module, "__path__", None)))

    def find_spec(self, fullname, path=None, target=None):
        if not self.active or threading.get_ident() != self.thread:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is not None:
            if self.contains(spec.origin):
                spec.loader = _SourceLoader(fullname, spec.origin, self)
                return spec
            if spec.origin is None and self.local_namespace(spec.submodule_search_locations):
                spec.loader = cast(Loader, _NamespaceLoader(self))
                return spec
        return None

    @contextmanager
    def importing(self):
        with _import_lock:
            self.thread = threading.get_ident()
            sys.meta_path.insert(0, self)
            try:
                yield
            finally:
                sys.meta_path.remove(self)

    def import_module(self, name, globals=None, locals=None, fromlist=(), level=0):
        if not self.active:
            return builtins.__import__(name, globals, locals, fromlist, level)
        if level:
            name = importlib.util.resolve_name("." * level + name, cast(dict, globals)["__package__"])
        with self.importing():
            if not self.active:
                return builtins.__import__(name, globals, locals, fromlist, 0)
            self._prepare_import(name)
            module = builtins.__import__(name, globals, locals, fromlist, 0)
            if module is importlib:
                self.importlib.__dict__.update(vars(importlib), import_module=self.import_dynamic)
                return self.importlib
            return module

    def import_dynamic(self, name, package=None):
        if not self.active:
            return importlib.import_module(name, package)
        if name.startswith("."):
            if not package:
                return importlib.import_module(name, package)
            name = importlib.util.resolve_name(name, package)
        with self.importing():
            if self.active:
                self._prepare_import(name)
            return importlib.import_module(name)

    def _prepare_import(self, name):
        # A previously cached local package must also get a fresh namespace.
        names = name.split(".")
        for index in range(1, len(names) + 1):
            prefix = ".".join(names[:index])
            module = sys.modules.get(prefix)
            if (module is not None and prefix not in self.modules
                    and self.contains_module(module)):
                for key in tuple(sys.modules):
                    if (key == prefix or key.startswith(prefix + ".")) and self.contains_module(sys.modules[key]):
                        cached = sys.modules.pop(key)
                        if self.pending:
                            self.saved.setdefault(key, cached)

    def rollback(self):
        self.active = False
        for name, module in self.modules.items():
            if sys.modules.get(name) is module:
                del sys.modules[name]
        sys.modules.update(self.saved)

    def commit(self, previous):
        self.saved.clear()
        self.pending = False
        if previous is not None:
            previous.active = False
