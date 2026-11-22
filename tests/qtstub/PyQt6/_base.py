"""Spoločný základ náhrady Qt."""
from __future__ import annotations

import weakref


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return EnumNS(cls.__name__).__getattr__(name)


class Dummy(metaclass=_Meta):
    """Prijme čokoľvek; každé volanie vráti ďalší Dummy."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: Dummy()

    def __call__(self, *a, **k):
        return Dummy()

    def __bool__(self):
        return True

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __iter__(self):
        return iter(())

    def __or__(self, o):
        return self

    __ror__ = __and__ = __rand__ = __or__

    def __invert__(self):
        return self

    def __add__(self, o):
        return o if isinstance(o, (int, float)) else self

    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __add__


class EnumNS:
    """Qt.AlignmentFlag.AlignLeft a pod. – stabilné celé čísla podľa mena."""
    _cache: dict = {}

    def __init__(self, path=""):
        self._path = path

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        key = f"{self._path}.{name}"
        if key not in EnumNS._cache:
            EnumNS._cache[key] = Flag(len(EnumNS._cache) + 1, key)
        return EnumNS._cache[key]


class Flag(int):
    def __new__(cls, v, name):
        o = int.__new__(cls, 1 << (v % 60))
        o.name = name
        return o

    def __getattr__(self, name):          # Flag sa dá použiť aj ako menný priestor (Qt.ColorScheme.Dark)
        if name.startswith("__"):
            raise AttributeError(name)
        return EnumNS(self.name).__getattr__(name)

    def __or__(self, o):
        return int(self) | int(o)

    __ror__ = __or__

    def __and__(self, o):
        return int(self) & int(o)

    def __invert__(self):
        return ~int(self)


class BoundSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot, *a):
        self._slots.append(slot)

    def disconnect(self, *a):
        self._slots.clear()

    def emit(self, *args):
        for s in list(self._slots):
            s(*args[:_max_args(s, len(args))])     # PyQt zahodí argumenty, ktoré slot neprijme


def _max_args(fn, n):
    import inspect
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return n
    count = 0
    for p in sig.parameters.values():
        if p.kind == p.VAR_POSITIONAL:
            return n
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            count += 1
    return min(n, count)


class pyqtSignal:
    def __init__(self, *types, **k):
        self._name = None

    def __set_name__(self, owner, name):
        self._name = "_sig_" + name

    def __get__(self, obj, owner):
        if obj is None:
            return self
        d = obj.__dict__
        if self._name not in d:
            d[self._name] = BoundSignal()
        return d[self._name]


class QObject(metaclass=_Meta):
    _all = weakref.WeakSet()

    def __init__(self, parent=None, *a, **k):
        self._parent = parent if isinstance(parent, QObject) else None
        self._children = []
        if self._parent is not None:
            self._parent._children.append(self)
        self._name = ""
        self._props = {}
        QObject._all.add(self)

    def __getattr__(self, name):
        if name.startswith("__") or name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: Dummy()

    def parent(self):
        return self._parent

    def setParent(self, p):
        self._parent = p
        if p is not None:
            p._children.append(self)

    def setObjectName(self, n):
        self._name = n

    def objectName(self):
        return self._name

    def setProperty(self, k, v):
        self._props[k] = v

    def property(self, k):
        return self._props.get(k)

    def deleteLater(self):
        pass

    def findChildren(self, cls=None, *a):
        out = []
        for c in self._children:
            if cls is None or isinstance(c, cls):
                out.append(c)
            out.extend(c.findChildren(cls))
        return out

    def findChild(self, cls, name=""):
        for c in self.findChildren(cls):
            if not name or c.objectName() == name:
                return c
        return None

    destroyed = pyqtSignal()
