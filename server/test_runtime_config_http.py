"""HTTP administration boundaries for the editable runtime."""
import unittest

from test_admin_api import AdminBase, TOKEN

class RuntimeAdminHTTPTests(AdminBase):
    def test_get_and_write_require_long_token_and_no_proxy(self):
        for path in ("/admin/config", "/admin/revisions", "/admin/status",
                     "/admin/online", "/admin/online/players", "/admin/config/candidate"):
            status, response=self.call("GET",path)
            self.assertEqual(status,200,(path,response))
            self.assertEqual(self.call("GET",path,token=None)[0],401)
            self.assertEqual(self.call("GET",path,headers={"X-Forwarded-For":"8.8.8.8"})[0],404)
        body={"changes":{"HOUSEHOLDS_ENABLED":True},"confirm":True}
        self.assertEqual(self.call("POST","/admin/config/set",body,token=None)[0],401)
        self.assertEqual(self.call("POST","/admin/config/set",body,
                          headers={"Forwarded":"for=8.8.8.8"})[0],404)
        self.assertEqual(self.call("POST","/admin/config/set",body)[0],200)
        self.assertEqual(self.call("GET","/admin/config")[1]["revision"],1)
    def test_invalid_changes_do_not_write(self):
        self.assertEqual(self.call("POST","/admin/config/set",
                         {"changes":{"HOUSEHOLDS_ENABLED":True}})[0],400)
        self.assertEqual(self.call("POST","/admin/config/set",
                         {"changes":{"ADMIN_API_TOKEN":"x"},"confirm":True})[0],400)
        self.assertEqual(self.call("GET","/admin/config")[1]["revision"],0)

if __name__=="__main__":unittest.main()
