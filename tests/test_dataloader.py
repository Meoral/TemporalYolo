import sys, os
# sys.path.append(os.path.abspath("../../"))

from shared_utils.data import BatchLoader

from nose.tools import assert_equals


def test_generating_batches():
    batch_loader = BatchLoader("tests/SAMPLE_DATA", seq_len=6, batch_size=2, step_size=1, folders_to_use=["TEST1", "TEST2", "TEST3"])

    assert_equals(len(batch_loader.batches), 6)


def test_loading_batches():
    batch_loader = BatchLoader("tests/SAMPLE_DATA", seq_len=6, batch_size=2, step_size=1, folders_to_use=["TEST1", "TEST2", "TEST3"])

    batch1 = batch_loader.load_batch(0)

    assert_equals(len(batch1[1]), 2)
    assert_equals(len(batch1[0]), 2)
    assert_equals(batch1[0].shape, (2, 6, 4102))
