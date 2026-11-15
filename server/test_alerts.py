import unittest
import alerts

class AlertTests(unittest.TestCase):
    def test_critical_bills_and_warehouse(self):
        status={'wages_owed':100,'tax_owed':10,'missed':2,'bankrupt_after':3}
        result=alerts.collect('alice',[],status,200,[],3,{'honey':100},100)
        codes={a['code'] for a in result}
        self.assertTrue({'wage_arrears','tax_arrears','warehouse_full','bankruptcy_risk','loan_interest'}<=codes)
        self.assertTrue(all(a['level'] in ('info','warning','critical') for a in result))

    def test_object_link_and_no_raw_input_stock(self):
        obj={'id':'b','x':4,'y':5,'construction_stage':'complete','status':'working','alerts':[], 'recipe':{'inputs':{'grain':20}}}
        result=alerts.collect('alice',[obj],{},0,[],5,{'grain':3},0)
        self.assertEqual(result[0]['object_id'],'b')
        self.assertEqual(result[0]['x'],4)
        self.assertEqual(result[0]['code'],'no_input:grain')

if __name__=='__main__':unittest.main()