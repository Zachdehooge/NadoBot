import unittest
import requests

# To run tests do: 
class TestURL(unittest.TestCase):
    def test_list_int(self):
        """
        Test that ensures the endpoint is up
        """
        url = requests.get("http://data.nadocast.com")
        self.assertEqual(url.status_code, 200)


if __name__ == "__main__":
    unittest.main()