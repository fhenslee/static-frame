from __future__ import annotations

import typing as tp

import numpy as np
from numpy.ma import MaskedArray

from static_frame.core.assign import Assign
from static_frame.core.doc_str import doc_inject
from static_frame.core.util import NULL_SLICE
from static_frame.core.util import AnyCallable
from static_frame.core.util import DtypesSpecifier
from static_frame.core.util import TLocSelector
from static_frame.core.util import TLocSelectorCompound
from static_frame.core.util import TBlocKey
from static_frame.core.util import TILocSelector

# from static_frame.core.util import AnyCallable

if tp.TYPE_CHECKING:
    from static_frame.core.batch import Batch  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.bus import Bus  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.frame import Frame  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.frame import FrameAssignILoc  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.frame import FrameAsType  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.index import Index  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.index_base import IndexBase  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.index_hierarchy import IndexHierarchy  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.index_hierarchy import IndexHierarchyAsType  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.series import Series  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.series import SeriesAssign  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.type_blocks import TypeBlocks  # pylint: disable = W0611 #pragma: no cover
    from static_frame.core.yarn import Yarn  # pylint: disable = W0611 #pragma: no cover

    NDArrayAny = np.ndarray[tp.Any, tp.Any] # pylint: disable=W0611 #pragma: no cover
    DtypeAny = np.dtype[tp.Any] # pylint: disable=W0611 #pragma: no cover

#-------------------------------------------------------------------------------
FrameOrSeries = tp.Union['Frame', 'Series']

TContainer = tp.TypeVar('TContainer',
        'Index',
        'Series',
        'Frame',
        'TypeBlocks',
        'Bus',
        'Batch',
        'Yarn',
        # 'Quilt',
        'IndexHierarchy',
        'SeriesAssign',
        'FrameAssignILoc',
         # cannot be NDArrayAny as not available in old NumPy
        np.ndarray, # type: ignore
        MaskedArray, # type: ignore
        FrameOrSeries,
        )
GetItemFunc = tp.TypeVar('GetItemFunc',
        bound=tp.Callable[[TLocSelector], TContainer]
        )



class Interface(tp.Generic[TContainer]):
    __slots__ = ()
    INTERFACE: tp.Tuple[str, ...] = ()

class InterfaceBatch:
    __slots__ = ()
    INTERFACE: tp.Tuple[str, ...] = ()


class InterfaceGetItemLoc(Interface[TContainer]):

    __slots__ = ('_func',)
    INTERFACE = ('__getitem__',)

    _func: tp.Callable[[TLocSelector], TContainer]

    def __init__(self, func: tp.Callable[[TLocSelector], TContainer]) -> None:
        self._func = func

    def __getitem__(self, key: TLocSelector) -> TContainer:
        return self._func(key)

class InterfaceGetItemILoc(Interface[TContainer]):

    __slots__ = ('_func',)
    INTERFACE = ('__getitem__',)

    _func: tp.Callable[[TILocSelector], TContainer]

    def __init__(self, func: tp.Callable[[TILocSelector], TContainer]) -> None:
        self._func = func

    def __getitem__(self, key: TILocSelector) -> TContainer:
        return self._func(key)


class InterfaceGetItemCompound(Interface[TContainer]):

    __slots__ = ('_func',)
    INTERFACE = ('__getitem__',)

    _func: tp.Callable[[TLocSelectorCompound], TContainer]

    def __init__(self, func: tp.Callable[[TLocSelectorCompound], TContainer]) -> None:
        self._func = func

    def __getitem__(self, key: TLocSelectorCompound) -> TContainer:
        return self._func(key)

class InterfaceGetItemBLoc(Interface[TContainer]):

    __slots__ = ('_func',)
    INTERFACE = ('__getitem__',)

    _func: tp.Callable[[TBlocKey], TContainer]

    def __init__(self, func: tp.Callable[[TBlocKey], TContainer]) -> None:
        self._func = func

    def __getitem__(self, key: TBlocKey) -> TContainer:
        return self._func(key)


#-------------------------------------------------------------------------------

class InterfaceSelectDuo(Interface[TContainer]):
    '''An instance to serve as an interface to all of iloc and loc
    '''

    __slots__ = (
            '_func_iloc',
            '_func_loc',
            )
    INTERFACE = ('iloc', 'loc')

    def __init__(self, *,
            func_iloc: GetItemFunc,
            func_loc: GetItemFunc) -> None:

        self._func_iloc = func_iloc
        self._func_loc = func_loc

    @property
    def iloc(self) -> InterfaceGetItemLoc[TContainer]:
        return InterfaceGetItemLoc(self._func_iloc)

    @property
    def loc(self) -> InterfaceGetItemLoc[TContainer]:
        return InterfaceGetItemLoc(self._func_loc)

