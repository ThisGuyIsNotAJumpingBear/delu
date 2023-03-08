import inspect
import secrets
from contextlib import ContextDecorator
from typing import Any, Optional

import torch
import torch.nn as nn

from . import random as delu_random


def improve_reproducibility(
    base_seed: Optional[int], one_cuda_seed: bool = False
) -> int:
    """Set seeds and turn off non-deterministic algorithms.

    Do everything possible to improve reproducibility for code that relies on global
    random number generators from the aforementioned modules. See also the note below.

    Sets:

    1. seeds in `random`, `numpy.random`, `torch`, `torch.cuda`
    2. `torch.backends.cudnn.benchmark` to `False`
    3. `torch.backends.cudnn.deterministic` to `True`

    Args:
        base_seed: the argument for `delu.random.seed`. If `None`, a high-quality base
            seed is generated instead.
        one_cuda_seed: the argument for `delu.random.seed`.

    Returns:
        base_seed: if ``base_seed`` is set to `None`, the generated base seed is
            returned; otherwise, ``base_seed`` is returned as is

    Note:
        If you don't want to choose the base seed, but still want to have a chance to
        reproduce things, you can use the following pattern::

            print('Seed:', delu.improve_reproducibility(None))

    Note:
        100% reproducibility is not always possible in PyTorch. See
        `this page <https://pytorch.org/docs/stable/notes/randomness.html>`_ for
        details.

    Examples:
        .. testcode::

            assert delu.improve_reproducibility(0) == 0
            seed = delu.improve_reproducibility(None)
    """
    torch.backends.cudnn.benchmark = False  # type: ignore
    torch.backends.cudnn.deterministic = True  # type: ignore
    if base_seed is None:
        # See https://numpy.org/doc/1.18/reference/random/bit_generators/index.html#seeding-and-entropy  # noqa
        base_seed = secrets.randbits(128) % (2**32 - 1024)
    else:
        assert base_seed < (2**32 - 1024)
    delu_random.seed(base_seed, one_cuda_seed)
    return base_seed


class evaluation(ContextDecorator):
    """Context-manager & decorator for models evaluation.

    This code... ::

        with evaluation(model):  # or: with evaluation(model_0, model_1, ...)
            ...

        @evaluation(model)  # or: @evaluation(model_0, model_1, ...)
        def f():
            ...

    ...is equivalent to the following: ::

        context = getattr(torch, 'inference_mode', torch.no_grad)

        with context():
            model.eval()
            ...

        @context()
        def f():
            model.eval()
            ...

    Args:
        modules

    Note:
        The training status of modules is undefined once a context is finished or a
        decorated function returns.

    Warning:
        The function must be used in the same way as `torch.no_grad` and
        `torch.inference_mode`, i.e. only as a context manager or a decorator as shown
        below in the examples. Otherwise, the behaviour is undefined.

    Warning:
        Contrary to `torch.no_grad` and `torch.inference_mode`, the function cannot be
        used to decorate generators. So, in the case of generators, you have to manually
        create a context::

            def my_generator():
                with evaluation(...):
                    for a in b:
                        yield c

    Examples:
        .. testcode::

            a = torch.nn.Linear(1, 1)
            b = torch.nn.Linear(2, 2)
            with evaluation(a):
                ...
            with evaluation(a, b):
                ...

            @evaluation(a)
            def f():
                ...

            @evaluation(a, b)
            def f():
                ...
    """

    def __init__(self, *modules: nn.Module) -> None:
        assert modules
        self._modules = modules
        self._torch_context: Any = None

    def __call__(self, func):
        """Decorate a function with an evaluation context.

        Args:
            func
        Raises:
            AssertionError: if ``func`` is a generator
        """
        assert not inspect.isgeneratorfunction(func), (
            f'{self.__class__} cannot be used to decorate generators.'
            ' See the documentation.'
        )
        return super().__call__(func)

    def __enter__(self) -> None:
        assert self._torch_context is None
        self._torch_context = getattr(torch, 'inference_mode', torch.no_grad)()
        self._torch_context.__enter__()  # type: ignore
        for m in self._modules:
            m.eval()

    def __exit__(self, *exc):
        assert self._torch_context is not None
        result = self._torch_context.__exit__(*exc)  # type: ignore
        self._torch_context = None
        return result
