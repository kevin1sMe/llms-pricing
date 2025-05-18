import unittest
from single import _parse_provider_list # 假设 single.py 和 test_single.py 在同一目录下或者 single.py 在PYTHONPATH中

class TestProviderParser(unittest.TestCase):

    def test_parse_provider_list_basic(self):
        content = """
## 阿里云
https://help.aliyun.com/zh/model-studio/models

## deepseek
https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
"""
        expected_output = [
            {'name': '阿里云', 'url': 'https://help.aliyun.com/zh/model-studio/models'},
            {'name': 'deepseek', 'url': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'}
        ]
        
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

    def test_parse_provider_list_empty_input(self):
        content = ""
        expected_output = []
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

    def test_parse_provider_list_no_url(self):
        content = """
## Provider One
No URL here
## Provider Two
https://provider.two/pricing
"""
        expected_output = [
            {'name': 'Provider Two', 'url': 'https://provider.two/pricing'}
        ]
        # Provider One will be skipped because it's followed by another provider or end of input without a URL
        # The current logic: if a provider is declared, it waits for a URL. If another provider starts before a URL is found, the prior one is not added.
        # If "Provider One" was the *last* entry with no URL, it would not be added.
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

    def test_parse_provider_list_extra_lines(self):
        content = """
Some introductory text.

## Provider A
This is a description for Provider A.
URL: https://provider.a/api

## Provider B
https://provider.b/
Additional details for B.

## Provider C
Leading text https://provider.c/models more text
"""
        expected_output = [
            {'name': 'Provider A', 'url': 'https://provider.a/api'},
            {'name': 'Provider B', 'url': 'https://provider.b/'},
            {'name': 'Provider C', 'url': 'https://provider.c/models'}
        ]
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

    def test_parse_provider_list_only_one_provider(self):
        content = """
## Only One Provider
https://onlyone.com/details
Some other text.
"""
        expected_output = [
            {'name': 'Only One Provider', 'url': 'https://onlyone.com/details'}
        ]
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

    def test_parse_provider_list_no_providers(self):
        content = """
Just some random text.
https://example.com
But no lines starting with ##
"""
        expected_output = []
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

    def test_parse_provider_list_url_before_provider(self):
        content = """
https://earlybird.com/worm
## Provider Later
https://providerlater.com
"""
        expected_output = [
            {'name': 'Provider Later', 'url': 'https://providerlater.com'}
        ]
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)
        
    def test_parse_provider_list_name_with_spaces_and_symbols(self):
        content = """
## My Awesome Provider & Co.
http://myawesomeprovider.co/api/v1/pricing

## Another One (Test)
https://another-one.test.com/page
"""
        expected_output = [
            {'name': 'My Awesome Provider & Co.', 'url': 'http://myawesomeprovider.co/api/v1/pricing'},
            {'name': 'Another One (Test)', 'url': 'https://another-one.test.com/page'}
        ]
        result = _parse_provider_list(content)
        self.assertEqual(result, expected_output)

if __name__ == '__main__':
    unittest.main() 