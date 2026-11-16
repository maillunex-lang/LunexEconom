"""A9: browser screens in two viewports/themes + authenticated end-to-end HTTP."""
import argparse
import base64
import json
import os
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server
from playwright.sync_api import sync_playwright
from portal import auth,db
from portal.app import create_app
from portal.ui_tests.shots import Quiet,seed

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,default=Path('portal/ui_tests/shots/a9'))
    out=ap.parse_args().output
    out.mkdir(parents=True,exist_ok=True)
    errors=[]
    with tempfile.TemporaryDirectory(prefix='portal-a9-') as temporary:
        path=str(Path(temporary)/'portal.sqlite')
        seed(path)
        def github_stub(url,token='',etag=None):
            if '/git/trees/' in url:
                return {'truncated':False,'tree':[{'type':'blob','path':'docs/plan.md','size':80}]},None
            if '/contents/docs/plan.md' in url:
                raw='# План строительства\nСтроительство и экономика. Проверочные данные.'
                return {'encoding':'base64','content':base64.b64encode(raw.encode()).decode()},None
            raise ValueError('not_found')
        app=create_app(path,base='/createportal',secure_cookie=False,webhook_enabled=True,reports_enabled=True,notifications_enabled=True,ops_enabled=True,memory_root=str(Path(__file__).resolve().parents[2]),github_api=github_stub)
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
                            page.on('pageerror',lambda e:errors.append(str(e)))
                            base='http://127.0.0.1:%s/createportal'%server.server_port
                            page.goto(base+'/')
                            page.evaluate('(t)=>{localStorage.setItem("portalTheme",t);document.documentElement.setAttribute("data-theme",t)}',theme)
                            page.locator('#u').fill('fixture')
                            page.locator('#p').fill('fixture-local-only-password')
                            page.get_by_role('button',name='Войти').click()
                            page.get_by_role('heading',name='Сегодня').wait_for()
                            page.locator('#tabs').get_by_role('button',name='Ещё').click()
                            page.get_by_role('button',name='Контекст для ИИ').first.click()
                            page.get_by_role('heading',name='Память проекта').wait_for()
                            preview=page.get_by_role('textbox',name='Предпросмотр контекста для ИИ')
                            page.wait_for_function("() => document.querySelector('textarea[aria-label=\"Предпросмотр контекста для ИИ\"]')?.value.includes('Тестовая доска')")
                            assert len(preview.input_value())<=6000
                            if page.evaluate('document.querySelector("#app").scrollWidth > document.querySelector("#app").clientWidth+1'):
                                offender=page.evaluate('''() => Array.from(document.querySelectorAll('#app *')).filter(e => e.getBoundingClientRect().right > document.querySelector('#app').getBoundingClientRect().right+1).slice(0,8).map(e=>({tag:e.tagName,cls:e.className,text:(e.innerText||'').slice(0,60),right:e.getBoundingClientRect().right}))''')
                                raise AssertionError('A9 content horizontal overflow: '+str(offender))
                            page.screenshot(path=str(out/f'a9-memory-{width}x{height}-{theme}.png'),full_page=True)
                            page.get_by_role('button',name='Ссылка на 24 часа').click()
                            page.wait_for_function("() => document.querySelector('#app')?.innerText.includes('/ctx/')")
                            page.screenshot(path=str(out/f'a9-context-link-{width}x{height}-{theme}.png'),full_page=True)
                            page.get_by_role('button',name='Отозвать ссылку').click()
                            page.get_by_text('Ссылка отозвана').wait_for()
                            search=page.get_by_placeholder('Поиск документов и решений')
                            search.fill('строительство')
                            page.get_by_role('button',name='Найти').click()
                            page.get_by_text('plan:',exact=False).wait_for()
                            page.screenshot(path=str(out/f'a9-search-{width}x{height}-{theme}.png'),full_page=True)
                            page.get_by_role('textbox',name='Заголовок решения').fill('План утверждён')
                            page.get_by_role('textbox',name='Текст решения').fill('Для тестового проекта')
                            page.get_by_role('button',name='Добавить решение').click()
                            page.get_by_text('План утверждён:',exact=False).wait_for()
                            page.screenshot(path=str(out/f'a9-decisions-{width}x{height}-{theme}.png'),full_page=True)
                            print('A9 browser OK',width,height,theme,flush=True)
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3);app.close()
    if errors:raise RuntimeError('JS errors: '+';'.join(errors))
    print('A9 screenshots:',len(list(out.glob('a9-*.png'))))
if __name__=='__main__':main()
