import unittest

import helpers  # noqa: F401
from wikitrends import languages as L


class TestLanguages(unittest.TestCase):
    def test_codes_pass_through(self):
        r = L.normalize_langs("pl,cs, uk")
        self.assertEqual(r.codes, ["pl", "cs", "uk"])
        self.assertEqual(r.errors, [])

    def test_country_codes_are_corrected_with_a_note(self):
        r = L.normalize_langs("cz,ua,gr,jp")
        self.assertEqual(r.codes, ["cs", "uk", "el", "ja"])
        self.assertTrue(any("cz" in n for n in r.notes))

    def test_names_in_english_and_ukrainian(self):
        r = L.normalize_langs(["Polish", "чеська", "польськомовна", "Czech"])
        self.assertEqual(r.codes, ["pl", "cs"])

    def test_confusable_codes_warn(self):
        r = L.normalize_langs("se")
        self.assertEqual(r.codes, ["se"])
        self.assertTrue(any("Swedish" in n for n in r.notes))

    def test_invalid(self):
        self.assertTrue(L.normalize_langs("klingon!").errors)
        self.assertTrue(L.normalize_langs("").errors)

    def test_dbname_and_urls(self):
        self.assertEqual(L.dbname("pl"), "plwiki")
        self.assertEqual(L.dbname("be-tarask"), "be_x_oldwiki")
        self.assertEqual(L.dbname("zh-yue"), "zh_yuewiki")
        self.assertEqual(L.project("uk"), "uk.wikipedia")
        self.assertIn("%D0", L.article_url("uk", "Астрономія"))


if __name__ == "__main__":
    unittest.main()