class InterfaceSelectTrio(Interface[TContainer]):
    '''An instance to serve as an interface to all of iloc, loc, and __getitem__ extractors.
    '''

    __slots__ = (
            '_func_iloc',
            '_func_loc',
            '_func_getitem',
            )
    INTERFACE = ('__getitem__', 'iloc', 'loc')

    def __init__(self, *,
            func_iloc: GetItemFunc,
            func_loc: GetItemFunc,
            func_getitem: GetItemFunc,
            ) -> None:

        self._func_iloc = func_iloc
        self._func_loc = func_loc
        self._func_getitem = func_getitem

    def __getitem__(self, key: TLocSelector) -> tp.Any:
        '''Label-based selection.
        '''
        return self._func_getitem(key)

    @property
    def iloc(self) -> InterfaceGetItemLoc[TContainer]:
        '''Integer-position based selection.'''
        return InterfaceGetItemLoc(self._func_iloc)

    @property
    def loc(self) -> InterfaceGetItemLoc[TContainer]:
        '''Label-based selection.
        '''
        return InterfaceGetItemLoc(self._func_loc)


class InterfaceSelectQuartet(Interface[TContainer]):
    '''An instance to serve as an interface to all of iloc, loc, and __getitem__ extractors.
    '''

    __slots__ = (
            '_func_iloc',
            '_func_loc',
            '_func_getitem',
            '_func_bloc',
            )
    INTERFACE = ('__getitem__', 'iloc', 'loc', 'bloc')

    def __init__(self, *,
            func_iloc: GetItemFunc,
            func_loc: GetItemFunc,
            func_getitem: GetItemFunc,
            func_bloc: tp.Any, # not sure what is the right type
            ) -> None:

        self._func_iloc = func_iloc
        self._func_loc = func_loc
        self._func_getitem = func_getitem
        self._func_bloc = func_bloc

    def __getitem__(self, key: TLocSelector) -> tp.Any:
        '''Label-based selection.
        '''
        return self._func_getitem(key)

    @property
    def bloc(self) -> InterfaceGetItemLoc[TContainer]:
        '''Boolean based assignment.'''
        return InterfaceGetItemLoc(self._func_bloc)

    @property
    def iloc(self) -> InterfaceGetItemLoc[TContainer]:
        '''Integer-position based assignment.'''
        return InterfaceGetItemLoc(self._func_iloc)

    @property
    def loc(self) -> InterfaceGetItemLoc[TContainer]:
        '''Label-based assignment.
        '''
        return InterfaceGetItemLoc(self._func_loc)


#-------------------------------------------------------------------------------

class InterfaceAssignTrio(InterfaceSelectTrio[TContainer]):
    '''For assignment with __getitem__, iloc, loc.
    '''

    __slots__ = ('delegate',)

    def __init__(self, *,
            func_iloc: GetItemFunc,
            func_loc: GetItemFunc,
            func_getitem: GetItemFunc,
            delegate: tp.Type[Assign]
            ) -> None:
        InterfaceSelectTrio.__init__(self,
                func_iloc=func_iloc,
                func_loc=func_loc,
                func_getitem=func_getitem,
                )
        self.delegate = delegate #pylint: disable=E0237


class InterfaceAssignQuartet(InterfaceSelectQuartet[TContainer]):
    '''For assignment with __getitem__, iloc, loc, bloc.
    '''
    __slots__ = ('delegate',)

    def __init__(self, *,
            func_iloc: GetItemFunc,
            func_loc: GetItemFunc,
            func_getitem: GetItemFunc,
            func_bloc: tp.Any, # not sure what is the right type
            delegate: tp.Type[Assign]
            ) -> None:
        InterfaceSelectQuartet.__init__(self,
                func_iloc=func_iloc,
                func_loc=func_loc,
                func_getitem=func_getitem,
                func_bloc=func_bloc,
                )
        self.delegate = delegate #pylint: disable=E0237


#-------------------------------------------------------------------------------

class InterfaceFrameAsType(Interface[TContainer]):
    __slots__ = ('_func_getitem',)
    INTERFACE = ('__getitem__', '__call__')

    def __init__(self,
            func_getitem: tp.Callable[[TLocSelector], 'FrameAsType']
            ) -> None:
        '''
        Args:
            _func_getitem: a callable that expects a _func_getitem key and returns a FrameAsType interface; for example, Frame._extract_getitem_astype.
        '''
        self._func_getitem = func_getitem

    @doc_inject(selector='selector')
    def __getitem__(self, key: TLocSelector) -> 'FrameAsType':
        '''Selector of columns by label.

        Args:
            key: {key_loc}
        '''
        return self._func_getitem(key)

    def __call__(self,
            dtype: DtypeAny,
            *,
            consolidate_blocks: bool = False,
            ) -> 'Frame':
        '''
        Apply a single ``dtype`` to all columns.
        '''

        return self._func_getitem(NULL_SLICE)(
                dtype,
                consolidate_blocks=consolidate_blocks,
                )


