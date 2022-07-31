import dataclasses
import pickle
import random
from collections.abc import Mapping, Sequence
from time import perf_counter, sleep
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import torch.nn as nn

import delu

from .util import Point


def flatten(data):
    if isinstance(data, torch.Tensor):
        yield data
    elif isinstance(data, (str, bytes)):
        # mypy: NaN
        yield data  # type: ignore
    elif isinstance(data, Sequence):
        for x in data:
            yield from flatten(x)
    elif isinstance(data, Mapping):
        for x in data.values():
            yield from flatten(x)
    elif isinstance(data, SimpleNamespace):
        for x in vars(data).values():
            yield from flatten(x)
    elif dataclasses.is_dataclass(data):
        for x in vars(data).values():
            yield from flatten(x)
    else:
        yield data


def test_to():
    with pytest.raises(ValueError):
        delu.to(None)
    with pytest.raises(ValueError):
        delu.to([None, None])

    t = lambda x: torch.tensor(0, dtype=x)  # noqa
    f32 = torch.float32
    i64 = torch.int64

    for dtype in f32, i64:
        x = t(dtype)
        assert delu.to(x, dtype) is x
    assert delu.to(t(f32), i64).dtype is i64

    for Container in tuple, Point, list:
        constructor = Container._make if Container is Point else Container
        for dtype in [f32, i64]:
            x = constructor([t(f32), t(f32)])
            out = delu.to(x, dtype)
            assert isinstance(out, Container)
            assert all(x.dtype is dtype for x in out)
            if dtype is f32:
                for x, y in zip(out, x):
                    assert x is y

    data = [t(f32), t(f32)]
    for x, y in zip(delu.to(data, f32), data):
        assert x is y
    assert all(x.dtype is i64 for x in delu.to(data, i64))

    @dataclasses.dataclass
    class A:
        a: torch.Tensor

    data = {
        'a': [t(f32), (t(f32), t(f32))],
        'b': {'c': {'d': [[[t(f32)]]]}},
        'c': Point(t(f32), {'d': t(f32)}),
        'f': SimpleNamespace(g=t(f32), h=A(t(f32))),
    }
    for x, y in zip(flatten(delu.to(data, f32)), flatten(data)):
        assert x is y
    for x, y in zip(flatten(delu.to(data, i64)), flatten(data)):
        assert x.dtype is i64
        assert type(x) is type(y)


def test_progress_tracker():
    score = -999999999

    # test initial state
    tracker = delu.ProgressTracker(0)
    assert not tracker.success
    assert not tracker.fail

    # test successful update
    tracker.update(score)
    assert tracker.best_score == score
    assert tracker.success

    # test failed update
    tracker.update(score)
    assert tracker.best_score == score
    assert tracker.fail

    # test forget_bad_updates, reset
    tracker.forget_bad_updates()
    assert tracker.best_score == score
    tracker.reset()
    assert tracker.best_score is None
    assert not tracker.success and not tracker.fail

    # test positive patience
    tracker = delu.ProgressTracker(1)
    tracker.update(score - 1)
    assert tracker.success
    tracker.update(score)
    assert tracker.success
    tracker.update(score)
    assert not tracker.success and not tracker.fail
    tracker.update(score)
    assert tracker.fail

    # test positive min_delta
    tracker = delu.ProgressTracker(0, 2)
    tracker.update(score - 2)
    assert tracker.success
    tracker.update(score)
    assert tracker.fail
    tracker.reset()
    tracker.update(score - 3)
    tracker.update(score)
    assert tracker.success

    # patience=None
    tracker = delu.ProgressTracker(None)
    for i in range(100):
        tracker.update(-i)
        assert not tracker.fail


def test_timer():
    with pytest.raises(AssertionError):
        delu.Timer().pause()

    # initial state, run
    timer = delu.Timer()
    sleep(0.001)
    assert not timer()
    timer.run()
    assert timer()

    # pause
    timer.pause()
    timer.pause()  # two pauses in a row
    x = timer()
    sleep(0.001)
    assert timer() == x

    # add, sub
    timer.pause()
    with pytest.raises(AssertionError):
        timer.add(-1.0)
    timer.add(1.0)
    assert timer() - x == pytest.approx(1)
    with pytest.raises(AssertionError):
        timer.sub(-1.0)
    timer.sub(1.0)
    assert timer() == x

    # run
    timer.pause()
    x = timer()
    timer.run()
    timer.run()  # two runs in a row
    assert timer() != x
    timer.pause()
    x = timer()
    sleep(0.001)
    assert timer() == x
    timer.run()

    # reset
    timer.reset()
    assert not timer()


def test_timer_measurements():
    x = perf_counter()
    sleep(0.1)
    correct = perf_counter() - x
    timer = delu.Timer()
    timer.run()
    sleep(0.1)
    actual = timer()
    # the allowed deviation was obtained from manual runs on my laptop so the test may
    # behave differently on other hardware
    assert actual == pytest.approx(correct, abs=0.01)


def test_timer_context():
    with delu.Timer() as timer:
        sleep(0.01)
    assert timer() > 0.01
    assert timer() == timer()

    timer = delu.Timer()
    timer.run()
    sleep(0.01)
    timer.pause()
    with timer:
        sleep(0.01)
    assert timer() > 0.02
    assert timer() == timer()


def test_timer_pickle():
    timer = delu.Timer()
    timer.run()
    sleep(0.01)
    timer.pause()
    value = timer()
    sleep(0.01)
    assert pickle.loads(pickle.dumps(timer))() == timer() == value


def test_timer_format():
    def make_timer(x):
        timer = delu.Timer()
        timer.add(x)
        return timer

    assert str(make_timer(1)) == '0:00:01'
    assert str(make_timer(1.1)) == '0:00:01'
    assert make_timer(7321).format('%Hh %Mm %Ss') == '02h 02m 01s'


@pytest.mark.parametrize('train', [False, True])
@pytest.mark.parametrize('grad', [False, True])
@pytest.mark.parametrize('n_models', range(3))
def test_evaluation(train, grad, n_models):
    if not n_models:
        with pytest.raises(AssertionError):
            with delu.evaluation():
                pass
        return

    torch.set_grad_enabled(grad)
    models = [nn.Linear(1, 1) for _ in range(n_models)]
    for x in models:
        x.train(train)
    with delu.evaluation(*models):
        assert all(not x.training for x in models[:-1])
        assert not torch.is_grad_enabled()
    assert torch.is_grad_enabled() == grad
    for x in models:
        x.train(train)

    @delu.evaluation(*models)
    def f():
        assert all(not x.training for x in models[:-1])
        assert not torch.is_grad_enabled()
        for x in models:
            x.train(train)

    for _ in range(3):
        f()
        assert torch.is_grad_enabled() == grad


def test_evaluation_generator():
    with pytest.raises(AssertionError):

        @delu.evaluation(nn.Linear(1, 1))
        def generator():
            yield 1


def test_improve_reproducibility():
    def f():
        upper_bound = 100
        return [
            random.randint(0, upper_bound),
            np.random.randint(upper_bound),
            torch.randint(upper_bound, (1,))[0].item(),
        ]

    for seed in [None, 0, 1, 2]:
        seed = delu.improve_reproducibility(seed)
        assert not torch.backends.cudnn.benchmark
        assert torch.backends.cudnn.deterministic
        results = f()
        delu.random.seed(seed)
        assert results == f()
