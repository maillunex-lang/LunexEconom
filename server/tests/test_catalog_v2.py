"""Catalog data, startup guards and HTTP conditional requests."""
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server.catalog import Catalog, CatalogError, ROOT, load_all, verify, canonical, register
from server.registry import Registry


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('schema','products','buildings','recipes'):
            shutil.copyfile(ROOT/(name+'.json'), self.root/(name+'.json'))

    def mutate(self, name, change):
        path = self.root/(name+'.json')
        data = json.loads(path.read_text(encoding='utf-8'))
        change(data)
        path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def test_full_catalog_and_m1(self):
        catalog=Catalog()
        self.assertEqual(len(catalog.data['products']),41)
        self.assertEqual(len(catalog.data['buildings']),42)
        self.assertEqual(len(catalog.data['recipes']),41)
        self.assertEqual(len(catalog.version),64)
        self.assertEqual(canonical(catalog.data),canonical(load_all()))

    def test_negative_or_float_schema_rejected(self):
        for val in (-2,1.5,True):
            with self.subTest(val=val):
                self.mutate('products',lambda rows: rows[0].update(reference_price=val))
                with self.assertRaisesRegex(CatalogError, 'products'):
                    Catalog(self.root)
                shutil.copyfile(ROOT/'products.json',self.root/'products.json')

    def test_duplicate_ids_and_json_keys(self):
        self.mutate('products',lambda rows: rows.append(copy.deepcopy(rows[0])))
        with self.assertRaisesRegex(CatalogError,'duplicate id'):
            Catalog(self.root)
        shutil.copyfile(ROOT/'products.json',self.root/'products.json')
        (self.root/'products.json').write_text('[{"id":"a","id":"b"}]',encoding='utf-8')
        with self.assertRaisesRegex(CatalogError,'duplicate JSON key'):
            Catalog(self.root)

    def test_bad_references(self):
        self.mutate('recipes',lambda rows: rows[0]['outputs'].update(phantom=1))
        with self.assertRaisesRegex(CatalogError,'unknown outputs product'):
            Catalog(self.root)
        shutil.copyfile(ROOT/'recipes.json',self.root/'recipes.json')
        self.mutate('recipes',lambda rows: rows[0].update(building='not_real'))
        with self.assertRaisesRegex(CatalogError,'unknown building'):
            Catalog(self.root)

    def test_cycle(self):
        self.mutate('recipes',lambda rows: rows[3]['inputs'].update(bread=1))
        with self.assertRaisesRegex(CatalogError,'cycle'):
            Catalog(self.root)

    def test_required_recipe_and_m1(self):
        self.mutate('recipes',lambda rows: rows.__setitem__(slice(None),[r for r in rows if r['building']!='mill']))
        with self.assertRaisesRegex(CatalogError,'no recipe'):
            Catalog(self.root)
        shutil.copyfile(ROOT/'recipes.json',self.root/'recipes.json')
        self.mutate('buildings',lambda rows: [r['allowed_goods'].remove('bread') for r in rows if r.get('allowed_goods') and 'bread' in r['allowed_goods']])
        with self.assertRaisesRegex(CatalogError,'M1 broken'):
            Catalog(self.root)

    def test_unbounded_quality_and_rating_rejected(self):
        self.mutate('products',lambda rows: rows[0]['rating_weights'].update(brand=999))
        with self.assertRaisesRegex(CatalogError,'weights'):
            Catalog(self.root)
        shutil.copyfile(ROOT/'products.json',self.root/'products.json')
        self.mutate('products',lambda rows: rows[0]['quality_range'].update(min=99,max=50))
        with self.assertRaisesRegex(CatalogError,'quality_range'):
            Catalog(self.root)

    def test_registration_rejects_bad_data_before_db(self):
        self.mutate('recipes',lambda rows: rows[0]['inputs'].update(unknown=1))
        with patch('server.catalog.ROOT',self.root):
            # No database is used in build_registry, registration must fail now.
            with self.assertRaises(CatalogError):
                register(Registry())

    def test_route_and_version_change(self):
        registry=Registry()
        register(registry)
        status,body=registry.dispatch('GET','/catalog',{}, {})
        self.assertEqual(status,200)
        self.assertIn('version',body)
        self.assertEqual(registry.dispatch('GET','/catalog',{}, {'if_none_match':registry.catalog.etag}), (304,{}))
        self.assertEqual(registry.dispatch('GET','/catalog',{}, {'if_none_match':'"bad", '+registry.catalog.etag}), (304,{}))
        self.assertEqual(registry.dispatch('GET','/catalog/products/grain',{}, {})[1]['name'],'Зерно')
        self.assertEqual(registry.dispatch('GET','/catalog/buildings/mill',{}, {})[1]['name'],'Мельница')
        self.assertEqual(registry.dispatch('GET','/catalog/buildings/does_not_exist',{}, {})[0],404)
        before=Catalog(self.root).version
        self.mutate('products',lambda rows: rows[0].update(reference_price=rows[0]['reference_price']+1))
        self.assertNotEqual(before,Catalog(self.root).version)


@unittest.skipUnless(os.getenv('LUNEX_TEST_DATABASE_URL'), 'Isolated PostgreSQL DSN not set')
class CatalogHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server.game_server import create_app
        cls.app=create_app(os.environ['LUNEX_TEST_DATABASE_URL'])

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def probe(self,path,etag=''):
        metadata={}
        environment={'REQUEST_METHOD':'GET','PATH_INFO':path,'CONTENT_LENGTH':'0','wsgi.input':io.BytesIO(), 'HTTP_IF_NONE_MATCH':etag}
        body=b''.join(type(self).app(environment,lambda status,headers:metadata.update(status=int(status.split()[0]),headers=dict(headers))))
        return metadata,body

    def test_http_etag_304(self):
        first,body=self.probe('/catalog')
        self.assertEqual(first['status'],200)
        self.assertEqual(json.loads(body)['version'],first['headers']['ETag'].strip('"'))
        cached,body=self.probe('/catalog',first['headers']['ETag'])
        self.assertEqual(cached['status'],304)
        self.assertEqual(body,b'')
        self.assertEqual(cached['headers']['ETag'],first['headers']['ETag'])
        product,body=self.probe('/catalog/products/grain')
        self.assertEqual(product['status'],200)
        self.assertEqual(json.loads(body)['name'],'Зерно')
