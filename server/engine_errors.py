"""Exceptions shared by the worker and inference pipelines."""


class Canceled(Exception):
    """The current inference job was interrupted by its owner."""


class MemoryPressure(Exception):
    """Not enough GPU execution headroom, even after offloading resident models."""
