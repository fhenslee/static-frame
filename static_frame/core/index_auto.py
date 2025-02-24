from __future__ import annotations

import typing as tp

import numpy as np

from static_frame.core.exception import InvalidDatetime64Initializer
from static_frame.core.index import Index
from static_frame.core.index import IndexGO
from static_frame.core.index_base import IndexBase  # pylint: disable = W0611
from static_frame.core.index_datetime import IndexDatetime  # base class
from static_frame.core.util import DTYPE_INT_DEFAULT
from static_frame.core.util import NAME_DEFAULT
from static_frame.core.util import CallableOrMapping
from static_frame.core.util import ExplicitConstructor
from static_frame.core.util import IndexConstructor
from static_frame.core.util import IndexInitializer
from static_frame.core.util import NameType
from static_frame.core.util import PositionsAllocator
from static_frame.core.util import TLabel
from static_frame.core.util import iterable_to_array_1d


class IndexConstructorFactoryBase:
    def __call__(self,
            labels: tp.Iterable[TLabel],
            *,
            name: NameType = NAME_DEFAULT,
            default_constructor: tp.Type[IndexBase],
            ) -> IndexBase:
        raise NotImplementedError() #pragma: no cover

class IndexDefaultConstructorFactory(IndexConstructorFactoryBase):
    '''
    Token class to be used to provide a ``name`` to a default constructor of an Index. To be used as an index constructor argument. An instance must be created.
    '''

    __slots__ = ('_name',)

    def __init__(self, name: NameType):
        self._name = name

    def __call__(self,
            labels: tp.Iterable[TLabel],
            *,
            name: NameType = NAME_DEFAULT,
            default_constructor: tp.Type[IndexBase],
            ) -> IndexBase:
        '''Call the passed constructor with the ``name``.
        '''
        name = self._name if name is NAME_DEFAULT else name
        return default_constructor(labels, name=name)

class IndexAutoConstructorFactory(IndexConstructorFactoryBase):
    '''
    Token class to be used to automatically determine index type by array dtype; can also provide a ``name`` attribute. To be used as a constructor argument. An instance or a class can be used.
    '''
    __slots__ = ('_name',)

    def __init__(self, name: NameType):
        self._name = name

    @staticmethod
    def to_index(labels: tp.Iterable[TLabel],
            *,
            default_constructor: tp.Type[IndexBase],
            name: NameType = None,
            ) -> IndexBase:
        '''Create and return the ``Index`` based on the array ``dtype``
        '''
        from static_frame.core.index_datetime import dtype_to_index_cls

        if labels.__class__ is not np.ndarray:
            # we can assume that this is 1D; returns an immutable array
            labels, _ = iterable_to_array_1d(labels)

        return dtype_to_index_cls(
                static=default_constructor.STATIC,
                dtype=labels.dtype)(labels, name=name) #type: ignore

    def __call__(self,
            labels: tp.Iterable[TLabel],
            *,
            name: NameType = NAME_DEFAULT,
            default_constructor: tp.Type[IndexBase] = Index,
            ) -> IndexBase:
        '''Call the passeed constructor with the ``name``.
        '''
        name = self._name if name is NAME_DEFAULT else name
        return self.to_index(labels,
                default_constructor=default_constructor,
                name=name,
                )



#---------------------------------------------------------------------------

IndexAutoInitializer = int

# could create trival subclasses for these indices, but the type would would not always describe the instance; for example, an IndexAutoGO could grow into non-contiguous integer index, as loc_is_iloc is reevaluated with each append can simply go to false.

class IndexAutoFactory:
    '''Class to be used as an ``index`` or ``columns`` argument (not as a constructor) to specify the creation of an auto-incremented integer index.
    '''
    __slots__ = ('_size', '_name')

    @classmethod
    def from_optional_constructor(cls,
            initializer: IndexAutoInitializer, # size
            *,
            default_constructor: IndexConstructor,
            explicit_constructor: ExplicitConstructor = None,
            ) -> IndexBase:

        # get an immutable array, shared from positions allocator
        labels = PositionsAllocator.get(initializer)

        if explicit_constructor:
            # NOTE: we raise when a Python integer is given to a dt64 index, but accept an NP array of integers; labels here is already an array, this would work without an explicit check.
            if isinstance(explicit_constructor, type) and issubclass(explicit_constructor, IndexDatetime):
                raise InvalidDatetime64Initializer(f'Attempting to create {explicit_constructor.__name__} from an {cls.__name__}, which is generally not desired as the result will be an offset from the epoch. Supply explicit labels.')
            if isinstance(explicit_constructor, IndexDefaultConstructorFactory):
                return explicit_constructor(labels,
                        default_constructor=default_constructor, # type: ignore
                        # NOTE might just pass name
                        )
            return explicit_constructor(labels) # type: ignore

        else: # get from default constructor
            assert default_constructor is not None
            constructor = Index if default_constructor.STATIC else IndexGO # type: ignore
            return constructor(
                    labels=labels,
                    loc_is_iloc=True,
                    dtype=DTYPE_INT_DEFAULT
                    )

    def __init__(self,
            size: IndexAutoInitializer,
            *,
            name: NameType = None,
            ):
        self._size = size
        self._name = name

    def to_index(self,
            *,
            default_constructor: IndexConstructor,
            explicit_constructor: ExplicitConstructor = None,
            ) -> IndexBase:
        '''Called by index_from_optional_constructor.
        '''
        return self.from_optional_constructor(self._size,
                default_constructor=default_constructor,
                explicit_constructor=explicit_constructor,
                )



IndexAutoFactoryType = tp.Type[IndexAutoFactory]
RelabelInput = tp.Union[CallableOrMapping, IndexAutoFactoryType, IndexInitializer]

IndexInitOrAutoType = tp.Optional[tp.Union[IndexInitializer, IndexAutoFactoryType, IndexAutoFactory]]


