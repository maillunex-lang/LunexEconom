"""Modules register independent routes, migrations, tick handlers and flags."""
from dataclasses import dataclass, field

@dataclass
class Registry:
    routes: dict = field(default_factory=dict)
    modules: list = field(default_factory=list)
    tick_handlers: dict = field(default_factory=lambda: {'daily': [], 'monthly': []})
    flags: dict = field(default_factory=dict)
    flag_constraints: dict = field(default_factory=dict)

    def route(self, method, path, handler):
        key = (method.upper(), path)
        if key in self.routes:
            raise ValueError('Duplicate route: ' + str(key))
        self.routes[key] = handler

    def tick(self, kind, name, handler, order=100):
        if kind not in self.tick_handlers or any(n == name for _,n,_ in self.tick_handlers[kind]):
            raise ValueError('Duplicate/invalid tick: ' + name)
        if isinstance(order,bool) or not isinstance(order,int):
            raise ValueError('tick order must be integer')
        self.tick_handlers[kind].append((order,name,handler))

    def flag(self, name, default, min_value=None, max_value=None):
        if name in self.flags:
            raise ValueError('Duplicate flag: ' + name)
        self.flags[name] = default
        self.flag_constraints[name] = [min_value,max_value] if min_value is not None or max_value is not None else None

    def add(self, module):
        module.register(self)
        self.modules.append(module)

    def dispatch(self, method, path, body, context):
        handler = self.routes.get((method.upper(),path))
        if handler is None and (path.startswith('/enterprises/') or path.startswith('/admin/enterprises/')):
            import re
            for (verb, template), candidate in self.routes.items():
                if verb != method.upper() or '{id}' not in template:
                    continue
                regex = '^' + re.escape(template).replace(re.escape('{id}'), '(?P<id>[1-9][0-9]*)') + '$'
                match = re.fullmatch(regex,path)
                if match:
                    context['path_params'] = match.groupdict()
                    handler = candidate
                    break
        if handler is None:
            return 404, {'error':'not_found'}
        return handler(body,context)
