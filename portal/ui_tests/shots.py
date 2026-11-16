"""B1 headless Chromium snapshots on an isolated in-memory-lifecycle SQLite DB.

Usage: python3 portal/ui_tests/shots.py [--output DIR]
Requires Playwright Python API + Chromium, installed outside project dependencies.
No production DB, credentials, or remote services are accessed.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from portal import auth, db
from portal.app import create_app
from portal.bootstrap import STARTER_PLAN


class Quiet(WSGIRequestHandler):
    def log_message(self, *_args):
        pass


def seed(path: str) -> None:
    """Independent deterministic fixture: 6 steps in each lane, different statuses."""
    conn = db.connect(path)
    auth.set_password(conn, "fixture", "fixture-local-only-password")
    plan = json.loads(json.dumps(STARTER_PLAN))
    plan['project'] = {'name': 'Тестовая доска', 'repo': 'example/sample', 'branch': 'main'}
    plan['packages'] = []
    names_a = ['Глубокие цепочки', 'Управление объектами', 'Кредиты и налоги',
               'Слои населения', 'Персонал и исследования', 'Надёжность']
    names_b = ['Основа клиента', 'Экран обновлений', 'Карта мира',
               'Магазины', 'Поставщики', 'Проверка интерфейса']
    for lane, names in [('A', names_a), ('B', names_b)]:
        for idx, name in enumerate(names, 1):
            pkg_id = f'{lane}{idx}'
            plan['packages'].append({'id': pkg_id, 'lane': lane, 'step': idx, 'title': name,
                'goal': 'Выполнить тестовый этап ' + name, 'done_when': ['Проверки прошли'],
                'depends_on': [f'{lane}{idx - 1}'] if idx > 1 else [],
                'gdd': ['03'], 'zone_extra': [], 'status': 'planned', 'size': 'M'})
    conn.execute("INSERT INTO projects(slug,name,repo,description,plan_json,created) VALUES(?,?,?,?,?,?)",
                 ('fixture-board', 'Тестовая доска', 'example/sample', '', json.dumps(plan, ensure_ascii=False), 1))
    for pkg_id, status in [('A1', 'accepted'), ('A2', 'issued'), ('B1', 'accepted'), ('B2', 'submitted')]:
        conn.execute('INSERT INTO task_state(project_slug,pkg_id,status) VALUES(?,?,?)',
                     ('fixture-board', pkg_id, status))
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('portal/ui_tests/shots'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit('Установите Playwright Python API и Chromium в изолированное окружение.') from exc
    with tempfile.TemporaryDirectory(prefix='portal-b1-') as tmp:
        db_path = os.path.join(tmp, 'test.sqlite')
        seed(db_path)
        application = None
        # WSGI app keeps its SQLite connection; create and serve in one dedicated thread.
        class SingleThreadServer(WSGIServer):
            pass
        server = make_server('127.0.0.1', 0, lambda *_: [], server_class=SingleThreadServer, handler_class=Quiet)
        def serve():
            nonlocal application
            application = create_app(db_path, base='/createportal', secure_cookie=False)
            server.set_app(application)
            try: server.serve_forever()
            finally: application.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/createportal/'
        errors = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
                try:
                    for theme in ['light', 'dark']:
                        for width, height in [(390, 844), (1440, 900)]:
                            context = browser.new_context(viewport={'width': width, 'height': height},
                                                          device_scale_factor=1, service_workers='block')
                            page = context.new_page()
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            # The initial /api/me 401 is expected before login.
                            page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' and '401 (Unauthorized)' not in msg.text else None)
                            page.goto(url)
                            page.evaluate('(theme) => { localStorage.setItem("portalTheme", theme); document.documentElement.setAttribute("data-theme", theme) }', theme)
                            page.locator('#u').wait_for()
                            fields = page.locator('input')
                            fields.nth(0).fill('fixture')
                            fields.nth(1).fill('fixture-local-only-password')
                            page.get_by_role('button', name='Войти').click()
                            page.get_by_role('button', name='Открыть доску').first.wait_for(timeout=10000)
                            page.get_by_role('button', name='Открыть доску').first.click()
                            page.locator('.phone-board').wait_for(state='attached')
                            if width == 390:
                                assert page.locator('.phone-switch').is_visible()
                                assert page.locator('.phone-bottom-actions').is_visible()
                                assert page.locator('.phone-parallel').is_visible()
                                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Горизонтальный скролл'
                            else:
                                assert page.locator('.lgrid').is_visible(), 'Нет дорожек на компьютере'
                            name = f'board-{width}x{height}-{theme}.png'
                            page.screenshot(path=str(args.output / name), full_page=False)
                            print('OK', name)
                            if width == 390:
                                page.locator('.phone-switch button').nth(2).click()
                                assert page.locator('.phone-pair').first.is_visible()
                                page.screenshot(path=str(args.output / f'board-{width}x{height}-{theme}-both.png'))
                                print('OK', f'board-{width}x{height}-{theme}-both.png')
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    if errors:
        raise SystemExit('Ошибки консоли браузера:\n' + '\n'.join(errors))
    print('Консоль браузера: без ошибок')


if __name__ == '__main__':
    main()
