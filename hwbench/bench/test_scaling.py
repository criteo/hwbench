from . import benchmarks


class FakeSockets:
    """A cpu of identical sockets, core n being logical cpu n."""

    def __init__(self, cores_per_socket: int):
        self.cores_per_socket = cores_per_socket

    def get_socket(self, logical_cpu: int) -> int:
        return logical_cpu // self.cores_per_socket


def test_curve_steps_beyond_256_cores():
    """The +16 steps go up to the last core."""
    steps = benchmarks.curve_steps([[core] for core in range(320)], FakeSockets(160))  # type: ignore[arg-type]
    assert steps == [1, 2, 3, 4, 8, 16, *range(32, 321, 16)]


def test_curve_steps_socket_end():
    """The end of each socket is a step, even when it is not a multiple of 16."""
    steps = benchmarks.curve_steps([[core] for core in range(100)], FakeSockets(50))  # type: ignore[arg-type]
    assert steps == [1, 2, 3, 4, 8, 16, 32, 48, 50, 64, 80, 96, 100]