class InterfaceIndexHierarchyAsType(Interface[TContainer]):
    __slots__ = ('_func_getitem',)
    INTERFACE = ('__getitem__', '__call__')

    def __init__(self,
            func_getitem: tp.Callable[[TLocSelector], 'IndexHierarchyAsType']
            ) -> None:
        '''
        Args:
            _func_getitem: a callable that expects a _func_getitem key and returns a IndexHierarchyAsType interface; for example, Frame._extract_getitem_astype.
        '''
        self._func_getitem = func_getitem

    @doc_inject(selector='selector')
    def __getitem__(self, key: TLocSelector) -> 'IndexHierarchyAsType':
        '''Selector of columns by label.

        Args:
            key: {key_loc}
        '''
        return self._func_getitem(key)

    def __call__(self,
            dtype: DtypeAny,
            *,
            consolidate_blocks: bool = False,
            ) -> 'IndexHierarchy':
        '''
        Apply a single ``dtype`` to all columns.
        '''
        return self._func_getitem(NULL_SLICE)(
                dtype,
                consolidate_blocks=consolidate_blocks,
                )



class BatchAsType:

    __slots__ = ('_batch_apply', '_column_key')

    def __init__(self,
            batch_apply: tp.Callable[[AnyCallable], 'Batch'],
            column_key: TLocSelector
            ) -> None:
        self._batch_apply = batch_apply
        self._column_key = column_key

    def __call__(self,
            dtypes: DtypesSpecifier,
            *,
            consolidate_blocks: bool = False,
            ) -> 'Batch':
        return self._batch_apply(
                lambda c: c.astype[self._column_key](
                    dtypes,
                    consolidate_blocks=consolidate_blocks,
                    )
                )

class InterfaceBatchAsType(Interface[TContainer]):
    '''An instance to serve as an interface to __getitem__ extractors. Used by both :obj:`Frame` and :obj:`IndexHierarchy`.
    '''

    __slots__ = ('_batch_apply',)
    INTERFACE = ('__getitem__', '__call__')

    def __init__(self,
            batch_apply: tp.Callable[[AnyCallable], 'Batch'],
            ) -> None:
        self._batch_apply = batch_apply

    @doc_inject(selector='selector')
    def __getitem__(self, key: TLocSelector) -> BatchAsType:
        '''Selector of columns by label.

        Args:
            key: {key_loc}
        '''
        return BatchAsType(batch_apply=self._batch_apply, column_key=key)

    def __call__(self, dtype: DtypeAny) -> 'Batch':
        '''
        Apply a single ``dtype`` to all columns.
        '''
        return BatchAsType(
                batch_apply=self._batch_apply,
                column_key=NULL_SLICE,
                )(dtype)


#-------------------------------------------------------------------------------

class InterfaceConsolidate(Interface[TContainer]):
    '''An instance to serve as an interface to __getitem__ extractors.
    '''

    __slots__ = (
            '_container',
            '_func_getitem',
            )

    INTERFACE = (
            '__getitem__',
            '__call__',
            'status',
            )

    def __init__(self,
            container: TContainer,
            func_getitem: tp.Callable[[TLocSelector], 'Frame']
            ) -> None:
        '''
        Args:
            _func_getitem: a callable that expects a _func_getitem key and returns a Frame interface.
        '''
        self._container: TContainer = container
        self._func_getitem = func_getitem

    @doc_inject(selector='selector')
    def __getitem__(self, key: TLocSelector) -> 'Frame':
        '''Selector of columns by label for consolidation.

        Args:
            key: {key_loc}
        '''
        return self._func_getitem(key)

    def __call__(self) -> 'Frame':
        '''
        Apply consolidation to all columns.
        '''
        return self._func_getitem(NULL_SLICE)

    @property
    def status(self) -> 'Frame':
        '''Display consolidation status of this Frame.
        '''
        from static_frame.core.frame import Frame

        flag_attrs: tp.Tuple[str, ...] = ('owndata', 'f_contiguous', 'c_contiguous')
        columns: IndexBase = self._container.columns # type: ignore

        def gen() -> tp.Tuple[DtypeAny, tp.Tuple[int, ...], int]:
            iloc_start = 0

            for b in self._container._blocks._blocks: # type: ignore
                width = 1 if b.ndim == 1 else b.shape[1]

                iloc_end = iloc_start + width
                if iloc_end >= len(columns):
                    iloc_slice = slice(iloc_start, None)
                else:
                    iloc_slice = slice(iloc_start, iloc_end)

                sub = columns[iloc_slice] # returns a column
                iloc: tp.Union[int, slice]
                if len(sub) == 1:
                    loc = sub[0]
                    iloc = iloc_start
                else: # get inclusive slice
                    loc = slice(sub[0], sub[-1])
                    iloc = iloc_slice

                yield [loc, iloc, b.dtype, b.shape, b.ndim] + [
                    getattr(b.flags, attr) for attr in flag_attrs]

                iloc_start = iloc_end

        return Frame.from_records(gen(),
            columns=('loc', 'iloc', 'dtype', 'shape', 'ndim') + flag_attrs
            )



