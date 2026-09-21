import unittest

from src.greeter import greet


class GreeterTests(unittest.TestCase):
    def test_greet(self):
        self.assertEqual("Hello, Ada!", greet("Ada"))


if __name__ == "__main__":
    unittest.main()
