"""Missing batteries from `torch.utils.data`."""

from typing import Any, Callable, Iterable, Optional, Tuple, TypeVar, Union

import torch
from torch.utils.data import DataLoader, Dataset

from ._stream import Stream  # noqa: F401
from ._utils import deprecated

T = TypeVar('T')


class Enumerate(Dataset):
    """Make dataset return both indices and items.

    .. rubric:: Tutorial

    .. testcode::

        from torch.utils.data import DataLoader, TensorDataset
        X, y = torch.randn(9, 2), torch.randn(9)
        dataset = TensorDataset(X, y)
        for batch_idx, batch in DataLoader(delu.data.Enumerate(dataset), batch_size=3):
            print(batch_idx)

    .. testoutput::

        tensor([0, 1, 2])
        tensor([3, 4, 5])
        tensor([6, 7, 8])
    """

    def __init__(self, dataset: Dataset) -> None:
        """Initialize self.

        Args:
            dataset
        """
        self._dataset = dataset

    @property
    def dataset(self) -> Dataset:
        """Access the underlying dataset.

        Returns:
            The dataset.
        """
        return self._dataset

    def __len__(self) -> int:
        """Get the length of the underlying dataset."""
        return len(self._dataset)  # type: ignore

    def __getitem__(self, index) -> Tuple[Any, Any]:
        """Return index and the corresponding item from the underlying dataset.

        Args:
            index
        Returns:
            (index, item)
        """
        return index, self._dataset[index]


class FnDataset(Dataset):
    """Create simple PyTorch datasets without classes and inheritance.

    `FnDataset` allows avoiding implementing `~torch.utils.data.Dataset` classes in
    simple cases.

    .. rubric:: Tutorial

    First, a quick example. Without `FnDataset`::

        from PIL import Image

        class ImagesList(Dataset):
            def __init__(self, filenames, transform):
                self.filenames = filenames
                self.transform = transform

            def __len__(self):
                return len(self.filenames)

            def __getitem__(self, index):
                return self.transform(Image.open(self.filenames[index]))

        dataset = ImagesList(filenames, transform)

    With `FnDataset`::

        dataset = delu.data.FnDataset(Image.open, filenames, transform)
        # Cache images after the first load:
        from functools import lru_cache
        dataset = delu.data.FnDataset(lru_cache(None)(Image.open), filenames)

    In other words, with the vanilla PyTorch, in order to create a dataset,
    you have to inherit from `torch.utils.data.Dataset` and implement three methods:

    - ``__init__``
    - ``__len__``
    - ``__getitem__``

    With `FnDataset` the only thing you *may* need to implement is the ``fn``
    argument that will power ``__getitem__``. The easiest way to learn
    `FnDataset` is to go through the examples below.

    A list of images::

        dataset = delu.data.FnDataset(Image.open, filenames)
        # dataset[i] returns Image.open(filenames[i])

    A list of images that are cached after the first load::

        from functools import lru_cache
        dataset = delu.data.FnDataset(lru_cache(None)(Image.open), filenames)

    `pathlib.Path` is handy for creating datasets that read from files::

        images_dir = Path(...)
        dataset = delu.data.FnDataset(Image.open, images_dir.iterdir())

    If you only need files with specific extensions::

        dataset = delu.data.FnDataset(Image.open, images_dir.glob('*.png'))

    If you only need files with specific extensions located in all subfolders::

        dataset = delu.data.FnDataset(
            Image.open, (x for x in images_dir.rglob('**/*.png') if condition(x))
        )

    A segmentation dataset::

        image_filenames = ...
        gt_filenames = ...

        def get(i):
            return Image.open(image_filenames[i]), Image.open(gt_filenames[i])

        dataset = delu.data.FnDataset(get, len(image_filenames))

    A dummy dataset that demonstrates that `FnDataset` is a very general thing:

    .. testcode::

        def f(x):
            return x * 10

        def g(x):
            return x * 2

        dataset = delu.data.FnDataset(f, 3, g)
        # dataset[i] returns g(f(i))
        assert len(dataset) == 3
        assert dataset[0] == 0
        assert dataset[1] == 20
        assert dataset[2] == 40

    """

    def __init__(
        self,
        fn: Callable[..., T],
        args: Union[int, Iterable],
        transform: Optional[Callable[[T], Any]] = None,
    ) -> None:
        """Initialize self.

        Args:
            fn: the function that produces values based on arguments from ``args``
            args: arguments for ``fn``. If an iterable, but not a list, then is
                casted to a list. If an integer, then the behavior is the same as for
                ``list(range(args))``. The size of ``args`` defines the return
                value for `FnDataset.__len__`.
            transform: if presented, is applied to the return value of `fn` in
                `FnDataset.__getitem__`

        Examples:
            .. code-block::

                import PIL.Image as Image
                import torchvision.transforms as T

                dataset = delu.data.FnDataset(Image.open, filenames, T.ToTensor())
        """
        self._fn = fn
        if isinstance(args, Iterable):
            if not isinstance(args, list):
                args = list(args)
        self._args = args
        self._transform = transform

    def __len__(self) -> int:
        """Get the dataset size.

        See `FnDataset` for details.

        Returns:
            size
        """
        return len(self._args) if isinstance(self._args, list) else self._args

    def __getitem__(self, index: int) -> Any:
        """Get value by index.

        See `FnDataset` for details.

        Args:
            index
        Returns:
            value
        Raises:
            IndexError: if ``index >= len(self)``
        """
        if isinstance(self._args, list):
            x = self._args[index]
        elif index < self._args:
            x = index
        else:
            raise IndexError(f'Index {index} is out of range')
        x = self._fn(x)
        return x if self._transform is None else self._transform(x)


