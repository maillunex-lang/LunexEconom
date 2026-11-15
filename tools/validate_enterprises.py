"""Offline check of V2-04 catalog assumptions."""
from server.enterprises import core

def main():
    c=core.catalog()
    recipes=c.index['recipes']
    assert recipes['field_grain']['outputs']['grain']==100
    assert recipes['mill_flour']['inputs']['grain']==100
    assert recipes['mill_flour']['outputs']['flour']==80
    assert core.load_bp({'grain':{'quantity':50,'quality':50}},recipes['mill_flour'],4000,10000)==5000
    assert core.load_bp({'grain':{'quantity':4000,'quality':50}},recipes['mill_flour'],4000,10000)==0
    for item in c.data['buildings']:
        assert type(item['build_days']) is int and item['build_days']>0
        assert type(item['build_cost']) is int and item['build_cost']>0
    print('Enterprise catalog validation OK; balance: draft')

if __name__=='__main__':
    main()
