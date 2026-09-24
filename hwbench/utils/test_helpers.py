import unittest

from .helpers import cpu_list_to_range, format_duration


class DisplayHelper(unittest.TestCase):
    def test_deserialize_cpu_list_to_string(self):
        "Make sure that the output matches the input even for invalid or weird cases"
        assert cpu_list_to_range([0, 1, 2, 3, 4, 5]) == "0-5"
        assert cpu_list_to_range([0, 1, 2, 3, 5]) == "0-3, 5"
        assert cpu_list_to_range([0, 1, 3, 4, 5]) == "0-1, 3-5"
        assert cpu_list_to_range([0, 4, 2, 7, 8, 9]) == "0, 2, 4, 7-9"
        assert cpu_list_to_range([0, 4, 2, 3, 7, 8, 9]) == "0, 2-4, 7-9"
        assert cpu_list_to_range([3, 7]) == "3, 7"
        assert cpu_list_to_range([0, 1]) == "0-1"
        assert cpu_list_to_range([5]) == "5"
        assert cpu_list_to_range([]) == ""

    def test_format_duration(self):
        assert format_duration(0) == "0h 00m 00s"
        assert format_duration(420) == "0h 07m 00s"
        assert format_duration(6120) == "1h 42m 00s"
        # Beyond a day, the hours keep counting
        assert format_duration(90061) == "25h 01m 01s"