class IndexDataset(Dataset):
    """A trivial dataset that yeilds indices back to user (useful for DDP).

    This simple dataset is useful when:

    1. you need a dataloader that yeilds batches of *indices* instead of *objects*
    2. AND you work in the `Distributed Data Parallel <https://pytorch.org/tutorials/intermediate/ddp_tutorial.html>`_ setup

    Note:
        If only the first condition is true, consider using the combinatation of
        `torch.randperm` and `torch.Tensor.split` instead.

    Example::

        from torch.utils.data import DataLoader
        from torch.utils.data.distributed import DistributedSampler

        train_size = 123456
        batch_size = 123
        dataset = delu.data.IndexDataset(dataset_size)
        for i in range(train_size):
            assert dataset[i] == i
        dataloader = DataLoader(
            dataset,
            batch_size,
            sampler=DistributedSampler(dataset)
        )

        for epoch in range(n_epochs):
            for batch_indices in dataloader:
                ...
    """  # noqa: E501

    def __init__(self, size: int) -> None:
        """Initialize self.

        Args:
            size: the dataset size
        """
        if size < 1:
            raise ValueError('size must be positive')
        self.size = size

    def __len__(self) -> int:
        """Get the dataset size."""
        return self.size

    def __getitem__(self, i: int) -> int:
        """Get the same index back.

        The index must be an integer from ``range(len(self))``.
        """
        if i < 0 or i >= self.size:
            raise IndexError(
                f"index {i} is out of range (dataset's size is {self.size})"
            )
        return i


@deprecated('Instead, use `delu.data.IndexDataset` and `~torch.utils.data.DataLoader`')
def make_index_dataloader(size: int, *args, **kwargs) -> DataLoader:
    """Make `~torch.utils.data.DataLoader` over indices instead of data.

    This is just a shortcut for
    ``torch.utils.data.DataLoader(delu.data.IndexDataset(...), ...)``.

    Args:
        size: the dataset size
        *args: positional arguments for `torch.utils.data.DataLoader`
        **kwargs: keyword arguments for `torch.utils.data.DataLoader`
    Raises:
        ValueError: for invalid inputs
    Examples:

        Usage for training:

        .. code-block::

            train_loader = delu.data.make_index_dataloader(
                len(train_dataset), batch_size, shuffle=True
            )
            for epoch in range(n_epochs):
                for i_batch in train_loader:
                    x_batch = X[i_batch]
                    y_batch = Y[i_batch]
                    ...

        Other examples:

        .. testcode::

            dataset_size = 10  # len(dataset)
            for batch_idx in delu.data.make_index_dataloader(
                dataset_size, batch_size=3
            ):
                print(batch_idx)

        .. testoutput::

            tensor([0, 1, 2])
            tensor([3, 4, 5])
            tensor([6, 7, 8])
            tensor([9])

        .. testcode::

            dataset_size = 10  # len(dataset)
            for batch_idx in delu.data.make_index_dataloader(
                dataset_size, 3, drop_last=True
            ):
                print(batch_idx)

        .. testoutput::

            tensor([0, 1, 2])
            tensor([3, 4, 5])
            tensor([6, 7, 8])
    See also:
        `delu.iter_batches`
    """
    return DataLoader(IndexDataset(size), *args, **kwargs)


