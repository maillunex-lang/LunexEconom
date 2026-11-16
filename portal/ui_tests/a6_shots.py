"""A6 real local WSGI -> browser: launch, create, more, mobile header, offline fallback."""
import argparse
import os
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

from portal import auth, db
from portal.app import create_app
from portal.ui_tests.shots import Quiet
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('portal/ui_tests/shots'))
    opts=parser.parse_args()
    opts.output.mkdir(parents=True,exist_ok=True)
    errors=[]
    with tempfile.TemporaryDirectory(prefix='portal-a6-') as temp:
        dbpath=os.path.join(temp,'a6.sqlite')
        c=db.connect(dbpath)
        auth.set_password(c,'fixture','fixture-local-only-password')
        c.close()
        app=create_app(dbpath,base='/createportal',secure_cookie=False,launch_enabled=True)
        server=make_server('127.0.0.1',0,app,handler_class=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(args=['--no-sandbox'])
                try:
                    for theme in ('light','dark'):
                        for width,height in ((390,844),(1440,900)):
                            context=browser.new_context(viewport={'width':width,'height':height},service_workers='block')
                            page=context.new_page()
                            page.on('pageerror',lambda e: errors.append(str(e)))
                            page.goto(f'http://127.0.0.1:{server.server_port}/createportal/')
                            page.evaluate('(t)=>{localStorage.setItem("portalTheme",t);document.documentElement.setAttribute("data-theme",t)}',theme)
                            page.locator('#u').fill('fixture')
                            page.locator('#p').fill('fixture-local-only-password')
                            page.get_by_role('button',name='Войти').click()
                            page.get_by_role('heading',name='Сегодня').wait_for()
                            page.locator('#tabs').get_by_role('button',name='Проекты').click()
                            page.get_by_role('heading',name='Мои проекты').wait_for()
                            page.get_by_role('button',name='Новый проект').first.click()
                            repo_name=f'demo-a6-{width}-{theme}'
                            page.locator('#a6-repo').fill('https://github.com/owner/'+repo_name+'.git')
                            assert page.locator('#a6-name').input_value()==repo_name
                            page.locator('#a6-wish').fill('Кооперативная игра на 4 игроков для Android')
                            page.screenshot(path=str(opts.output/f'a6-create-{width}x{height}-{theme}.png'))
                            page.get_by_role('button',name='Создать проект').click()
                            page.wait_for_timeout(300)
                            if not page.get_by_role('heading',name='Запуск проекта').count():
                                print('CREATE ERROR:',page.locator('#app').inner_text()[:1400],flush=True)
                            page.get_by_role('heading',name='Запуск проекта').wait_for()
                            page.get_by_role('heading',name='Скопировать промпт директору').wait_for()
                            assert page.locator('.a6-step').count()==4
                            assert page.locator('.a6-step.current').count()==1
                            page.locator('.a6-step').first.get_by_text('Показать текст').click()
                            assert 'Кооперативная игра' in page.locator('.a6-step pre').inner_text()
                            page.screenshot(path=str(opts.output/f'a6-launch-{width}x{height}-{theme}.png'))
                            page.locator('#tabs').get_by_role('button',name='Сегодня').click()
                            page.get_by_role('button',name='Продолжить запуск проекта').wait_for()
                            page.screenshot(path=str(opts.output/f'a6-today-{width}x{height}-{theme}.png'))
                            for tab in ('Доска','Проекты','Ещё'):
                                page.locator('#tabs').get_by_role('button',name=tab).click()
                                assert page.locator('[data-screen-title]').inner_text().strip(),tab
                            page.get_by_role('button',name='Развитие портала').click()
                            page.get_by_role('heading',name='Развитие портала').wait_for()
                            page.get_by_role('button',name='Скопировать инструкцию директору').wait_for(state='visible')
                            page.get_by_role('button',name='Скопировать инструкцию директору').wait_for(state='attached')
                            page.get_by_text("Инструкция загружена.").wait_for()
                            assert page.get_by_role('button',name='Скопировать инструкцию директору').is_enabled()
                            page.screenshot(path=str(opts.output/f'a6-guide-{width}x{height}-{theme}.png'))
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                            # Network errors are visible, never treated as saved changes.
                            page.route('**/api/portal-dev-guide',lambda route:route.abort())
                            page.locator('#tabs').get_by_role('button',name='Ещё').click()
                            page.get_by_role('button',name='Развитие портала').click()
                            page.get_by_text('Инструкция не загружена',exact=False).wait_for()
                            print('A6 OK',width,height,theme)
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3);app.close()
    if errors:raise RuntimeError('JS errors: '+'; '.join(errors))
    print('A6 browser: 16 snapshots, no uncaught JS errors')

if __name__=='__main__':main()
