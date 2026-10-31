import unittest

from spotpris2 import __main__ as spotpris2_main


class ResourceTests(unittest.TestCase):
    def test_mpris_interfaces_are_loaded_from_package_data(self):
        interfaces = spotpris2_main._load_mpris_interfaces()

        self.assertEqual(2, len(interfaces))
        self.assertIn('<interface name="org.mpris.MediaPlayer2">', interfaces[0])
        self.assertIn(
            '<interface name="org.mpris.MediaPlayer2.Player">',
            interfaces[1],
        )


if __name__ == "__main__":
    unittest.main()