@deprecated('Instead, use `delu.data.IndexDataset` and `~torch.utils.data.DataLoader`')
class IndexLoader:
    """Like `~torch.utils.data.DataLoader`, but over indices instead of data.

    **The shuffling logic is delegated to the native PyTorch DataLoader**, i.e. no
    custom logic is performed under the hood. The data loader which actually generates
    indices is available as `IndexLoader.loader`.

    Examples:

        Usage for training:

        .. code-block::

            train_loader = delu.data.IndexLoader(
                len(train_dataset), batch_size, shuffle=True
            )
            for epoch in range(n_epochs):
                for batch_idx in train_loader:
                    ...

        Other examples:

        .. testcode::

            dataset_size = 10  # len(dataset)
            for batch_idx in delu.data.IndexLoader(dataset_size, batch_size=3):
                print(batch_idx)

        .. testoutput::

            tensor([0, 1, 2])
            tensor([3, 4, 5])
            tensor([6, 7, 8])
            tensor([9])

        .. testcode::

            dataset_size = 10  # len(dataset)
            for batch_idx in delu.data.IndexLoader(dataset_size, 3, drop_last=True):
                print(batch_idx)

        .. testoutput::

            tensor([0, 1, 2])
            tensor([3, 4, 5])
            tensor([6, 7, 8])

    See also:
        `delu.iter_batches`
    """

    def __init__(
        self, size: int, *args, device: Union[int, str, torch.device] = 'cpu', **kwargs
    ) -> None:
        """Initialize self.

        Args:
            size: the number of items (for example, :code:`len(dataset)`)
            *args: positional arguments for `torch.utils.data.DataLoader`
            device: if not CPU, then all indices are materialized and moved to the
                device at the beginning of every loop. It can be useful when the indices
                are applied to non-CPU data (e.g. CUDA-tensors) and moving data between
                devices takes non-negligible time (which can happen in the case of
                simple and fast models like MLPs).
            **kwargs: keyword arguments for `torch.utils.data.DataLoader`
        Raises:
            AssertionError: if size is not positive
        """
        assert size > 0
        self._batch_size = args[0] if args else kwargs.get('batch_size', 1)
        self._loader = DataLoader(IndexDataset(size), *args, **kwargs)
        if isinstance(device, (int, str)):
            device = torch.device(device)
        self._device = device

    @property
    def loader(self) -> DataLoader:
        """The underlying DataLoader."""
        return self._loader

    def __len__(self) -> int:
        """Get the size of the underlying DataLoader."""
        return len(self.loader)

    def __iter__(self):
        return iter(
            self._loader
            if self._device.type == 'cpu'
            else torch.cat(list(self.loader)).to(self._device).split(self._batch_size)
        )


@deprecated('Instead, use `torch.utils.data.dataloader.default_collate`')
def collate(iterable: Iterable) -> Any:
    """Almost an alias for :code:`torch.utils.data.dataloader.default_collate`.
    Namely, the input is allowed to be any kind of iterable, not only a list. Firstly,
    if it is not a list, it is transformed to a list. Then, the list is passed to the
    original function and the result is returned as is.
    """
    if not isinstance(iterable, list):
        iterable = list(iterable)
    # > Module has no attribute "default_collate"
    return torch.utils.data.dataloader.default_collate(iterable)  # type: ignore
