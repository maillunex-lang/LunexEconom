"""B4 end-to-end on isolated real WSGI server; no API mocks or production data."""
import json
import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server
from portal.app import create_app
from portal.ui_tests.shots import seed
from playwright.sync_api import sync_playwright


def main():
    with tempfile.TemporaryDirectory(prefix='b4-e2e-') as temp:
        db=os.path.join(temp,'db.sqlite');seed(db)
        with sqlite3.connect(db) as con:
            plan=json.loads(con.execute("SELECT plan_json FROM projects WHERE slug='fixture-board'").fetchone()[0]);plan['project']['name']='Проверка полного пути'
        server=make_server('127.0.0.1',0,create_app(db,base='/createportal',secure_cookie=False,reports_enabled=True,notifications_enabled=True,webhook_enabled=True))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}/createportal'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(args=['--no-sandbox']);context=browser.new_context(service_workers='block');page=context.new_page()
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/');page.locator('#u').fill('fixture');page.locator('#p').fill('fixture-local-only-password');page.get_by_role('button',name='Войти').click();page.get_by_role('heading',name='Сегодня').wait_for()
                csrf=context.request.get(base+'/api/me').json()['csrf']
                def post(path,body):
                    r=context.request.post(base+path,data=body,headers={'X-CSRF-Token':csrf});assert r.ok,(path,r.status,r.text());return r.json()
                post('/api/projects',{'slug':'b4-endtoend','name':'Проверка полного пути','repo':'example/sample','description':'Только локальный тест'})
                post('/api/projects/b4-endtoend/plan',{'plan':plan})
                for status in ('issued','submitted'):
                    post('/api/projects/b4-endtoend/status',{'id':'A1','status':status})
                post('/api/projects/b4-endtoend/tasks/A1/report',{'text':'Результат тестовой работы; тесты выполнены'})
                review=context.request.get(base+'/api/projects/b4-endtoend/tasks/A1/review').json()['review']
                post('/api/projects/b4-endtoend/tasks/A1/review',{'items':[{'text':x['text'],'checked':True} for x in review['items']],'ci_state':'success'})
                post('/api/projects/b4-endtoend/status',{'id':'A1','status':'accepted'})
                state=context.request.get(base+'/api/projects/b4-endtoend').json()['state']['A1'];assert state['status']=='accepted'
                settings=context.request.get(base+'/api/projects/b4-endtoend/settings');assert settings.ok
                page.locator('#tabs').get_by_role('button',name='Доска').click();page.locator('.node').first.wait_for(state='attached')
                page.locator('#tabs').get_by_role('button',name='Ещё').click();page.locator('.b6-more').get_by_role('button',name='Настройки').click();page.get_by_role('heading',name='Настройки').wait_for()
                backup=context.request.get(base+'/api/backup');assert backup.status==404,'A5 появился: обновить сценарий на создание копии'
                assert not errors,errors
                print('E2E: вход, создание проекта, импорт плана, выдача, сдача, отчёт, чек-лист, приёмка, настройки OK; backup: A5 отсутствует')
                browser.close()
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
