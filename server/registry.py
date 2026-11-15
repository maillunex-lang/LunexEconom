"""Modules register independent routes, migrations, tick handlers and flags."""
from dataclasses import dataclass, field

@dataclass
class Registry:
    routes: dict = field(default_factory=dict)
    modules: list = field(default_factory=list)
    tick_handlers: dict = field(default_factory=lambda: {'daily': [], 'monthly': []})
    flags: dict = field(default_factory=dict)

    def route(self, method, path, handler):
        key = (method.upper(), path)
        if key in self.routes:
            raise ValueError('Duplicate route: ' + str(key))
        self.routes[key] = handler

    def tick(self, kind, name, handler):
        if kind not in self.tick_handlers or any(n == name for n, _ in self.tick_handlers[kind]):
            raise ValueError('Duplicate/invalid tick: ' + name)
        self.tick_handlers[kind].append((name, handler))

    def flag(self, name, default):
        if name in self.flags:
            raise ValueError('Duplicate flag: ' + name)
        self.flags[name] = default

    def add(self, module):
        module.register(self)
        self.modules.append(module)

    def dispatch(self, method, path, body, context):
        handler = self.routes.get((method.upper(), path))
        if handler is None:
            return 404, {'error': 'not_found'}
        return handler(body, context)
