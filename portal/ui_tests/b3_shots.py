"""B3 isolated headless browser screenshots and review/metrics contract mocks."""
import argparse
import json
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
    errors=[]
    with tempfile.TemporaryDirectory(prefix='b3-') as temp:
        db=os.path.join(temp,'portal.sqlite');seed(db)
        server=make_server('127.0.0.1',0,create_app(db,base='/createportal',secure_cookie=False))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(args=['--no-sandbox'])
                try:
                    for theme in ('light','dark'):
                        for width,height in ((390,844),(1440,900)):
                            ctx=browser.new_context(viewport={'width':width,'height':height},service_workers='block');page=ctx.new_page()
                            page.on('pageerror',lambda e:errors.append(str(e)))
                            page.on('console',lambda m:errors.append(m.text) if m.type=='error' and '401 (Unauthorized)' not in m.text else None)
                            calls=[]
                            def mock(route):
                                url=route.request.url
                                if url.endswith('/api/metrics'):
                                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'attention':[{'project_name':'Тестовая доска','project_slug':'fixture-board','task_id':'B2','reason':'Ждёт приёмки'}],'metrics':{'accepted_week':3,'avg_issue_to_submit':'2 дня','avg_issue_to_accept':'3 дня','return_rate':'20 %','waiting_owner':1,'red_ci':0,'weekly':[{'week':'1','count':1},{'week':'2','count':3}]}}));return
                                if '/tasks/B2/report' in url:
                                    if route.request.method=='POST':calls.append(('report',route.request.post_data_json));route.fulfill(status=200,content_type='application/json',body='{"ok":true}');return
                                    route.fulfill(status=200,content_type='application/json',body=json.dumps({'report':{'text':'PR: проверено в тестовой среде'},'checks':[],'revisions':2}));return
                                if '/tasks/B2/review' in url:
                                    calls.append(('review',route.request.post_data_json));route.fulfill(status=200,content_type='application/json',body='{"ok":true}');return
                                route.continue_()
                            page.route('**/createportal/api/**',mock)
                            page.goto(f'http://127.0.0.1:{server.server_port}/createportal/')
                            page.evaluate('(t)=>{localStorage.setItem("portalTheme",t);document.documentElement.setAttribute("data-theme",t)}',theme)
                            page.locator('#u').fill('fixture');page.locator('#p').fill('fixture-local-only-password');page.get_by_role('button',name='Войти').click()
                            page.get_by_role('heading',name='Требует вашего внимания').wait_for();page.get_by_text('20 %').wait_for()
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            page.screenshot(path=str(args.output/f'b3-overview-{width}x{height}-{theme}.png'))
                            page.get_by_role('button',name='Открыть доску').first.click()
                            page.locator('.node').first.wait_for(state='attached')
                            page.evaluate("() => [...document.querySelectorAll('.node')].find(e=>e.textContent.includes('B2'))?.click()")
                            page.get_by_role('heading',name='Чек-лист приёмки').wait_for()
                            page.get_by_text('Доработок: 2').wait_for()
                            assert page.get_by_role('button',name='Принято, в архив').last.is_disabled()
                            page.screenshot(path=str(args.output/f'b3-review-{width}x{height}-{theme}.png'))
                            for cb in page.locator('.b3-check input').all():cb.check()
                            assert page.get_by_role('button',name='Принято, в архив').last.is_enabled()
                            page.get_by_role('button',name='Принять вручную').click();assert 'Подтвердите ручную' in page.locator('.b3-review').inner_text()
                            page.locator('.b3-review textarea').last.fill('Исправить тесты и приложить отчёт')
                            page.get_by_role('button',name='Копировать промпт доработки').is_enabled()
                            page.screenshot(path=str(args.output/f'b3-checklist-{width}x{height}-{theme}.png'))
                            page.locator('.b3-review textarea').first.fill('Сдана работа и тесты')
                            page.get_by_role('button',name='Сохранить отчёт').click();page.get_by_text('Отчёт сохранён.').wait_for()
                            assert calls and calls[-1][0]=='report'
                            page.get_by_role('button',name='Принять вручную').click();page.wait_for_timeout(150)
                            assert any(k=='review' and v.get('manual') is True for k,v in calls)
                            page.evaluate("() => [...document.querySelectorAll('.node')].find(e=>e.textContent.includes('B2'))?.click()")
                            page.get_by_text('Доработок: 2').wait_for()
                            page.locator('.b3-review textarea').last.fill('Доработать тесты')
                            page.get_by_role('button',name='Вернуть исполнителю').last.click()
                            page.wait_for_timeout(150)
                            assert any(k=='review' and v.get('action')=='return' and v.get('notes')=='Доработать тесты' for k,v in calls)
                            print('OK',width,height,theme)
                            ctx.close()
                finally:browser.close()
        finally:server.shutdown();server.server_close();thread.join(timeout=3)
    if errors:raise RuntimeError('Ошибки консоли/JavaScript: '+'; '.join(errors))
    print('Браузер: без ошибок')

if __name__=='__main__':main()
