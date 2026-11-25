# Compatibility path for the declared PASS_TO_PASS baseline.
from test_frontier_0023 import test_fixed_head_mutex_and_atomic_refcount, test_fixed_stress


def test_no_regression_frontier_gh_0023():
    test_fixed_head_mutex_and_atomic_refcount()
    test_fixed_stress()
