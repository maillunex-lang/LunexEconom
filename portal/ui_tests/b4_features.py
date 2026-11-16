"""B4 additional browser checks: real WSGI routes, notifications and graceful missing API."""
import argparse
import os
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server
from portal.app import create_app
from portal.ui_tests.shots import seed
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('portal/ui_tests/shots'));args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='b4-features-') as tmp:
        db=os.path.join(tmp,'db.sqlite');seed(db)
        server=make_server('127.0.0.1',0,create_app(db,base='/createportal',secure_cookie=False,notifications_enabled=True))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        errors=[]
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(args=['--no-sandbox'])
                for theme in ('light','dark'):
                    for width,height in ((390,844),(1440,900)):
                        ctx=browser.new_context(viewport={'width':width,'height':height},service_workers='block')
                        page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                        page.on('console',lambda m:errors.append(m.text) if m.type=='error' and '401 (Unauthorized)' not in m.text and '404 (Not Found)' not in m.text else None)
                        page.goto(f'http://127.0.0.1:{server.server_port}/createportal/')
                        page.evaluate('(t)=>{localStorage.setItem("portalTheme",t);document.documentElement.setAttribute("data-theme",t)}',theme)
                        page.locator('#u').fill('fixture');page.locator('#p').fill('fixture-local-only-password');page.get_by_role('button',name='Войти').click();page.get_by_role('heading',name='Сегодня').wait_for()
                        page.locator('#tabs').get_by_role('button',name='Ещё').click();page.locator('.b6-more').get_by_role('button',name='Уведомления').click();page.get_by_role('heading',name='Уведомления MAX и Telegram').wait_for()
                        page.get_by_role('button',name='Получить одноразовый код').first.click();page.locator('.b4-code').first.get_by_text(__import__('re').compile(r'\S{4,}')).wait_for(timeout=5000)
                        page.locator('.b4-code').first.evaluate('(e)=>{e.textContent="КОД СКРЫТ"}');page.screenshot(path=str(args.output/f'b4-notifications-{width}x{height}-{theme}.png'))
                        page.locator('#tabs').get_by_role('button',name='Доска').click();page.locator('.node').first.wait_for(state='attached')
                        page.locator('#tabs').get_by_role('button',name='Ещё').click();page.locator('.b6-more').get_by_role('button',name='Граф').click();page.get_by_role('heading',name='Граф зависимостей').wait_for();page.locator('.b4-graph-node').first.wait_for();page.screenshot(path=str(args.output/f'b4-graph-{width}x{height}-{theme}.png'))
                        page.locator('#tabs').get_by_role('button',name='Ещё').click();page.locator('.b6-more').get_by_role('button',name='Поиск').click();page.get_by_role('heading',name='Поиск по задачам и идеям').wait_for();page.get_by_role('textbox',name='Поиск по архиву, задачам и идеям').fill('Экран обновлений');page.get_by_text('B2 · Экран обновлений').wait_for();page.screenshot(path=str(args.output/f'b4-search-{width}x{height}-{theme}.png'))
                        page.locator('#tabs').get_by_role('button',name='Ещё').click();page.locator('.b6-more').get_by_role('button',name='Настройки').click();page.get_by_role('heading',name='Настройки').wait_for();page.get_by_role('button',name='Резервные копии').last.click();page.get_by_role('heading',name='Резервные копии').wait_for();page.screenshot(path=str(args.output/f'b4-backups-{width}x{height}-{theme}.png'))
                        page.goto(f'http://127.0.0.1:{server.server_port}/createportal/#task/A2');page.get_by_role('dialog',name='Управление объектами').wait_for(timeout=7000)
                        assert page.locator('.drawer').get_by_role('button',name='← Назад').count()==1
                        ctx.close();print('OK',width,height,theme)
                browser.close()
        finally:server.shutdown();server.server_close()
        if errors:raise RuntimeError('JS console: '+'; '.join(errors))
        print('B4 features: без ошибок JavaScript')

if __name__=='__main__':main()
