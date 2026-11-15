from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class Check(HTMLParser):
    def __init__(self): super().__init__(); self.ids=set();self.links=[];self.lang=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='html': self.lang=attrs.get('lang')
        if 'id' in attrs: self.ids.add(attrs['id'])
        if tag=='a': self.links.append(attrs.get('href',''))


def main():
    html=(ROOT/'web/index.html').read_text()
    css=(ROOT/'web/styles.css').read_text()
    checker=Check();checker.feed(html)
    assert checker.lang=='ru'
    assert {'home','about','mechanics','screens','download'} <= checker.ids
    assert all(h[1:] in checker.ids for h in checker.links if h.startswith('#'))
    assert 'max-width:620px' in css and 'viewport-fit=cover' in html
    assert 'Capitalism Lab' not in html
    assert 'aria-disabled="true"' in html, 'Never pretend APK exists'
    print('Website checks passed: anchors, Russian, responsive, no fake APK')

if __name__=='__main__': main()
