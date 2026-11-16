"""B2 headless browser checks with isolated B1 SQLite fixture and HTTP response mocks."""
from __future__ import annotations
import argparse
import json
import os
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
from portal.app import create_app
from portal.ui_tests.shots import seed

class Quiet(WSGIRequestHandler):
    def log_message(self, *_): pass

MOCK_PR = {'number':112, 'branch':'portal/b2-settings-ci', 'sha':'3f9c2a1', 'url':'https://github.com/maillunex-lang/LunexEconom/pull/112','merged':True,'auto_accepted':True}
MOCK_CI = {'status':'success', 'checks':[{'name':'server test','status':'success'},{'name':'client smoke','status':'success'},{'name':'website','status':'success'}]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('portal/ui_tests/shots'));args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix='portal-b2-') as tmp:
        path=os.path.join(tmp,'fixture.sqlite');seed(path)
        server=make_server('127.0.0.1',0,lambda *_: [],server_class=WSGIServer,handler_class=Quiet)
        def serve():
            app=create_app(path,base='/createportal',secure_cookie=False);server.set_app(app)
            try:server.serve_forever()
            finally:app.close()
        worker=threading.Thread(target=serve,daemon=True);worker.start()
        errors=[]
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
                try:
                    for theme in ('light','dark'):
                        for width,height in ((390,844),(1440,900)):
                            context=browser.new_context(viewport={'width':width,'height':height},service_workers='block')
                            page=context.new_page()
                            page.on('pageerror',lambda error:errors.append(str(error)))
                            page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' and '401 (Unauthorized)' not in msg.text else None)
                            def mock(route):
                                u=route.request.url
                                if u.endswith('/api/audit'):
                                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'events':[{'ts':1794828000,'action':'Вход в портал'},{'ts':1794828200,'action':'План синхронизирован'}]}));return
                                if u.endswith('/settings') and '/api/projects/' in u:
                                    if route.request.method=='POST':
                                        incoming=route.request.post_data_json
                                        route.fulfill(status=200,content_type='application/json',body=json.dumps({'settings':incoming}));return
                                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'settings':{'auto_accept':False,'auto_accept_require_checklist':False}}));return
                                if u.endswith('/api/projects/fixture-board'):
                                    response=route.fetch();data=response.json();data['state']['A1'].update({'merged':True,'sha':'3f9c2a1','pr':MOCK_PR,'ci':MOCK_CI});data['state']['B2'].update({'pr':{'number':114,'branch':'portal/b2','sha':'cafe123','url':'https://github.com/maillunex-lang/LunexEconom/pull/114'},'ci':{'status':'pending','checks':[{'name':'server test','status':'pending'}]}})
                                    route.fulfill(status=200,content_type='application/json',body=json.dumps(data));return
                                route.continue_()
                            page.route('**/createportal/api/**',mock)
                            page.goto(f'http://127.0.0.1:{server.server_port}/createportal/')
                            page.evaluate('(theme) => {localStorage.setItem("portalTheme",theme);document.documentElement.setAttribute("data-theme",theme)}',theme)
                            page.locator('#u').fill('fixture');page.locator('#p').fill('fixture-local-only-password');page.get_by_role('button',name='Войти').click()
                            page.get_by_role('button',name='Открыть доску').first.wait_for()
                            page.get_by_role('button',name='Настройки и безопасность портала').click()
                            page.get_by_role('heading',name='Журнал аудита').wait_for()
                            page.get_by_text('План синхронизирован').wait_for()
                            assert page.locator('.b2-field input').count()==3
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(args.output/f'b2-settings-{width}x{height}-{theme}.png'))
                            print('OK settings',width,theme)
                            page.locator('button.brand').click()
                            page.get_by_role('button',name='Открыть доску').first.click()
                            page.get_by_role('button',name='Настройки проекта').locator('visible=true').first.click()
                            page.get_by_text('Настройки загружены.').wait_for()
                            page.get_by_label('Автоприёмка при слиянии').check();page.get_by_label('Требовать чек-лист').check()
                            page.get_by_role('button',name='Сохранить настройки').click()
                            page.get_by_text('Настройки сохранены.').wait_for()
                            page.screenshot(path=str(args.output/f'b2-project-{width}x{height}-{theme}.png'))
                            print('OK project',width,theme)
                            page.get_by_role('button',name='К доске').click();page.locator('.node').first.wait_for(state='attached')
                            if width==390:
                                page.evaluate("() => { document.querySelector('.node')?.click() }")
                            else:page.locator('.node').filter(has_text='A1').first.click()
                            page.locator('.b2-pr h3').wait_for(state='attached',timeout=6000)
                            assert page.locator('.b2-pr').inner_text().find('Принято автоматически')>=0
                            page.screenshot(path=str(args.output/f'b2-task-{width}x{height}-{theme}.png'))
                            print('OK task',width,theme)
                            page.get_by_role('button',name='Закрыть').last.click(force=True)
                            page.evaluate("() => [...document.querySelectorAll('.node')].find(e=>e.textContent.includes('B2'))?.click()")
                            assert 'Ждём CI' in page.locator('.b2-pr').inner_text()
                            print('OK waiting CI',width,theme)
                            context.close()
                finally:browser.close()
        finally:server.shutdown();server.server_close();worker.join(timeout=3)
    if errors:raise SystemExit('Браузерные ошибки: '+'; '.join(errors))
    print('Консоль браузера: без ошибок')

if __name__=='__main__':main()
