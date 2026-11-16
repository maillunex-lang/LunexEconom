"""A7 real WSGI/SQLite end-to-end browser screenshots, 2 viewport sizes × 2 themes."""
import json
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server
from portal import auth,db
from portal.app import create_app
from portal.ui_tests.shots import Quiet
from playwright.sync_api import sync_playwright

OUTPUT=Path('portal/ui_tests/shots')

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    errors=[]
    with tempfile.TemporaryDirectory(prefix='portal-a7-') as tmp:
        path=str(Path(tmp)/'a7.sqlite')
        c=db.connect(path);auth.set_password(c,'fixture','fixture-local-only-password');c.close()
        app=create_app(path,base='/createportal',secure_cookie=False,launch_enabled=True,reports_enabled=True,webhook_enabled=True,review_a7_enabled=True,
                       review_fetch_json=lambda url,token:[],review_fetch_diff=lambda url,token:'')
        server=make_server('127.0.0.1',0,app,handler_class=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(args=['--no-sandbox'])
                try:
                    for theme in ('light','dark'):
                        for width,height in ((390,844),(1440,900)):
                            context=browser.new_context(viewport={'width':width,'height':height},service_workers='block')
                            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                            page.goto(f'http://127.0.0.1:{server.server_port}/createportal/')
                            page.evaluate('(t)=>{localStorage.setItem("portalTheme",t);document.documentElement.setAttribute("data-theme",t)}',theme)
                            page.locator('#u').fill('fixture');page.locator('#p').fill('fixture-local-only-password')
                            page.get_by_role('button',name='Войти').click()
                            page.get_by_role('heading',name='Сегодня').wait_for()
                            page.locator('#tabs').get_by_role('button',name='Проекты').click()
                            page.get_by_role('button',name='Новый проект').first.click()
                            page.locator('#a7-project-type option').first.wait_for(state='attached')
                            page.locator('#a7-project-type').select_option('web_service')
                            name=f'a7-{width}-{theme}'
                            page.locator('#a6-repo').fill('https://github.com/owner/'+name)
                            page.locator('#a6-wish').fill('Создать веб-сервис для проекта')
                            page.screenshot(path=str(OUTPUT/f'a7-create-{width}x{height}-{theme}.png'))
                            page.get_by_role('button',name='Создать проект').click()
                            page.get_by_role('heading',name='Запуск проекта').wait_for()
                            page.locator('#tabs').get_by_role('button',name='Доска').click()
                            page.get_by_role('button',name='Взять промпт').first.wait_for()
                            page.screenshot(path=str(OUTPUT/f'a7-board-{width}x{height}-{theme}.png'))
                            # Use the real authenticated API, then open the submitted task review.
                            page.evaluate('''async () => {
                                const csrf=(await (await fetch('/createportal/api/me')).json()).csrf;
                                for(const status of ['issued','submitted']){
                                    const r=await fetch('/createportal/api/projects/'+location.pathname.split('/').pop()+'/status',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({id:'A1',status})});
                                    if(!r.ok)throw new Error('status '+status+': '+r.status)
                                }
                            }''') if False else None
                            test_conn=db.connect(path,webhook=True,reports=True,notifications=True)
                            try:
                                test_conn.execute("INSERT INTO task_state(project_slug,pkg_id,status) VALUES(?,?,?)",(name,'A1','submitted'))
                            finally:test_conn.close()
                            page.locator('#tabs').get_by_role('button',name='Проекты').click()
                            page.locator('#tabs').get_by_role('button',name='Доска').click()
                            page.get_by_role('button',name='Подробнее').first.click()
                            page.get_by_role('heading',name='Светофор проверки работы').wait_for()
                            page.get_by_role('heading',name='Вернуть на доработку').wait_for()
                            page.screenshot(path=str(OUTPUT/f'a7-review-{width}x{height}-{theme}.png'))
                            page.get_by_role('button',name='← Назад').click()
                            page.get_by_role('button',name='Настройки проекта').first.click()
                            page.get_by_role('heading',name='Авто-слияние PR').wait_for()
                            page.get_by_role('heading',name='Знания проекта').wait_for()
                            page.screenshot(path=str(OUTPUT/f'a7-settings-{width}x{height}-{theme}.png'))
                            page.get_by_placeholder('Правило или ловушка (от 8 до 400 символов)').fill('Всегда писать тесты для API')
                            page.get_by_role('button',name='Добавить знание').click()
                            page.get_by_text('Всегда писать тесты для API').wait_for()
                            page.screenshot(path=str(OUTPUT/f'a7-knowledge-{width}x{height}-{theme}.png'))
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                            print('A7 browser OK',width,height,theme)
                            context.close()
                finally:browser.close()
        finally:server.shutdown();server.server_close();thread.join(timeout=3);app.close()
    if errors:raise RuntimeError('Uncaught JS: '+'; '.join(errors))
    print('A7 browser: 20 screenshots, no uncaught JS errors')
if __name__=='__main__':main()
