import unittest

from .helpers import cpu_list_to_range


class DisplayHelper(unittest.TestCase):
    def test_deserialize_cpu_list_to_string(self):
        "Make sure that the output matches the input even for invalid or weird cases"
        assert cpu_list_to_range([0, 1, 2, 3, 4, 5]) == "0-5"
        assert cpu_list_to_range([0, 1, 2, 3, 5]) == "0-3, 5"
        assert cpu_list_to_range([0, 1, 3, 4, 5]) == "0-1, 3-5"
        assert cpu_list_to_range([0, 4, 2, 7, 8, 9]) == "0, 2, 4, 7-9"
        assert cpu_list_to_range([0, 4, 2, 3, 7, 8, 9]) == "0, 2-4, 7-9"

    def test_single_cpu(self):
        "A single-element list must render as that single cpu (regression: it used to render empty)"
        assert cpu_list_to_range([5]) == "5"
        assert cpu_list_to_range([0]) == "0"

    def test_empty_cpu_list(self):
        "An empty list must render as an empty string, not raise"
        assert cpu_list_to_range([]) == ""
