import typing as tp
import sqlite3
import csv
import json
from collections import namedtuple
from functools import partial

import numpy as np # type: ignore

from numpy.ma import MaskedArray

from static_frame.core.util import UFunc
from static_frame.core.util import DEFAULT_SORT_KIND
from static_frame.core.util import DTYPE_FLOAT_DEFAULT

from static_frame.core.util import NULL_SLICE
from static_frame.core.util import KEY_MULTIPLE_TYPES
from static_frame.core.util import INT_TYPES
from static_frame.core.util import GetItemKeyType
from static_frame.core.util import GetItemKeyTypeCompound
from static_frame.core.util import KeyOrKeys
from static_frame.core.util import PathSpecifier
from static_frame.core.util import PathSpecifierOrFileLike
from static_frame.core.util import DtypesSpecifier
from static_frame.core.util import FILL_VALUE_DEFAULT

from static_frame.core.util import IndexSpecifier
from static_frame.core.util import IndexInitializer
from static_frame.core.util import IndexConstructor
from static_frame.core.util import IndexConstructors

from static_frame.core.util import FrameInitializer
from static_frame.core.util import FRAME_INITIALIZER_DEFAULT
from static_frame.core.util import column_2d_filter
from static_frame.core.util import column_1d_filter

from static_frame.core.util import name_filter
from static_frame.core.util import _gen_skip_middle
from static_frame.core.util import iterable_to_array
# from static_frame.core.util import _dict_to_sorted_items
from static_frame.core.util import array_to_duplicated
from static_frame.core.util import ufunc_set_iter
from static_frame.core.util import array2d_to_tuples
from static_frame.core.util import _read_url
from static_frame.core.util import write_optional_file
from static_frame.core.util import ufunc_unique
# from static_frame.core.util import STATIC_ATTR
from static_frame.core.util import concat_resolved
from static_frame.core.util import DepthLevelSpecifier
from static_frame.core.util import array_to_groups_and_locations
from static_frame.core.util import is_callable_or_mapping

from static_frame.core.util import argmin_2d
from static_frame.core.util import argmax_2d
from static_frame.core.util import resolve_dtype

from static_frame.core.selector_node import InterfaceGetItem
from static_frame.core.selector_node import InterfaceSelection2D
from static_frame.core.selector_node import InterfaceAsType

from static_frame.core.index_correspondence import IndexCorrespondence
from static_frame.core.container import ContainerOperand
from static_frame.core.container_util import matmul
from static_frame.core.container_util import index_from_optional_constructor

from static_frame.core.iter_node import IterNodeApplyType
from static_frame.core.iter_node import IterNodeType
from static_frame.core.iter_node import IterNode

from static_frame.core.display import DisplayConfig
from static_frame.core.display import DisplayActive
from static_frame.core.display import Display
from static_frame.core.display import DisplayFormats
from static_frame.core.display import DisplayHeader

from static_frame.core.type_blocks import TypeBlocks

from static_frame.core.series import Series
from static_frame.core.series import RelabelInput

from static_frame.core.index_base import IndexBase

from static_frame.core.index import Index
from static_frame.core.index import IndexGO
from static_frame.core.index import _requires_reindex
from static_frame.core.index import _index_initializer_needs_init
from static_frame.core.index import immutable_index_filter

from static_frame.core.index_hierarchy import IndexHierarchy
from static_frame.core.index_hierarchy import IndexHierarchyGO

from static_frame.core.index_auto import IndexAutoFactory
from static_frame.core.index_auto import IndexAutoFactoryType

from static_frame.core.store_filter import StoreFilter
from static_frame.core.store_filter import STORE_FILTER_DEFAULT

from static_frame.core.exception import ErrorInitFrame

from static_frame.core.doc_str import doc_inject

if tp.TYPE_CHECKING:
    import pandas as pd # type: ignore #pylint: disable=W0611
    from xarray import Dataset # type: ignore #pylint: disable=W0611


def dtypes_mappable(dtypes: DtypesSpecifier):
    '''
    Determine if the dtypes argument can be used by name lookup, rather than index.
    '''
    return isinstance(dtypes, (dict, Series))


@doc_inject(selector='container_init', class_name='Frame')
class Frame(ContainerOperand):
    '''
    A two-dimensional ordered, labelled collection, immutable and of fixed size.

    Args:
        data: A Frame initializer, given as either a NumPy array, a single value (to be used to fill a shape defined by ``index`` and ``columns``), or an iterable suitable to given to the NumPy array constructor.
        {index}
        {columns}
        {own_data}
        {own_index}
        {own_columns}
    '''

    __slots__ = (
            '_blocks',
            '_columns',
            '_index',
            '_name'
            )

    _blocks: TypeBlocks
    _columns: IndexBase
    _index: IndexBase
    _name: tp.Hashable

    _COLUMNS_CONSTRUCTOR = Index
    _NDIM: int = 2

    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_concat(cls,
            frames: tp.Iterable[tp.Union['Frame', Series]],
            *,
            axis: int = 0,
            union: bool = True,
            index: tp.Union[IndexInitializer, IndexAutoFactoryType] = None,
            columns: tp.Union[IndexInitializer, IndexAutoFactoryType] = None,
            name: tp.Hashable = None,
            fill_value: object = np.nan,
            consolidate_blocks: bool = False
            ) -> 'Frame':
        '''
        Concatenate multiple Frames into a new Frame. If index or columns are provided and appropriately sized, the resulting Frame will use those indices. If the axis along concatenation (index for axis 0, columns for axis 1) is unique after concatenation, it will be preserved; otherwise, a new index or an :obj:`IndexAutoFactory` must be supplied.

        Args:
            frames: Iterable of Frames.
            axis: Integer specifying 0 to concatenate supplied Frames vertically (aligning on columns), 1 to concatenate horizontally (aligning on rows).
            union: If True, the union of the aligned indices is used; if False, the intersection is used.
            index: Optionally specify a new index.
            columns: Optionally specify new columns.
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''

        # when doing axis 1 concat (growin horizontally) Series need to be presented as rows (axis 0)
        # axis_series = (0 if axis is 1 else 1)
        frames = [f if isinstance(f, Frame) else f.to_frame(axis) for f in frames]

        # switch if we have reduced the columns argument to an array
        from_array_columns = False
        from_array_index = False

        own_columns = False
        own_index = False

        if axis == 1: # stacks columns (extends rows horizontally)
            # index can be the same, columns must be redefined if not unique
            if columns is IndexAutoFactory:
                columns = None # let default creation happen
            elif columns is None:
                # returns immutable array
                columns = concat_resolved([frame._columns.values for frame in frames])
                from_array_columns = True
                # avoid sort for performance; always want rows if ndim is 2
                if len(ufunc_unique(columns, axis=0)) != len(columns):
                    raise ErrorInitFrame('Column names after horizontal concatenation are not unique; supply a columns argument or IndexAutoFactory.')

            if index is IndexAutoFactory:
                raise ErrorInitFrame('for axis 1 concatenation, index must be used for reindexing row alignment: IndexAutoFactory is not permitted')
            elif index is None:
                # get the union index, or the common index if identical
                index = ufunc_set_iter(
                        (frame._index.values for frame in frames),
                        union=union,
                        assume_unique=True # all from indices
                        )
                index.flags.writeable = False
                from_array_index = True

            def blocks():
                for frame in frames:
                    if len(frame.index) != len(index) or (frame.index != index).any():
                        frame = frame.reindex(index=index, fill_value=fill_value)
                    for block in frame._blocks._blocks:
                        yield block

        elif axis == 0: # stacks rows (extends columns vertically)
            if index is IndexAutoFactory:
                index = None # let default creationn happen
            elif index is None:
                # returns immutable array
                index = concat_resolved([frame._index.values for frame in frames])
                from_array_index = True
                # avoid sort for performance; always want rows if ndim is 2
                if len(ufunc_unique(index, axis=0)) != len(index):
                    raise ErrorInitFrame('Index names after vertical concatenation are not unique; supply an index argument or IndexAutoFactory.')

            if columns is IndexAutoFactory:
                raise ErrorInitFrame('for axis 0 concatenation, columns must be used for reindexing and column alignment: IndexAutoFactory is not permitted')
            elif columns is None:
                columns = ufunc_set_iter(
                        (frame._columns.values for frame in frames),
                        union=union,
                        assume_unique=True
                        )
                # import ipdb; ipdb.set_trace()
                columns.flags.writeable = False
                from_array_columns = True

            def blocks():
                aligned_frames = []
                previous_frame = None
                block_compatible = True
                reblock_compatible = True

                for frame in frames:
                    if len(frame.columns) != len(columns) or (frame.columns != columns).any():
                        frame = frame.reindex(columns=columns, fill_value=fill_value)
                    aligned_frames.append(frame)
                    # column size is all the same by this point
                    if previous_frame is not None:
                        if block_compatible:
                            block_compatible &= frame._blocks.block_compatible(
                                    previous_frame._blocks,
                                    axis=1) # only compare columns
                        if reblock_compatible:
                            reblock_compatible &= frame._blocks.reblock_compatible(
                                    previous_frame._blocks)
                    previous_frame = frame

                if block_compatible or reblock_compatible:
                    if not block_compatible and reblock_compatible:
                        # after reblocking, will be compatible
                        type_blocks = [f._blocks.consolidate() for f in aligned_frames]
                    else: # blocks by column are compatible
                        type_blocks = [f._blocks for f in aligned_frames]

                    # all TypeBlocks have the same number of blocks by here
                    for block_idx in range(len(type_blocks[0]._blocks)):
                        block_parts = []
                        for frame_idx in range(len(type_blocks)):
                            b = column_2d_filter(
                                    type_blocks[frame_idx]._blocks[block_idx])
                            block_parts.append(b)
                        # returns immutable array
                        yield concat_resolved(block_parts)
                else:
                    # must just combine .values; returns immutable array
                    yield concat_resolved([frame.values for frame in frames])
        else:
            raise NotImplementedError('no support for axis', axis)

        if from_array_columns:
            if columns.ndim == 2: # we have a hierarchical index
                cls_ih = (IndexHierarchy
                        if cls._COLUMNS_CONSTRUCTOR.STATIC else IndexHierarchyGO)
                columns = cls_ih.from_labels(columns)
                own_columns = True

        if from_array_index:
            if index.ndim == 2: # we have a hierarchical index
                index = IndexHierarchy.from_labels(index)
                own_index = True

        if consolidate_blocks:
            block_gen = lambda: TypeBlocks.consolidate_blocks(blocks())
        else:
            block_gen = blocks

        return cls(TypeBlocks.from_blocks(block_gen()),
                index=index,
                columns=columns,
                name=name,
                own_data=True,
                own_columns=own_columns,
                own_index=own_index)


    @classmethod
    def from_concat_items(cls,
            items: tp.Iterable[tp.Tuple[tp.Hashable, 'Frame']],
            *,
            axis: int = 0,
            union: bool = True,
            name: tp.Hashable = None,
            fill_value: object = np.nan,
            consolidate_blocks: bool = False
            ) -> 'Frame':
        '''
        Produce a :obj:`Frame` with a hierarchical index from an iterable of pairs of labels, :obj:`Frame`. The :obj:`IndexHierarchy` is formed from the provided labels and the :obj:`Index` if each :obj:`Frame`.

        Args:
            items: Iterable of pairs of label, :obj:`Series`
        '''
        frames = []

        def gen():
            for label, frame in items:
                # must normalize Series here to avoid down-stream confusion
                if isinstance(frame, Series):
                    frame = frame.to_frame(axis)

                frames.append(frame)
                if axis == 0:
                    yield label, frame._index
                else:
                    yield label, frame._columns

        # populates array_values as side effect
        if axis == 0:
            ih = IndexHierarchy.from_index_items(gen())
            kwargs = dict(index=ih)
        else:
            cls_ih = (IndexHierarchy
                    if cls._COLUMNS_CONSTRUCTOR.STATIC else IndexHierarchyGO)
            ih = cls_ih.from_index_items(gen())
            kwargs = dict(columns=ih)

        return cls.from_concat(frames,
                axis=axis,
                union=union,
                name=name,
                fill_value=fill_value,
                consolidate_blocks=consolidate_blocks,
                **kwargs
                )


    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_records(cls,
            records: tp.Iterable[tp.Any],
            *,
            index: tp.Optional[IndexInitializer] = None,
            columns: tp.Optional[IndexInitializer] = None,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False,
            own_index: bool = False,
            own_columns: bool = False
            ) -> 'Frame':
        '''Frame constructor from an iterable of rows, where rows are defined as iterables, including tuples, lists, and dictionaries. If each row is a NamedTuple or dictionary, and ``columns`` is not provided, column names will be derived from the dictionary keys or NamedTuple fields.

        Note that rows defined as ``Series`` is not supported; use ``Frame.from_concat``; for creating a ``Frame`` from a single dictionary, where keys are column labels and values are columns, use ``Frame.from_dict``.

        Args:
            records: Iterable of row values, where row values are arrays, tuples, lists, dictionaries, or namedtuples.
            index: Optionally provide an iterable of index labels, equal in length to the number of records.
            columns: Optionally provide an iterable of column labels, equal in length to the length of each row.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        derive_columns = False
        if columns is None:
            derive_columns = True
            # leave columns list in outer scope for blocks() to populate
            columns = []

        # if records is np; we can just pass it to constructor, as is alrady a consolidate type
        if isinstance(records, np.ndarray):
            if dtypes is not None:
                raise ErrorInitFrame('specifying dtypes when using NP records is not permitted')
            return cls(records,
                    index=index,
                    columns=columns,
                    own_index=own_index,
                    own_columns=own_columns
                    )

        dtypes_is_map = dtypes_mappable(dtypes)

        def get_col_dtype(col_idx):
            if dtypes_is_map:
                return dtypes.get(columns[col_idx], None)
            return dtypes[col_idx]


        def blocks():

            if not hasattr(records, '__len__'):
                # might be a generator; must convert to sequence
                rows = list(records)
            else:
                # could be a sequence, or something like a dict view
                rows = records

            if not len(rows):
                raise ErrorInitFrame('no rows available in records.')

            if hasattr(rows, '__getitem__'):
                rows_to_iter = False
                row_reference = rows[0]
            else:
                # dict view, or other sized iterable that does not support getitem
                rows_to_iter = True
                row_reference = next(iter(rows))

            row_count = len(rows)
            col_count = len(row_reference)

            column_getter = None
            if isinstance(row_reference, dict):
                col_idx_iter = row_reference.keys()
                # col_idx_iter = (k for k, _ in _dict_to_sorted_items(row_reference))
                if derive_columns: # just pass the key back
                    column_getter = lambda key: key
            elif isinstance(row_reference, Series):
                raise ErrorInitFrame('Frame.from_records() does not support Series. Use Frame.from_concat() instead.')
            else:
                # all other iterables
                col_idx_iter = range(col_count)
                if hasattr(row_reference, '_fields') and derive_columns:
                    column_getter = row_reference._fields.__getitem__

            # derive types from first rows
            for col_idx, col_key in enumerate(col_idx_iter):
                if column_getter: # append as side effect of generator!
                    columns.append(column_getter(col_key))

                # for each column, try to get a column_type, or None
                if dtypes is None:
                    field_ref = row_reference[col_key]
                    # string, datetime64 types requires size in dtype specification, so cannot use np.fromiter, as we do not know the size of all columns
                    column_type = (type(field_ref)
                            if not isinstance(field_ref, (str, np.datetime64))
                            else None)
                    column_type_explicit = False
                else: # column_type returned here can be None.
                    column_type = get_col_dtype(col_idx)
                    column_type_explicit = True

                values = None
                if column_type is not None:
                    rows_iter = rows if not rows_to_iter else iter(rows)
                    try:
                        values = np.fromiter(
                                (row[col_key] for row in rows_iter),
                                count=row_count,
                                dtype=column_type)
                    except (ValueError, TypeError):
                        # the column_type may not be compatible, so must fall back on using np.array to determine the type, i.e., ValueError: cannot convert float NaN to integer
                        if not column_type_explicit:
                            # reset to None if not explicit and failued in fromiter
                            column_type = None
                if values is None:
                    rows_iter = rows if not rows_to_iter else iter(rows)
                    # let array constructor determine type if column_type is None
                    values = np.array([row[col_key] for row in rows_iter],
                            dtype=column_type)

                values.flags.writeable = False
                yield values

        if consolidate_blocks:
            block_gen = lambda: TypeBlocks.consolidate_blocks(blocks())
        else:
            block_gen = blocks

        return cls(TypeBlocks.from_blocks(block_gen()),
                index=index,
                columns=columns,
                name=name,
                own_data=True,
                own_index=own_index,
                own_columns=own_columns
                )


    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_records_items(cls,
            items: tp.Iterator[tp.Tuple[tp.Hashable, tp.Iterable[tp.Any]]],
            *,
            columns: tp.Optional[IndexInitializer] = None,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False) -> 'Frame':
        '''Frame constructor from iterable of pairs of index value, row (where row is an iterable).

        Args:
            items: Iterable of pairs of index label, row values, where row values are arrays, tuples, lists, dictionaries, or namedtuples.
            columns: Optionally provide an iterable of column labels, equal in length to the length of each row.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`

        '''
        index = []

        def gen():
            for label, values in items:
                index.append(label)
                yield values

        return cls.from_records(gen(),
                index=index,
                columns=columns,
                dtypes=dtypes,
                name=name,
                consolidate_blocks=consolidate_blocks
                )

    @classmethod
    def from_sql(cls,
            query: str,
            connection: sqlite3.Connection,
            ) -> 'Frame':
        '''
        Frame constructor from an SQL query and a database connection object.

        Args:
            query: A query string.
            connection: A DBAPI2 (PEP 249) Connection object, such as those returned from SQLite (via the sqlite3 module) or PyODBC.
        '''
        row_gen = connection.execute(query)

        columns = []
        for bundle in row_gen.description:
            columns.append(bundle[0])

        # let default type induction do its work
        return cls.from_records(row_gen, columns=columns)


    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_json(cls,
            json_data: str,
            *,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False
            ) -> 'Frame':
        '''Frame constructor from an in-memory JSON document.

        Args:
            json_data: a string of JSON, encoding a table as an array of JSON objects.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        data = json.loads(json_data)
        return cls.from_records(data,
                name=name,
                dtypes=dtypes,
                consolidate_blocks=consolidate_blocks
                )

    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_json_url(cls,
            url: str,
            *,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False
            ) -> 'Frame':
        '''Frame constructor from a JSON documenst provided via a URL.

        Args:
            url: URL to the JSON resource.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        return cls.from_json(_read_url(url),
                name=name,
                dtypes=dtypes,
                consolidate_blocks=consolidate_blocks
                )


    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_items(cls,
            pairs: tp.Iterable[tp.Tuple[tp.Hashable, tp.Iterable[tp.Any]]],
            *,
            index: IndexInitializer = None,
            fill_value: object = np.nan,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False
            ):
        '''Frame constructor from an iterator or generator of pairs, where the first value is the column name and the second value is an iterable of a single column's values.

        Args:
            pairs: Iterable of pairs of column name, column values.
            index: Iterable of values to create an Index.
            fill_value: If pairs include Series, they will be reindexed with the provided index; reindexing will use this fill value.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        columns = []

        # if an index initializer is passed, and we expect to get Series, we need to create the index in advance of iterating blocks
        own_index = False
        if _index_initializer_needs_init(index):
            index = Index(index)
            own_index = True

        dtypes_is_map = dtypes_mappable(dtypes)
        def get_col_dtype(col_idx):
            if dtypes_is_map:
                return dtypes.get(columns[col_idx], None)
            return dtypes[col_idx]

        def blocks():
            for col_idx, (k, v) in enumerate(pairs):
                columns.append(k) # side effet of generator!

                if dtypes:
                    column_type = get_col_dtype(col_idx)
                else:
                    column_type = None

                if isinstance(v, np.ndarray):
                    # NOTE: we rely on TypeBlocks constructor to check that these are same sized
                    if column_type is not None:
                        yield v.astype(column_type)
                    else:
                        yield v
                elif isinstance(v, Series):
                    if index is None:
                        raise ErrorInitFrame('can only consume Series in Frame.from_items if an Index is provided.')

                    if column_type is not None:
                        v = v.astype(column_type)

                    if _requires_reindex(v.index, index):
                        yield v.reindex(index, fill_value=fill_value).values
                    else:
                        yield v.values

                elif isinstance(v, Frame):
                    raise ErrorInitFrame('Frames are not supported in from_items constructor.')
                else:
                    values = np.array(v, dtype=column_type)
                    values.flags.writeable = False
                    yield values

        if consolidate_blocks:
            block_gen = lambda: TypeBlocks.consolidate_blocks(blocks())
        else:
            block_gen = blocks

        return cls(TypeBlocks.from_blocks(block_gen()),
                index=index,
                columns=columns,
                name=name,
                own_data=True,
                own_index=own_index)


    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_dict(cls,
            mapping: tp.Dict[tp.Hashable, tp.Iterable[tp.Any]],
            *,
            index: IndexInitializer = None,
            fill_value: object = np.nan,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False
            ) -> 'Frame':
        '''
        Create a Frame from a dictionary, or any object that has an items() method.

        Args:
            mapping: a dictionary or similar mapping interface.
            {dtypes}
            {name}
            {consolidate_blocks}
        '''
        return cls.from_items(mapping.items(),
                index=index,
                fill_value=fill_value,
                name=name,
                dtypes=dtypes,
                consolidate_blocks=consolidate_blocks)


    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_structured_array(cls,
            array: np.ndarray,
            *,
            index_depth: int = 0,
            index_column: tp.Optional[IndexSpecifier] = None,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False,
            store_filter: tp.Optional[StoreFilter] = STORE_FILTER_DEFAULT
            ) -> 'Frame':
        '''
        Convert a NumPy structed array into a Frame. Presently this always uses

        Args:
            array: Structured NumPy array.
            index_column: Optionally provide the name or position offset of the column to use as the index.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        # will be the header if this was parsed from a delimited file
        names = array.dtype.names

        index_start_pos = -1 # will be ignored
        if index_column is not None:
            if index_depth <= 0:
                raise ErrorInitFrame('index_column specified but index_depth is 0')
            elif isinstance(index_column, INT_TYPES):
                index_start_pos = index_column
            else:
                index_start_pos = names.index(index_column) # linear performance
        else: # no index_column specified, if index depth > 0, set start to 0
            if index_depth > 0:
                index_start_pos = 0


        # assign in generator; requires  reading through gen first
        # index_array = None
        index_arrays = []
        # cannot use names if we remove an index; might be a more efficient way as we know the size
        columns = []
        columns_by_col_idx = []

        dtypes_is_map = dtypes_mappable(dtypes)
        def get_col_dtype(col_idx):
            if dtypes_is_map:
                return dtypes.get(columns_by_col_idx[col_idx], None)
            return dtypes[col_idx]

        def blocks():
            # iterate over column names and yield one at a time for block construction; collect index arrays and column labels as we go
            for col_idx, name in enumerate(names):
                # append here as we iterate for usage in get_col_dtype
                columns_by_col_idx.append(name)

                # this is not expected to make a copy
                array_final = array[name]
                # do StoreFilter conversions before dtyp
                if store_filter is not None:
                    array_final = store_filter.to_type_filter_array(array_final)
                if dtypes:
                    dtype = get_col_dtype(col_idx)
                    if dtype is not None:
                        array_final = array_final.astype(dtype)

                # import ipdb; ipdb.set_trace()
                if col_idx >= index_start_pos and col_idx < index_start_pos + index_depth:
                    # nonlocal index_arrays
                    index_arrays.append(array_final)
                    continue

                columns.append(name)
                yield array_final

        if consolidate_blocks:
            block_gen = lambda: TypeBlocks.consolidate_blocks(blocks())
        else:
            block_gen = blocks

        if index_depth == 0:
            return cls(TypeBlocks.from_blocks(block_gen()),
                    columns=columns,
                    index=None,
                    name=name,
                    own_data=True)
        if index_depth == 1:
            return cls(TypeBlocks.from_blocks(block_gen()),
                    columns=columns,
                    index=index_arrays[0],
                    name=name,
                    own_data=True)
        if index_depth > 1:
            return cls(TypeBlocks.from_blocks(block_gen()),
                    columns=columns,
                    index=zip(*index_arrays),
                    index_constructor=IndexHierarchy.from_labels,
                    name=name,
                    own_data=True)

    #---------------------------------------------------------------------------
    # iloc/loc pairs constructors: these are not public, not sure if they should be

    @classmethod
    def from_element_iloc_items(cls,
            items,
            *,
            index,
            columns,
            dtype,
            name: tp.Hashable = None
            ) -> 'Frame':
        '''
        Given an iterable of pairs of iloc coordinates and values, populate a Frame as defined by the given index and columns. The dtype must be specified, and must be the same for all values.

        Returns:
            :py:class:`static_frame.Frame`
        '''
        index = Index(index)
        columns = cls._COLUMNS_CONSTRUCTOR(columns)

        tb = TypeBlocks.from_element_items(items,
                shape=(len(index), len(columns)),
                dtype=dtype)
        return cls(tb,
                index=index,
                columns=columns,
                name=name,
                own_data=True,
                own_index=True,
                own_columns=True)

    @classmethod
    def from_element_loc_items(cls,
            items: tp.Iterable[tp.Tuple[
                    tp.Tuple[tp.Hashable, tp.Hashable], tp.Any]],
            *,
            index: IndexInitializer,
            columns: IndexInitializer,
            dtype=None,
            name: tp.Hashable = None,
            fill_value: object = FILL_VALUE_DEFAULT,
            index_constructor: IndexConstructor = None,
            columns_constructor: IndexConstructor = None
            ) -> 'Frame':
        '''
        This function is partialed (setting the index and columns) and used by ``IterNodeDelegate`` as the apply constructor for doing application on element iteration.

        Args:
            items: an iterable of pairs of 2-tuples of row, column loc labels and values.


        Returns:
            :py:class:`static_frame.Frame`
        '''
        index = index_from_optional_constructor(index,
                default_constructor=Index,
                explicit_constructor=index_constructor
                )

        columns = index_from_optional_constructor(columns,
                default_constructor=cls._COLUMNS_CONSTRUCTOR,
                explicit_constructor=columns_constructor
                )

        items = (((index.loc_to_iloc(k[0]), columns.loc_to_iloc(k[1])), v)
                for k, v in items)

        dtype = dtype if dtype is not None else object

        tb = TypeBlocks.from_element_items(
                items,
                shape=(len(index), len(columns)),
                dtype=dtype,
                fill_value=fill_value)

        return cls(tb,
                index=index,
                columns=columns,
                name=name,
                own_data=True,
                own_index=True,
                own_columns=True)

    #---------------------------------------------------------------------------
    # file, data format loaders

    @classmethod
    @doc_inject(selector='constructor_frame')
    def from_csv(cls,
            fp: PathSpecifierOrFileLike,
            *,
            delimiter: str = ',',
            index_depth: int = 0,
            index_column: tp.Optional[tp.Union[int, str]] = None,
            columns_depth: int = 1,
            skip_header: int = 0,
            skip_footer: int = 0,
            quote_char: str = '"',
            encoding: tp.Optional[str] = None,
            dtypes: DtypesSpecifier = None,
            name: tp.Hashable = None,
            consolidate_blocks: bool = False,
            store_filter: tp.Optional[StoreFilter] = STORE_FILTER_DEFAULT
            ) -> 'Frame':
        '''
        Create a Frame from a file path or a file-like object defining a delimited (CSV, TSV) data file.

        Args:
            fp: A file path or a file-like object.
            delimiter: The character used to seperate row elements.
            index_depth: Specify the number of columns used to create the index labels; a value greater than 1 will attempt to create a hierarchical index.
            index_column: Optionally specify a column, by position or name, to become the start of the index if index_depth is greater than 0. If not set and index_depth is greater than 0, the first column will be used.
            columns_depth: Specify the number of rows after the skip_header used to create the column labels. A value of 0 will be no header; a value greater than 1 will attempt to create a hierarchical index.
            skip_header: Number of leading lines to skip.
            skip_footer: Number of trailing lines to skip.
            store_filter: A StoreFilter instance, defining translation between unrepresentable types. Presently only the ``to_nan`` attributes is used.
            {dtypes}
            {name}
            {consolidate_blocks}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        # https://docs.scipy.org/doc/numpy/reference/generated/numpy.loadtxt.html
        # https://docs.scipy.org/doc/numpy/reference/generated/numpy.genfromtxt.html

        if columns_depth > 1:
            raise NotImplementedError('reading hierarchical columns from a delimited file is not yet sypported')

        delimiter_native = '\t'

        if delimiter != delimiter_native:
            # this is necessary if there are quoted cells that include the delimiter
            def to_tsv():
                if isinstance(fp, str):
                    with open(fp, 'r') as f:
                        for row in csv.reader(f, delimiter=delimiter, quotechar=quote_char):
                            yield delimiter_native.join(row)
                else:
                    # handling file like object works for stringio but not for bytesio
                    for row in csv.reader(fp, delimiter=delimiter, quotechar=quote_char):
                        yield delimiter_native.join(row)
            file_like = to_tsv()
        else:
            file_like = fp

        # genfromtxt takes a missing_values, but this can only be a list, and does not work under some condition (i.e., a cell with no value). thus, this is deferred to from_sructured_array

        array = np.genfromtxt(file_like,
                delimiter=delimiter_native,
                skip_header=skip_header,
                skip_footer=skip_footer,
                # strange NP convention for this parameter: False it not supported, must convert to None
                names=None if columns_depth == 0 else True,
                dtype=None,
                encoding=encoding,
                invalid_raise=False,
                )

        # can own this array so set it as immutable
        array.flags.writeable = False
        return cls.from_structured_array(array,
                index_depth=index_depth,
                index_column=index_column,
                dtypes=dtypes,
                name=name,
                consolidate_blocks=consolidate_blocks,
                store_filter=store_filter,
                )

    @classmethod
    def from_tsv(cls,
            fp: PathSpecifierOrFileLike,
            **kwargs
            ) -> 'Frame':
        '''
        Specialized version of :py:meth:`Frame.from_csv` for TSV files.

        Returns:
            :py:class:`static_frame.Frame`
        '''
        return cls.from_csv(fp, delimiter='\t', **kwargs)

    @classmethod
    def from_xlsx(cls,
            fp: PathSpecifier,
            *,
            sheet_name: tp.Optional[str] = None,
            index_depth: int = 0,
            columns_depth: int = 1,
            dtypes: DtypesSpecifier = None
            ) -> 'Frame':
        '''
        Load Frame from the contents of a sheet in an XLSX workbook.
        '''
        from static_frame.core.store_xlsx import StoreXLSX

        st = StoreXLSX(fp)
        return st.read(sheet_name, # should this be called label?
            index_depth=index_depth,
            columns_depth=index_depth,
            dtypes=dtypes
            )



    @classmethod
    @doc_inject()
    def from_pandas(cls,
            value,
            *,
            own_data: bool = False) -> 'Frame':
        '''Given a Pandas DataFrame, return a Frame.

        Args:
            value: Pandas DataFrame.
            {own_data}

        Returns:
            :py:class:`static_frame.Frame`
        '''
        # create generator of contiguous typed data
        # calling .values will force type unification accross all columns
        def blocks():
            #import ipdb; ipdb.set_trace()
            pairs = value.dtypes.items()
            column_start, dtype_current = next(pairs)

            column_last = column_start
            for column, dtype in pairs:

                if dtype != dtype_current:
                    # use loc to select before calling .values
                    array = value.loc[NULL_SLICE,
                            slice(column_start, column_last)].values
                    if own_data:
                        array.flags.writeable = False
                    yield array
                    column_start = column
                    dtype_current = dtype

                column_last = column

            # always have left over
            array = value.loc[NULL_SLICE, slice(column_start, None)].values
            if own_data:
                array.flags.writeable = False
            yield array

        blocks = TypeBlocks.from_blocks(blocks())

        # avoid getting a Series if a column
        if 'name' not in value.columns and hasattr(value, 'name'):
            name = value.name
        else:
            name = None

        return cls(blocks,
                index=IndexBase.from_pandas(value.index),
                columns=IndexBase.from_pandas(value.columns,
                        is_static=cls._COLUMNS_CONSTRUCTOR.STATIC),
                name=name,
                own_data=True,
                own_index=True,
                own_columns=True
                )

    #---------------------------------------------------------------------------

    def __init__(self,
            data: FrameInitializer = FRAME_INITIALIZER_DEFAULT,
            *,
            index: tp.Union[IndexInitializer, IndexAutoFactoryType] = None,
            columns: tp.Union[IndexInitializer, IndexAutoFactoryType] = None,
            name: tp.Hashable = None,
            index_constructor: IndexConstructor = None,
            columns_constructor: IndexConstructor = None,
            own_data: bool = False,
            own_index: bool = False,
            own_columns: bool = False
            ) -> None:
        # doc string at class def

        self._name = name if name is None else name_filter(name)

        # we can determine if columns or index are empty only if they are not iterators; those cases will have to use a deferred evaluation
        columns_empty = columns is None or columns is IndexAutoFactory or (
                hasattr(columns, '__len__') and len(columns) == 0)

        index_empty = index is None or index is IndexAutoFactory or (
                hasattr(index, '__len__') and len(index) == 0)

        #-----------------------------------------------------------------------
        # blocks assignment

        blocks_constructor = None

        if isinstance(data, TypeBlocks):
            if own_data:
                self._blocks = data
            else:
                # assume we need to create a new TB instance; this will not copy underlying arrays as all blocks are immutable
                self._blocks = TypeBlocks.from_blocks(data._blocks)

        elif isinstance(data, np.ndarray):
            if own_data:
                data.flags.writeable = False
            # from_blocks will apply immutable filter
            self._blocks = TypeBlocks.from_blocks(data)

        elif isinstance(data, dict):
            raise ErrorInitFrame('use Frame.from_dict to create a Frame from a mapping.')

        elif data is FRAME_INITIALIZER_DEFAULT and (columns_empty or index_empty):
            # NOTE: this will not catch all cases where index or columns is empty, as they might be iterators; those cases will be handled below.

            def blocks_constructor(shape): #pylint: disable=E0102
                self._blocks = TypeBlocks.from_zero_size_shape(shape)

        elif not hasattr(data, '__len__') or isinstance(data, str):
            # and data is a single element to scale to size of index and columns; must defer until after index realization; or, data is FRAME_INITIALIZER_DEFAULT, and index or columns is an iterator, and size as not yet been evaluated

            def blocks_constructor(shape): #pylint: disable=E0102
                if shape[0] > 0 and shape[1] > 0 and data is FRAME_INITIALIZER_DEFAULT:
                    # if fillable and we still have default initializer, this is a problem
                    raise RuntimeError('must supply a non-default value for Frame construction from a single element or array constructor input')

                a = np.full(shape, data)
                a.flags.writeable = False
                self._blocks = TypeBlocks.from_blocks(a)

        else:
            # assume that the argument is castable into an array using default dtype discovery, and can build a TypeBlock that is compatible with this Frame. The array cas be 1D (to produce one column) or 2D; greater dimensionality will raise exception.
            a = np.array(data)
            a.flags.writeable = False
            self._blocks = TypeBlocks.from_blocks(a)

        # counts can be zero (not None) if _block was created but is empty
        row_count, col_count = (self._blocks._shape
                if not blocks_constructor else (None, None))

        #-----------------------------------------------------------------------
        # columns assignment

        if own_columns:
            self._columns = columns
            col_count = len(self._columns)
        elif columns_empty:
            col_count = 0 if col_count is None else col_count
            self._columns = IndexAutoFactory.from_optional_constructor(
                    col_count,
                    default_constructor=self._COLUMNS_CONSTRUCTOR,
                    explicit_constructor=columns_constructor
                    )
        else:
            self._columns = index_from_optional_constructor(columns,
                    default_constructor=self._COLUMNS_CONSTRUCTOR,
                    explicit_constructor=columns_constructor
                    )
            col_count = len(self._columns)

        # check after creation, as we cannot determine from the constructor (it might be a method on a class)
        if self._COLUMNS_CONSTRUCTOR.STATIC != self._columns.STATIC:
            raise ErrorInitFrame(f'supplied column constructor does not match required static attribute: {self._COLUMNS_CONSTRUCTOR.STATIC}')
        #-----------------------------------------------------------------------
        # index assignment

        if own_index:
            self._index = index
            row_count = len(self._index)
        elif index_empty:
            row_count = 0 if row_count is None else row_count
            self._index = IndexAutoFactory.from_optional_constructor(
                    row_count,
                    default_constructor=Index,
                    explicit_constructor=index_constructor
                    )
        else:
            self._index = index_from_optional_constructor(index,
                    default_constructor=Index,
                    explicit_constructor=index_constructor
                    )
            row_count = len(self._index)

        if not self._index.STATIC:
            raise ErrorInitFrame('non-static index cannot be assigned to Frame')

        #-----------------------------------------------------------------------
        # final evaluation

        # for indices that are created by generators, need to reevaluate if data has been given for an empty index or columns
        columns_empty = col_count == 0
        index_empty = row_count == 0

        if blocks_constructor:
            # if we have a blocks_constructor, we are determining final size from index and/or columns; we might have a legitamate single value for data, but it cannot be FRAME_INITIALIZER_DEFAULT
            if data is not FRAME_INITIALIZER_DEFAULT and (
                    columns_empty or index_empty):
                raise ErrorInitFrame('cannot supply a data argument to Frame constructor when index or columns is empty')
            # must update the row/col counts, sets self._blocks
            blocks_constructor((row_count, col_count))

        # final check of block/index coherence

        if self._blocks.ndim != self._NDIM:
            raise ErrorInitFrame('dimensionality of final values not supported')

        if self._blocks.shape[0] != row_count:
            # row count might be 0 for an empty DF
            raise ErrorInitFrame(
                f'Index has incorrect size (got {self._blocks.shape[0]}, expected {row_count})'
            )
        if self._blocks.shape[1] != col_count:
            raise ErrorInitFrame(
                f'Columns has incorrect size (got {self._blocks.shape[1]}, expected {col_count})'
            )

    #---------------------------------------------------------------------------
    # name interface

    @property
    def name(self) -> tp.Hashable:
        return self._name

    def rename(self, name: tp.Hashable) -> 'Frame':
        '''
        Return a new Frame with an updated name attribute.
        '''
        # copying blocks does not copy underlying data
        return self.__class__(self._blocks.copy(),
                index=self._index,
                columns=self._columns, # let constructor handle if GO
                name=name,
                own_data=True,
                own_index=True)

    #---------------------------------------------------------------------------
    # interfaces

    @property
    def loc(self) -> InterfaceGetItem:
        return InterfaceGetItem(self._extract_loc)

    @property
    def iloc(self) -> InterfaceGetItem:
        return InterfaceGetItem(self._extract_iloc)

    @property
    def drop(self) -> InterfaceSelection2D:
        return InterfaceSelection2D(
            func_iloc=self._drop_iloc,
            func_loc=self._drop_loc,
            func_getitem=self._drop_getitem)

    @property
    def mask(self) -> InterfaceSelection2D:
        return InterfaceSelection2D(
            func_iloc=self._extract_iloc_mask,
            func_loc=self._extract_loc_mask,
            func_getitem=self._extract_getitem_mask)

    @property
    def masked_array(self) -> InterfaceSelection2D:
        return InterfaceSelection2D(
            func_iloc=self._extract_iloc_masked_array,
            func_loc=self._extract_loc_masked_array,
            func_getitem=self._extract_getitem_masked_array)

    @property
    def assign(self) -> InterfaceSelection2D:
        return InterfaceSelection2D(
            func_iloc=self._extract_iloc_assign,
            func_loc=self._extract_loc_assign,
            func_getitem=self._extract_getitem_assign)

    @property
    def astype(self) -> InterfaceAsType:
        '''
        Retype one or more columns. Can be used as as function to retype the entire ``Frame``; alternatively, a ``__getitem__`` interface permits retyping selected columns.
        '''
        return InterfaceAsType(func_getitem=self._extract_getitem_astype)

    # generators
    @property
    def iter_array(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_array,
            function_items=self._axis_array_items,
            yield_type=IterNodeType.VALUES
            )

    @property
    def iter_array_items(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_array,
            function_items=self._axis_array_items,
            yield_type=IterNodeType.ITEMS
            )

    @property
    def iter_tuple(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_tuple,
            function_items=self._axis_tuple_items,
            yield_type=IterNodeType.VALUES
            )

    @property
    def iter_tuple_items(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_tuple,
            function_items=self._axis_tuple_items,
            yield_type=IterNodeType.ITEMS
            )

    @property
    def iter_series(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_series,
            function_items=self._axis_series_items,
            yield_type=IterNodeType.VALUES
            )

    @property
    def iter_series_items(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_series,
            function_items=self._axis_series_items,
            yield_type=IterNodeType.ITEMS
            )

    @property
    def iter_group(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_group_loc,
            function_items=self._axis_group_loc_items,
            yield_type=IterNodeType.VALUES
            )

    @property
    def iter_group_items(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_group_loc,
            function_items=self._axis_group_loc_items,
            yield_type=IterNodeType.ITEMS
            )

    @property
    def iter_group_index(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_group_index,
            function_items=self._axis_group_index_items,
            yield_type=IterNodeType.VALUES
            )

    @property
    def iter_group_index_items(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._axis_group_index,
            function_items=self._axis_group_index_items,
            yield_type=IterNodeType.ITEMS
            )


    @property
    def iter_element(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._iter_element_loc,
            function_items=self._iter_element_loc_items,
            yield_type=IterNodeType.VALUES,
            apply_type=IterNodeApplyType.FRAME_ELEMENTS
            )

    @property
    def iter_element_items(self) -> IterNode:
        return IterNode(
            container=self,
            function_values=self._iter_element_loc,
            function_items=self._iter_element_loc_items,
            yield_type=IterNodeType.ITEMS,
            apply_type=IterNodeApplyType.FRAME_ELEMENTS
            )

    #---------------------------------------------------------------------------
    # index manipulation

    def _reindex_other_like_iloc(self,
            value: tp.Union[Series, 'Frame'],
            iloc_key: GetItemKeyTypeCompound,
            fill_value=np.nan
            ) -> 'Frame':
        '''Given a value that is a Series or Frame, reindex it to the index components, drawn from this Frame, that are specified by the iloc_key.
        '''
        if isinstance(iloc_key, tuple):
            row_key, column_key = iloc_key
        else:
            row_key, column_key = iloc_key, None

        # within this frame, get Index objects by extracting based on passed-in iloc keys
        nm_row, nm_column = self._extract_axis_not_multi(row_key, column_key)
        v = None

        if nm_row and not nm_column:
            # only column is multi selection, reindex by column
            if isinstance(value, Series):
                v = value.reindex(self._columns._extract_iloc(column_key),
                        fill_value=fill_value)
        elif not nm_row and nm_column:
            # only row is multi selection, reindex by index
            if isinstance(value, Series):
                v = value.reindex(self._index._extract_iloc(row_key),
                        fill_value=fill_value)
        elif not nm_row and not nm_column:
            # both multi, must be a Frame
            if isinstance(value, Frame):
                target_column_index = self._columns._extract_iloc(column_key)
                target_row_index = self._index._extract_iloc(row_key)
                # this will use the default fillna type, which may or may not be what is wanted
                v = value.reindex(
                        index=target_row_index,
                        columns=target_column_index,
                        fill_value=fill_value)
        if v is None:
            raise Exception(('cannot assign '
                    + value.__class__.__name__
                    + ' with key configuration'), (nm_row, nm_column))
        return v

    @doc_inject(selector='reindex', class_name='Frame')
    def reindex(self,
            index: tp.Optional[IndexInitializer] = None,
            columns: tp.Optional[IndexInitializer] = None,
            fill_value=np.nan,
            own_index: bool = False,
            own_columns: bool = False
            ) -> 'Frame':
        '''
        {doc}

        Args:
            index: {index_initializer}
            columns: {index_initializer}
            {fill_value}
            {own_index}
            {own_columns}
        '''
        if index is None and columns is None:
            raise Exception('must specify one of index or columns')

        if index is not None:
            if isinstance(index, IndexBase):
                if not own_index:
                    # always use the Index constructor for safe reuse when poss[ible
                    if not index.STATIC:
                        index = index._IMMUTABLE_CONSTRUCTOR(index)
                    else:
                        index = index.__class__(index)
            else: # create the Index if not already an index, assume 1D
                index = Index(index)
            index_ic = IndexCorrespondence.from_correspondence(self._index, index)
            own_index_frame = True
        else:
            index = self._index
            index_ic = None
            # cannot own self._index, need a new index on Frame construction
            own_index_frame = False

        if columns is not None:
            if isinstance(columns, IndexBase):
                # always use the Index constructor for safe reuse when possible
                if not own_columns:
                    if columns.STATIC != self._COLUMNS_CONSTRUCTOR.STATIC:
                        columns_constructor = columns._IMMUTABLE_CONSTRUCTOR
                    else:
                        columns_constructor = columns.__class__
                    columns = columns_constructor(columns)
            else: # create the Index if not already an columns, assume 1D
                columns = self._COLUMNS_CONSTRUCTOR(columns)
            columns_ic = IndexCorrespondence.from_correspondence(self._columns, columns)
            own_columns_frame = True
        else:
            columns = self._columns
            columns_ic = None
            # if static, can own
            own_columns_frame = self._COLUMNS_CONSTRUCTOR.STATIC

        return self.__class__(
                TypeBlocks.from_blocks(
                        self._blocks.resize_blocks(
                                index_ic=index_ic,
                                columns_ic=columns_ic,
                                fill_value=fill_value),
                        shape_reference=(len(index), len(columns))
                        ),
                index=index,
                columns=columns,
                name=self._name,
                own_data=True,
                own_index=own_index_frame,
                own_columns=own_columns_frame
                )

    @doc_inject(selector='relabel', class_name='Frame')
    def relabel(self,
            index: tp.Optional[RelabelInput] = None,
            columns: tp.Optional[RelabelInput] = None
            ) -> 'Frame':
        '''
        {doc}

        Args:
            index: {relabel_input}
            columns: {relabel_input}
        '''
        # create new index objects in both cases so as to call with own*

        own_index = False
        if index is IndexAutoFactory:
            index = None
        elif is_callable_or_mapping(index):
            index = self._index.relabel(index)
            own_index = True
        elif index is None:
            index = self._index
        else: # assume index IndexInitializer
            index = index

        own_columns = False
        if columns is IndexAutoFactory:
            columns = None
        elif is_callable_or_mapping(columns):
            columns = self._columns.relabel(columns)
            own_columns = True
        elif columns is None:
            columns = self._columns
        else: # assume IndexInitializer
            columns = columns

        return self.__class__(
                self._blocks.copy(), # does not copy arrays
                index=index,
                columns=columns,
                name=self._name,
                own_data=True,
                own_index=own_index,
                own_columns=own_columns)

    @doc_inject(selector='relabel_flat', class_name='Frame')
    def relabel_flat(self,
            index: bool = False,
            columns: bool = False) -> 'Frame':
        '''
        {doc}

        Args:
            index: Boolean to flag flatening on the index.
            columns: Boolean to flag flatening on the columns.
        '''

        index = self._index.flat() if index else self._index.copy()
        columns = self._columns.flat() if columns else self._columns.copy()

        return self.__class__(
                self._blocks.copy(), # does not copy arrays
                index=index,
                columns=columns,
                name=self._name,
                own_data=True,
                own_index=True,
                own_columns=True)

    @doc_inject(selector='relabel_add_level', class_name='Frame')
    def relabel_add_level(self,
            index: tp.Hashable = None,
            columns: tp.Hashable = None
            ) -> 'Frame':
        '''
        {doc}

        Args:
            index: {level}
            columns: {level}
        '''

        index = self._index.add_level(index) if index else self._index.copy()
        columns = self._columns.add_level(columns) if columns else self._columns.copy()

        return self.__class__(
                self._blocks.copy(), # does not copy arrays
                index=index,
                columns=columns,
                name=self._name,
                own_data=True,
                own_index=True,
                own_columns=True)

    @doc_inject(selector='relabel_drop_level', class_name='Frame')
    def relabel_drop_level(self,
            index: int = 0,
            columns: int = 0
            ) -> 'Frame':
        '''
        {doc}

        Args:
            index: {count} Default is zero.
            columns: {count} Default is zero.
        '''

        index = self._index.drop_level(index) if index else self._index.copy()
        columns = self._columns.drop_level(columns) if columns else self._columns.copy()

        return self.__class__(
                self._blocks.copy(), # does not copy arrays
                index=index,
                columns=columns,
                name=self._name,
                own_data=True,
                own_index=True,
                own_columns=True)


    #---------------------------------------------------------------------------
    # na handling

    def isna(self) -> 'Frame':
        '''
        Return a same-indexed, Boolean Frame indicating True which values are NaN or None.
        '''
        # always return a Frame, even if this is a FrameGO
        return Frame(self._blocks.isna(),
                index=self._index,
                columns=self._columns,
                own_data=True)


    def notna(self) -> 'Frame':
        '''
        Return a same-indexed, Boolean Frame indicating True which values are not NaN or None.
        '''
        # always return a Frame, even if this is a FrameGO
        return Frame(self._blocks.notna(),
                index=self._index,
                columns=self._columns,
                own_data=True)

    def dropna(self,
            axis: int = 0,
            condition: tp.Callable[[np.ndarray], bool] = np.all) -> 'Frame':
        '''
        Return a new Frame after removing rows (axis 0) or columns (axis 1) where condition is True, where condition is an NumPy ufunc that process the Boolean array returned by isna().
        '''
        # returns Boolean areas that define axis to keep
        row_key, column_key = self._blocks.dropna_to_keep_locations(
                axis=axis,
                condition=condition)

        # NOTE: if not values to drop and this is a Frame (not a FrameGO) we can return self as it is immutable
        if self.__class__ is Frame:
            if (row_key is not None and column_key is not None
                    and row_key.all() and column_key.all()):
                return self
        return self._extract(row_key, column_key)

    @doc_inject(selector='fillna')
    def fillna(self, value: tp.Any) -> 'Frame':
        '''Return a new ``Frame`` after replacing null (NaN or None) with the supplied value.

        Args:
            {value}
        '''
        return self.__class__(self._blocks.fillna(value),
                index=self._index,
                columns=self._columns,
                name=self._name,
                own_data=True)

    @doc_inject(selector='fillna')
    def fillna_leading(self,
            value: tp.Any,
            *,
            axis: int = 0) -> 'Frame':
        '''
        Return a new ``Frame`` after filling leading (and only leading) null (NaN or None) with the supplied value.

        Args:
            {value}
            {axis}
        '''
        return self.__class__(self._blocks.fillna_leading(value, axis=axis),
                index=self._index,
                columns=self._columns,
                name=self._name,
                own_data=True)

    @doc_inject(selector='fillna')
    def fillna_trailing(self,
            value: tp.Any,
            *,
            axis: int = 0) -> 'Frame':
        '''
        Return a new ``Frame`` after filling trailing (and only trailing) null (NaN or None) with the supplied value.

        Args:
            {value}
            {axis}
        '''
        return self.__class__(self._blocks.fillna_trailing(value, axis=axis),
                index=self._index,
                columns=self._columns,
                name=self._name,
                own_data=True)

    @doc_inject(selector='fillna')
    def fillna_forward(self,
            limit: int = 0,
            *,
            axis: int = 0) -> 'Frame':
        '''
        Return a new ``Frame`` after filling forward null (NaN or None) with the supplied value.

        Args:
            {limit}
            {axis}
        '''
        return self.__class__(self._blocks.fillna_forward(limit=limit, axis=axis),
                index=self._index,
                columns=self._columns,
                name=self._name,
                own_data=True)

    @doc_inject(selector='fillna')
    def fillna_backward(self,
            limit: int = 0,
            *,
            axis: int = 0) -> 'Frame':
        '''
        Return a new ``Frame`` after filling backward null (NaN or None) with the supplied value.

        Args:
            {limit}
            {axis}
        '''
        return self.__class__(self._blocks.fillna_backward(limit=limit, axis=axis),
                index=self._index,
                columns=self._columns,
                name=self._name,
                own_data=True)

    #---------------------------------------------------------------------------

    def __len__(self) -> int:
        '''Length of rows in values.
        '''
        return self._blocks._shape[0]

    def display(self,
            config: tp.Optional[DisplayConfig] = None
            ) -> Display:
        config = config or DisplayActive.get()

        # create an empty display, then populate with index
        d = Display([[]],
                config=config,
                outermost=True,
                index_depth=self._index.depth,
                columns_depth=self._columns.depth + 2)

        display_index = self._index.display(config=config)
        d.extend_display(display_index)

        if self._blocks._shape[1] > config.display_columns:
            # columns as they will look after application of truncation and insertion of ellipsis
            # get target column count in the absence of meta data, subtracting 2
            data_half_count = Display.truncate_half_count(
                    config.display_columns - Display.DATA_MARGINS)

            column_gen = partial(_gen_skip_middle,
                    forward_iter=partial(self._blocks.axis_values, axis=0),
                    forward_count=data_half_count,
                    reverse_iter=partial(self._blocks.axis_values, axis=0, reverse=True),
                    reverse_count=data_half_count,
                    center_sentinel=Display.ELLIPSIS_CENTER_SENTINEL
                    )
        else:
            column_gen = partial(self._blocks.axis_values, axis=0)

        for column in column_gen():
            if column is Display.ELLIPSIS_CENTER_SENTINEL:
                d.extend_ellipsis()
            else:
                d.extend_iterable(column, header='')

        config_transpose = config.to_transpose()
        display_cls = Display.from_values((),
                header=DisplayHeader(self.__class__, self._name),
                config=config_transpose)

        # need to apply the column config such that it truncates it based on the the max columns, not the max rows
        display_columns = self._columns.display(
                config=config_transpose)

        # add spacers for a wide index
        for _ in range(self._index.depth - 1):
            # will need a width equal to the column depth
            row = [Display.to_cell('', config=config)
                    for _ in range(self._columns.depth)]
            spacer = Display([row])
            display_columns.insert_displays(spacer,
                    insert_index=1) # after the first, the name

        if self._columns.depth > 1:
            display_columns_horizontal = display_columns.transform()
        else: # can just flatten a single column into one row
            display_columns_horizontal = display_columns.flatten()

        d.insert_displays(
                display_cls.flatten(),
                display_columns_horizontal,
                )
        return d

    def _repr_html_(self):
        '''
        Provide HTML representation for Jupyter Notebooks.
        '''
        # modify the active display to be fore HTML
        config = DisplayActive.get(
                display_format=DisplayFormats.HTML_TABLE,
                type_show=False
                )
        return repr(self.display(config))

    #---------------------------------------------------------------------------
    # accessors

    @property
    def values(self) -> np.ndarray:
        '''A 2D array of values. Note: type coercion might be necessary.
        '''
        return self._blocks.values

    @property
    def index(self) -> Index:
        '''The ``IndexBase`` instance assigned for row labels.
        '''
        return self._index

    @property
    def columns(self) -> Index:
        '''The ``IndexBase`` instance assigned for column labels.
        '''
        return self._columns

    #---------------------------------------------------------------------------
    # common attributes from the numpy array

    @property
    def dtypes(self) -> Series:
        '''
        Return a Series of dytpes for each realizable column.

        Returns:
            :py:class:`static_frame.Series`
        '''
        return Series(self._blocks.dtypes,
                index=immutable_index_filter(self._columns),
                name=self._name
                )

    @property
    @doc_inject()
    def mloc(self) -> np.ndarray:
        '''{doc_array}
        '''
        return self._blocks.mloc

    #---------------------------------------------------------------------------

    @property
    def shape(self) -> tp.Tuple[int, int]:
        '''
        Return a tuple describing the shape of the underlying NumPy array.

        Returns:
            :py:class:`tp.Tuple[int]`
        '''
        return self._blocks._shape

    @property
    def ndim(self) -> int:
        '''
        Return the number of dimensions, which for a `Frame` is always 2.

        Returns:
            :py:class:`int`
        '''
        return self._NDIM

    @property
    def size(self) -> int:
        '''
        Return the size of the underlying NumPy array.

        Returns:
            :py:class:`int`
        '''

        return self._blocks.size

    @property
    def nbytes(self) -> int:
        '''
        Return the total bytes of the underlying NumPy array.

        Returns:
            :py:class:`int`
        '''
        return self._blocks.nbytes

    #---------------------------------------------------------------------------
    @staticmethod
    def _extract_axis_not_multi(row_key, column_key) -> tp.Tuple[bool, bool]:
        '''
        If either row or column is given with a non-multiple type of selection (a single scalar), reduce dimensionality.
        '''
        row_nm = False
        column_nm = False
        if row_key is not None and not isinstance(row_key, KEY_MULTIPLE_TYPES):
            row_nm = True # axis 0
        if column_key is not None and not isinstance(column_key, KEY_MULTIPLE_TYPES):
            column_nm = True # axis 1
        return row_nm, column_nm


    def _extract(self,
            row_key: GetItemKeyType = None,
            column_key: GetItemKeyType = None) -> tp.Union['Frame', Series]:
        '''
        Extract based on iloc selection (indices have already mapped)
        '''
        blocks = self._blocks._extract(row_key=row_key, column_key=column_key)

        if not isinstance(blocks, TypeBlocks):
            return blocks # reduced to an element

        own_index = True # the extracted Frame can always own this index
        row_key_is_slice = isinstance(row_key, slice)
        if row_key is None or (row_key_is_slice and row_key == NULL_SLICE):
            index = self._index
        else:
            index = self._index._extract_iloc(row_key)
            if not row_key_is_slice:
                name_row = self._index.values[row_key]
                if self._index.depth > 1:
                    name_row = tuple(name_row)

        # can only own columns if _COLUMNS_CONSTRUCTOR is static
        column_key_is_slice = isinstance(column_key, slice)
        if column_key is None or (column_key_is_slice and column_key == NULL_SLICE):
            columns = self._columns
            own_columns = self._COLUMNS_CONSTRUCTOR.STATIC
        else:
            columns = self._columns._extract_iloc(column_key)
            own_columns = True
            if not column_key_is_slice:
                name_column = self._columns.values[column_key]
                if self._columns.depth > 1:
                    name_column = tuple(name_column)

        axis_nm = self._extract_axis_not_multi(row_key, column_key)

        if blocks._shape == (1, 1):
            # if TypeBlocks did not return an element, need to determine which axis to use for Series index
            if axis_nm[0]: # if row not multi
                return Series(blocks.values[0],
                        index=immutable_index_filter(columns),
                        name=name_row)
            elif axis_nm[1]:
                return Series(blocks.values[0],
                        index=index,
                        name=name_column)
            # if both are multi, we return a Frame
        elif blocks._shape[0] == 1: # if one row
            if axis_nm[0]: # if row key not multi
                # best to use blocks.values, as will need to consolidate dtypes; will always return a 2D array
                return Series(blocks.values[0],
                        index=immutable_index_filter(columns),
                        name=name_row)
        elif blocks._shape[1] == 1: # if one column
            if axis_nm[1]: # if column key is not multi
                return Series(
                        column_1d_filter(blocks._blocks[0]),
                        index=index,
                        name=name_column)

        return self.__class__(blocks,
                index=index,
                columns=columns,
                name=self._name,
                own_data=True, # always get new TypeBlock instance above
                own_index=own_index,
                own_columns=own_columns
                )


    def _extract_iloc(self, key: GetItemKeyTypeCompound) -> 'Frame':
        '''
        Give a compound key, return a new Frame. This method simply handles the variabiliyt of single or compound selectors.
        '''
        if isinstance(key, tuple):
            return self._extract(*key)
        return self._extract(row_key=key)

    def _compound_loc_to_iloc(self,
            key: GetItemKeyTypeCompound) -> tp.Tuple[GetItemKeyType, GetItemKeyType]:
        '''
        Given a compound iloc key, return a tuple of row, column keys. Assumes the first argument is always a row extractor.
        '''
        if isinstance(key, tuple):
            loc_row_key, loc_column_key = key
            iloc_column_key = self._columns.loc_to_iloc(loc_column_key)
        else:
            loc_row_key = key
            iloc_column_key = None

        iloc_row_key = self._index.loc_to_iloc(loc_row_key)
        return iloc_row_key, iloc_column_key

    def _compound_loc_to_getitem_iloc(self,
            key: GetItemKeyTypeCompound) -> tp.Tuple[GetItemKeyType, GetItemKeyType]:
        '''Handle a potentially compound key in the style of __getitem__. This will raise an appropriate exception if a two argument loc-style call is attempted.
        '''
        if isinstance(key, tuple):
            raise KeyError('__getitem__ does not support multiple indexers')
        iloc_column_key = self._columns.loc_to_iloc(key)
        return None, iloc_column_key

    def _extract_loc(self, key: GetItemKeyTypeCompound) -> 'Frame':
        iloc_row_key, iloc_column_key = self._compound_loc_to_iloc(key)
        return self._extract(row_key=iloc_row_key,
                column_key=iloc_column_key)

    @doc_inject(selector='selector')
    def __getitem__(self, key: GetItemKeyType):
        '''Selector of columns by label.

        Args:
            key: {key_loc}
        '''
        return self._extract(*self._compound_loc_to_getitem_iloc(key))

    #---------------------------------------------------------------------------

    def _drop_iloc(self, key: GetItemKeyTypeCompound) -> 'Frame':
        '''
        Args:
            key: If a Boolean Series was passed, it has been converted to Boolean NumPy array already in loc to iloc.
        '''

        blocks = self._blocks.drop(key)

        if isinstance(key, tuple):
            iloc_row_key, iloc_column_key = key

            index = self._index._drop_iloc(iloc_row_key)
            own_index = True

            columns = self._columns._drop_iloc(iloc_column_key)
            own_columns = True
        else:
            iloc_row_key = key # no column selection

            index = self._index._drop_iloc(iloc_row_key)
            own_index = True

            columns = self._columns
            own_columns = False

        return self.__class__(blocks,
                columns=columns,
                index=index,
                name=self._name,
                own_data=True,
                own_columns=own_columns,
                own_index=own_index
                )

    def _drop_loc(self, key: GetItemKeyTypeCompound) -> 'Frame':
        key = self._compound_loc_to_iloc(key)
        return self._drop_iloc(key=key)

    def _drop_getitem(self, key: GetItemKeyTypeCompound) -> 'Frame':
        key = self._compound_loc_to_getitem_iloc(key)
        return self._drop_iloc(key=key)


    #---------------------------------------------------------------------------
    def _extract_iloc_mask(self, key: GetItemKeyTypeCompound) -> 'Frame':
        masked_blocks = self._blocks.extract_iloc_mask(key)
        return self.__class__(masked_blocks,
                columns=self._columns,
                index=self._index,
                own_data=True)

    def _extract_loc_mask(self, key: GetItemKeyTypeCompound) -> 'Frame':
        key = self._compound_loc_to_iloc(key)
        return self._extract_iloc_mask(key=key)

    def _extract_getitem_mask(self, key: GetItemKeyTypeCompound) -> 'Frame':
        key = self._compound_loc_to_getitem_iloc(key)
        return self._extract_iloc_mask(key=key)

    #---------------------------------------------------------------------------
    def _extract_iloc_masked_array(self, key: GetItemKeyTypeCompound) -> MaskedArray:
        masked_blocks = self._blocks.extract_iloc_mask(key)
        return MaskedArray(data=self.values, mask=masked_blocks.values)

    def _extract_loc_masked_array(self, key: GetItemKeyTypeCompound) -> MaskedArray:
        key = self._compound_loc_to_iloc(key)
        return self._extract_iloc_masked_array(key=key)

    def _extract_getitem_masked_array(self, key: GetItemKeyTypeCompound) -> 'Frame':
        key = self._compound_loc_to_getitem_iloc(key)
        return self._extract_iloc_masked_array(key=key)

    #---------------------------------------------------------------------------
    def _extract_iloc_assign(self, key: GetItemKeyTypeCompound) -> 'FrameAssign':
        return FrameAssign(self, iloc_key=key)

    def _extract_loc_assign(self, key: GetItemKeyTypeCompound) -> 'FrameAssign':
        # extract if tuple, then pack back again
        key = self._compound_loc_to_iloc(key)
        return self._extract_iloc_assign(key=key)

    def _extract_getitem_assign(self, key: GetItemKeyTypeCompound) -> 'FrameAssign':
        # extract if tuple, then pack back again
        key = self._compound_loc_to_getitem_iloc(key)
        return self._extract_iloc_assign(key=key)


    #---------------------------------------------------------------------------

    def _extract_getitem_astype(self, key: GetItemKeyType) -> 'FrameAsType':
        # extract if tuple, then pack back again
        _, key = self._compound_loc_to_getitem_iloc(key)
        return FrameAsType(self, column_key=key)



    #---------------------------------------------------------------------------
    # dictionary-like interface

    def keys(self):
        '''Iterator of column labels.
        '''
        return self._columns

    def __iter__(self):
        '''
        Iterator of column labels, same as :py:meth:`Frame.keys`.
        '''
        return self._columns.__iter__()

    def __contains__(self, value) -> bool:
        '''
        Inclusion of value in column labels.
        '''
        return self._columns.__contains__(value)

    def items(self) -> tp.Generator[tp.Tuple[tp.Any, Series], None, None]:
        '''Iterator of pairs of column label and corresponding column :py:class:`Series`.
        '''
        return zip(self._columns.values,
                (Series(v, index=self._index) for v in self._blocks.axis_values(0)))

    def get(self, key, default=None):
        '''
        Return the value found at the columns key, else the default if the key is not found. This method is implemented to complete the dictionary-like interface.
        '''
        if key not in self._columns:
            return default
        return self.__getitem__(key)


    #---------------------------------------------------------------------------
    # operator functions


    def _ufunc_unary_operator(self, operator: tp.Callable) -> 'Frame':
        # call the unary operator on _blocks
        return self.__class__(
                self._blocks._ufunc_unary_operator(operator=operator),
                index=self._index,
                columns=self._columns)

    def _ufunc_binary_operator(self, *,
            operator,
            other
            ) -> 'Frame':

        if operator.__name__ == 'matmul':
            return matmul(self, other)
        elif operator.__name__ == 'rmatmul':
            return matmul(other, self)

        if isinstance(other, Frame):
            # reindex both dimensions to union indices
            columns = self._columns.union(other._columns)
            index = self._index.union(other._index)
            self_tb = self.reindex(columns=columns, index=index)._blocks
            other_tb = other.reindex(columns=columns, index=index)._blocks
            return self.__class__(self_tb._ufunc_binary_operator(
                    operator=operator, other=other_tb),
                    index=index,
                    columns=columns,
                    own_data=True
                    )
        elif isinstance(other, Series):
            columns = self._columns.union(other._index)
            self_tb = self.reindex(columns=columns)._blocks
            other_array = other.reindex(columns).values
            return self.__class__(self_tb._ufunc_binary_operator(
                    operator=operator, other=other_array),
                    index=self._index,
                    columns=columns,
                    own_data=True
                    )
        # handle single values and lists that can be converted to appropriate arrays
        if not isinstance(other, np.ndarray) and hasattr(other, '__iter__'):
            other = np.array(other)

        # assume we will keep dimensionality
        return self.__class__(self._blocks._ufunc_binary_operator(
                operator=operator, other=other),
                index=self._index,
                columns=self._columns,
                own_data=True
                )

    #---------------------------------------------------------------------------
    # axis functions

    def _ufunc_axis_skipna(self, *,
            axis: int,
            skipna: bool,
            ufunc: UFunc,
            ufunc_skipna: UFunc,
            composable: bool,
            dtype) -> 'Series':
        # axis 0 processes ros, deliveres column index
        # axis 1 processes cols, delivers row index
        assert axis < 2

        post = self._blocks.ufunc_axis_skipna(
                skipna=skipna,
                axis=axis,
                ufunc=ufunc,
                ufunc_skipna=ufunc_skipna,
                composable=composable,
                dtype=dtype)

        # post has been made immutable so Series will own
        if axis == 0:
            return Series(
                    post,
                    index=immutable_index_filter(self._columns)
                    )
        return Series(post, index=self._index)

    def _ufunc_shape_skipna(self, *,
            axis,
            skipna,
            ufunc,
            ufunc_skipna,
            composable: bool,
            dtype) -> 'Frame':
        # axis 0 processes ros, deliveres column index
        # axis 1 processes cols, delivers row index
        assert axis < 2

        # assumed not composable for axis 1, full-shape processing requires processing contiguous values
        v = self.values
        if skipna:
            post = ufunc_skipna(v, axis=axis, dtype=dtype)
        else:
            post = ufunc(v, axis=axis, dtype=dtype)

        post.flags.writeable = False

        return self.__class__(
                TypeBlocks.from_blocks(post),
                index=self._index,
                columns=self._columns,
                own_data=True,
                own_index=True
                )

    #---------------------------------------------------------------------------
    # axis iterators
    # NOTE: if there is more than one argument, the axis argument needs to be key-word only

    def _axis_array(self, axis):
        '''Generator of arrays across an axis
        '''
        yield from self._blocks.axis_values(axis)

    def _axis_array_items(self, axis):
        keys = self._index if axis == 1 else self._columns
        yield from zip(keys, self._blocks.axis_values(axis))


    def _axis_tuple(self, axis):
        '''Generator of named tuples across an axis.

        Args:
            axis: 0 iterates over columns (index axis), 1 iterates over rows (column axis)
        '''
        if axis == 1:
            Tuple = namedtuple('Axis', self._columns.values)
        elif axis == 0:
            Tuple = namedtuple('Axis', self._index.values)
        else:
            raise NotImplementedError()

        for axis_values in self._blocks.axis_values(axis):
            yield Tuple(*axis_values)

    def _axis_tuple_items(self, axis):
        keys = self._index if axis == 1 else self._columns
        yield from zip(keys, self._axis_tuple(axis=axis))


    def _axis_series(self, axis):
        '''Generator of Series across an axis
        '''
        if axis == 1:
            index = self._columns.values
        elif axis == 0:
            index = self._index
        for axis_values in self._blocks.axis_values(axis):
            yield Series(axis_values, index=index)

    def _axis_series_items(self, axis):
        keys = self._index if axis == 1 else self._columns
        yield from zip(keys, self._axis_series(axis=axis))


    #---------------------------------------------------------------------------
    # grouping methods naturally return their "index" as the group element

    def _axis_group_iloc_items(self, key, *, axis):

        for group, selection, tb in self._blocks.group(axis=axis, key=key):
            if axis == 0:
                # axis 0 is a row iter, so need to slice index, keep columns
                yield group, self.__class__(tb,
                        index=self._index[selection],
                        columns=self._columns, # let constructor determine ownership
                        own_index=True,
                        own_data=True)
            elif axis == 1:
                # axis 1 is a column iterators, so need to slice columns, keep index
                yield group, self.__class__(tb,
                        index=self._index,
                        columns=self._columns[selection],
                        own_index=True,
                        own_columns=True,
                        own_data=True)
            else:
                raise NotImplementedError()

    def _axis_group_loc_items(self, key, *, axis=0):
        if axis == 0: # row iterator, selecting columns for group by
            key = self._columns.loc_to_iloc(key)
        elif axis == 1: # column iterator, selecting rows for group by
            key = self._index.loc_to_iloc(key)
        else:
            raise NotImplementedError()
        yield from self._axis_group_iloc_items(key=key, axis=axis)

    def _axis_group_loc(self, key, *, axis=0):
        yield from (x for _, x in self._axis_group_loc_items(key=key, axis=axis))



    def _axis_group_index_items(self,
            depth_level: DepthLevelSpecifier = 0,
            *,
            axis=0):

        if axis == 0: # maintain columns, group by index
            ref_index = self._index
        elif axis == 1: # maintain index, group by columns
            ref_index = self._columns
        else:
            raise NotImplementedError()

        values = ref_index.values_at_depth(depth_level)
        group_to_tuple = values.ndim > 1

        groups, locations = array_to_groups_and_locations(values)

        for idx, group in enumerate(groups):
            selection = locations == idx

            if axis == 0:
                # axis 0 is a row iter, so need to slice index, keep columns
                tb = self._blocks._extract(row_key=selection)
                yield group, self.__class__(tb,
                        index=self._index[selection],
                        columns=self._columns, # let constructor determine ownership
                        own_index=True,
                        own_data=True)

            elif axis == 1:
                # axis 1 is a column iterators, so need to slice columns, keep index
                tb = self._blocks._extract(column_key=selection)
                yield group, self.__class__(tb,
                        index=self._index,
                        columns=self._columns[selection],
                        own_index=True,
                        own_columns=True,
                        own_data=True)
            else:
                raise NotImplementedError()

    def _axis_group_index(self,
            depth_level: DepthLevelSpecifier = 0,
            *,
            axis=0):
        yield from (x for _, x in self._axis_group_index_items(
                depth_level=depth_level, axis=axis))


    #---------------------------------------------------------------------------

    def _iter_element_iloc_items(self):
        yield from self._blocks.element_items()

    def _iter_element_iloc(self):
        yield from (x for _, x in self._iter_element_iloc_items())

    def _iter_element_loc_items(self) -> tp.Iterator[
            tp.Tuple[tp.Tuple[tp.Hashable, tp.Hashable], tp.Any]]:
        '''
        Generator of pairs of (index, column), value.
        '''
        yield from (
                ((self._index[k[0]], self._columns[k[1]]), v)
                for k, v in self._blocks.element_items()
                )

    def _iter_element_loc(self):
        yield from (x for _, x in self._iter_element_loc_items())


    #---------------------------------------------------------------------------
    # transformations resulting in the same dimensionality

    def __reversed__(self) -> tp.Iterator[tp.Hashable]:
        '''
        Returns a reverse iterator on the frame's columns.
        '''
        return reversed(self._columns)

    def sort_index(self,
            ascending: bool = True,
            kind: str = DEFAULT_SORT_KIND) -> 'Frame':
        '''
        Return a new Frame ordered by the sorted Index.
        '''
        if self._index.depth > 1:
            v = self._index.values
            order = np.lexsort([v[:, i] for i in range(v.shape[1]-1, -1, -1)])
        else:
            # argsort lets us do the sort once and reuse the results
            order = np.argsort(self._index.values, kind=kind)

        if not ascending:
            order = order[::-1]

        index_values = self._index.values[order]
        index_values.flags.writeable = False

        blocks = self._blocks.iloc[order]
        return self.__class__(blocks,
                index=index_values,
                columns=self._columns,
                own_data=True,
                name=self._name,
                index_constructor=self._index.from_labels,
                )

    def sort_columns(self,
            ascending: bool = True,
            kind: str = DEFAULT_SORT_KIND) -> 'Frame':
        '''
        Return a new Frame ordered by the sorted Columns.
        '''
        if self._columns.depth > 1:
            v = self._columns.values
            order = np.lexsort([v[:, i] for i in range(v.shape[1]-1, -1, -1)])
        else:
            # argsort lets us do the sort once and reuse the results
            order = np.argsort(self._columns.values, kind=kind)

        if not ascending:
            order = order[::-1]

        columns_values = self._columns.values[order]
        columns_values.flags.writeable = False

        blocks = self._blocks[order]
        return self.__class__(blocks,
                index=self._index,
                columns=columns_values,
                own_data=True,
                name=self._name,
                columns_constructor=self._columns.from_labels
                )

    def sort_values(self,
            key: KeyOrKeys,
            ascending: bool = True,
            axis: int = 1,
            kind=DEFAULT_SORT_KIND) -> 'Frame':
        '''
        Return a new Frame ordered by the sorted values, where values is given by single column or iterable of columns.

        Args:
            key: a key or tuple of keys. Presently a list is not supported.
        '''
        # argsort lets us do the sort once and reuse the results
        if axis == 0: # get a column ordering based on one or more rows
            col_count = self._columns.__len__()
            if key in self._index:
                iloc_key = self._index.loc_to_iloc(key)
                sort_array = self._blocks._extract_array(row_key=iloc_key)
                order = np.argsort(sort_array, kind=kind)
            else: # assume an iterable of keys
                # order so that highest priority is last
                iloc_keys = (self._index.loc_to_iloc(key) for key in reversed(key))
                sort_array = [self._blocks._extract_array(row_key=key)
                        for key in iloc_keys]
                order = np.lexsort(sort_array)
        elif axis == 1: # get a row ordering based on one or more columns
            if key in self._columns:
                iloc_key = self._columns.loc_to_iloc(key)
                sort_array = self._blocks._extract_array(column_key=iloc_key)
                order = np.argsort(sort_array, kind=kind)
            else: # assume an iterable of keys
                # order so that highest priority is last
                iloc_keys = (self._columns.loc_to_iloc(key) for key in reversed(key))
                sort_array = [self._blocks._extract_array(column_key=key)
                        for key in iloc_keys]
                order = np.lexsort(sort_array)
        else:
            raise NotImplementedError()


        if not ascending:
            order = order[::-1]

        if axis == 0:
            column_values = self._columns.values[order]
            column_values.flags.writeable = False
            blocks = self._blocks[order]
            return self.__class__(blocks,
                    index=self._index,
                    columns=column_values,
                    own_data=True,
                    name=self._name,
                    columns_constructor=self._columns.from_labels
                    )

        index_values = self._index.values[order]
        index_values.flags.writeable = False
        blocks = self._blocks.iloc[order]
        return self.__class__(blocks,
                index=index_values,
                columns=self._columns,
                own_data=True,
                name=self._name,
                index_constructor=self._index.from_labels
                )

    def isin(self, other) -> 'Frame':
        '''
        Return a same-sized Boolean Frame that shows if the same-positioned element is in the iterable passed to the function.
        '''
        # cannot use assume_unique because do not know if values are unique
        v, _ = iterable_to_array(other)
        # NOTE: is it faster to do this at the block level and return blocks?
        array = np.isin(self.values, v)
        array.flags.writeable = False
        return self.__class__(array, columns=self._columns, index=self._index)

    @doc_inject(class_name='Frame')
    def clip(self,
            lower=None,
            upper=None,
            axis: tp.Optional[int] = None):
        '''{}

        Args:
            lower: value, ``Series``, ``Frame``
            upper: value, ``Series``, ``Frame``
            axis: required if ``lower`` or ``upper`` are given as a ``Series``.
        '''
        args = [lower, upper]
        for idx, arg in enumerate(args):
            bound = -np.inf if idx == 0 else np.inf
            if isinstance(arg, Series):
                if axis is None:
                    raise RuntimeError('cannot use a Series argument without specifying an axis')
                target = self._index if axis == 0 else self._columns
                values = arg.reindex(target).fillna(bound).values
                if axis == 0: # duplicate the same column over the width
                    args[idx] = np.vstack([values] * self.shape[1]).T
                else:
                    args[idx] = np.vstack([values] * self.shape[0])
            elif isinstance(arg, Frame):
                args[idx] = arg.reindex(
                        index=self._index,
                        columns=self._columns).fillna(bound).values
            elif hasattr(arg, '__iter__'):
                raise RuntimeError('only Series or Frame are supported as iterable lower/upper arguments')
            # assume single value otherwise, no change necessary

        array = np.clip(self.values, *args)
        array.flags.writeable = False
        return self.__class__(array,
                columns=self._columns,
                index=self._index)


    def transpose(self) -> 'Frame':
        '''Return a tansposed version of the ``Frame``.
        '''
        return self.__class__(self._blocks.transpose(),
                index=self._columns,
                columns=self._index,
                own_data=True,
                name=self.name)

    @property
    def T(self) -> 'Frame':
        '''Return a transposed version of the ``Frame``.
        '''
        return self.transpose()


    def duplicated(self,
            axis=0,
            exclude_first=False,
            exclude_last=False) -> 'Series':
        '''
        Return an axis-sized Boolean Series that shows True for all rows (axis 0) or columns (axis 1) duplicated.
        '''
        # TODO: might be able to do this witnout calling .values and passing in TypeBlocks, but TB needs to support roll
        duplicates = array_to_duplicated(self.values,
                axis=axis,
                exclude_first=exclude_first,
                exclude_last=exclude_last)
        duplicates.flags.writeable = False
        if axis == 0: # index is index
            return Series(duplicates, index=self._index)
        return Series(duplicates, index=self._columns)

    def drop_duplicated(self,
            axis=0,
            exclude_first: bool = False,
            exclude_last: bool = False
            ) -> 'Frame':
        '''
        Return a Frame with duplicated values removed.
        '''
        # NOTE: can avoid calling .vaalues with extensions to TypeBlocks
        duplicates = array_to_duplicated(self.values,
                axis=axis,
                exclude_first=exclude_first,
                exclude_last=exclude_last)

        if not duplicates.any():
            return self

        keep = ~duplicates
        if axis == 0: # return rows with index indexed
            return self.__class__(self.values[keep],
                    index=self._index[keep],
                    columns=self._columns)
        return self.__class__(self.values[:, keep],
                index=self._index,
                columns=self._columns[keep])

    def set_index(self,
            column: GetItemKeyType,
            *,
            drop: bool = False,
            index_constructor=Index) -> 'Frame':
        '''
        Return a new frame produced by setting the given column as the index, optionally removing that column from the new Frame.
        '''
        column_iloc = self._columns.loc_to_iloc(column)

        if drop:
            blocks = TypeBlocks.from_blocks(
                    self._blocks._drop_blocks(column_key=column_iloc))
            columns = self._columns._drop_iloc(column_iloc)
            own_data = True
            own_columns = True
        else:
            blocks = self._blocks
            columns = self._columns
            own_data = False
            own_columns = False

        index_values = self._blocks._extract_array(column_key=column_iloc)
        index = index_constructor(index_values, name=column)

        return self.__class__(blocks,
                columns=columns,
                index=index,
                own_data=own_data,
                own_columns=own_columns,
                own_index=True,
                name=self._name
                )

    def set_index_hierarchy(self,
            columns: GetItemKeyType,
            *,
            drop: bool = False,
            index_constructors: tp.Optional[IndexConstructors] = None
            ) -> 'Frame':
        '''
        Given an iterable of column labels, return a new ``Frame`` with those columns as an ``IndexHierarchy`` on the index.

        Args:
            columns: Iterable of column labels.
            drop: Boolean to determine if selected columns should be removed from the data.
            index_constructors: Optionally provide a sequence of ``Index`` constructors, of length equal to depth, to be used in converting columns Index components in the ``IndexHierarchy``.

        Returns:
            :py:class:`Frame`
        '''

        # columns cannot be a tuple
        if isinstance(columns, tuple):
            column_loc = list(columns)
            column_name = columns
        else:
            column_loc = columns
            column_name = None # could be a slice, must get post iloc conversion

        column_iloc = self._columns.loc_to_iloc(column_loc)

        if column_name is None:
            column_name = tuple(self._columns.values[column_iloc])

        if drop:
            blocks = TypeBlocks.from_blocks(
                    self._blocks._drop_blocks(column_key=column_iloc))
            columns = self._columns._drop_iloc(column_iloc)
            own_data = True
            own_columns = True
        else:
            blocks = self._blocks
            columns = self._columns
            own_data = False
            own_columns = False

        index_labels = self._blocks._extract_array(column_key=column_iloc)
        # index is always immutable
        index = IndexHierarchy.from_labels(index_labels,
                name=column_name,
                index_constructors=index_constructors
                )

        return self.__class__(blocks,
                columns=columns,
                index=index,
                own_data=own_data,
                own_columns=own_columns,
                own_index=True
                )

    def roll(self,
            index: int = 0,
            columns: int = 0,
            include_index: bool = False,
            include_columns: bool = False) -> 'Frame':
        '''
        Args:
            include_index: Determine if index is included in index-wise rotation.
            include_columns: Determine if column index is included in index-wise rotation.
        '''
        shift_index = index
        shift_column = columns

        blocks = TypeBlocks.from_blocks(
                self._blocks._shift_blocks(
                row_shift=shift_index,
                column_shift=shift_column,
                wrap=True
                ))

        if include_index:
            index = self._index.roll(shift_index)
            own_index = True
        else:
            index = self._index
            own_index = False

        if include_columns:
            columns = self._columns.roll(shift_column)
            own_columns = True
        else:
            columns = self._columns
            own_columns = False

        return self.__class__(blocks,
                columns=columns,
                index=index,
                name=self._name,
                own_data=True,
                own_columns=own_columns,
                own_index=own_index,
                )

    def shift(self,
            index: int = 0,
            columns: int = 0,
            fill_value=np.nan) -> 'Frame':

        shift_index = index
        shift_column = columns

        blocks = TypeBlocks.from_blocks(
                self._blocks._shift_blocks(
                row_shift=shift_index,
                column_shift=shift_column,
                wrap=False,
                fill_value=fill_value
                ))

        return self.__class__(blocks,
                columns=self._columns,
                index=self._index,
                name=self._name,
                own_data=True,
                )

    #---------------------------------------------------------------------------
    # transformations resulting in reduced dimensionality

    def head(self, count: int = 5) -> 'Frame':
        '''Return a Frame consisting only of the top rows as specified by ``count``.
        '''
        return self.iloc[:count]

    def tail(self, count: int = 5) -> 'Frame':
        '''Return a Frame consisting only of the bottom rows as specified by ``count``.
        '''
        return self.iloc[-count:]

    @doc_inject(selector='argminmax')
    def loc_min(self, *,
            skipna: bool = True,
            axis: int = 0
            ) -> Series:
        '''
        Return the labels corresponding to the minimum value found.

        Args:
            {skipna}
            {axis}
        '''
        # this operation is not composable for axis 1; cannot use _ufunc_axis_skipna interface as do not have out argument, and need to determine returned dtype in advance

        # if this has NaN we cannot get a loc
        post = argmin_2d(self.values, skipna=skipna, axis=axis)
        if post.dtype == DTYPE_FLOAT_DEFAULT:
            raise RuntimeError('cannot produce loc representation from NaNs')

        # post has been made immutable so Series will own
        if axis == 0:
            return Series(
                    self.index.values[post],
                    index=immutable_index_filter(self._columns)
                    )
        return Series(self.columns.values[post], index=self._index)

    @doc_inject(selector='argminmax')
    def iloc_min(self, *,
            skipna: bool = True,
            axis: int = 0
            ) -> Series:
        '''
        Return the integer indices corresponding to the minimum values found.

        Args:
            {skipna}
            {axis}
        '''
        # if this has NaN can continue
        post = argmin_2d(self.values, skipna=skipna, axis=axis)
        post.flags.writeable = False
        if axis == 0:
            return Series(post, index=immutable_index_filter(self._columns))
        return Series(post, index=self._index)

    @doc_inject(selector='argminmax')
    def loc_max(self, *,
            skipna: bool = True,
            axis: int = 0
            ) -> Series:
        '''
        Return the labels corresponding to the maximum values found.

        Args:
            {skipna}
            {axis}
        '''
        # if this has NaN we cannot get a loc
        post = argmax_2d(self.values, skipna=skipna, axis=axis)
        if post.dtype == DTYPE_FLOAT_DEFAULT:
            raise RuntimeError('cannot produce loc representation from NaNs')

        if axis == 0:
            return Series(
                    self.index.values[post],
                    index=immutable_index_filter(self._columns)
                    )
        return Series(self.columns.values[post], index=self._index)

    @doc_inject(selector='argminmax')
    def iloc_max(self, *,
            skipna: bool = True,
            axis: int = 0
            ) -> Series:
        '''
        Return the integer indices corresponding to the maximum values found.

        Args:
            {skipna}
            {axis}
        '''
        # if this has NaN can continue
        post = argmax_2d(self.values, skipna=skipna, axis=axis)
        post.flags.writeable = False
        if axis == 0:
            return Series(post, index=immutable_index_filter(self._columns))
        return Series(post, index=self._index)



    #---------------------------------------------------------------------------
    # utility function to numpy array

    def unique(self, axis: tp.Optional[int] = None) -> np.ndarray:
        '''
        Return a NumPy array of unqiue values. If the axis argument is provied, uniqueness is determined by columns or row.
        '''
        return ufunc_unique(self.values, axis=axis)

    #---------------------------------------------------------------------------
    # exporters

    def to_pairs(self, axis) -> tp.Iterable[
            tp.Tuple[tp.Hashable, tp.Iterable[tp.Tuple[tp.Hashable, tp.Any]]]]:
        '''
        Return a tuple of major axis key, minor axis key vlaue pairs, where major axis is determined by the axis argument.
        '''
        # TODO: find a common interfave on IndexHierarchy that cna give hashables
        if isinstance(self._index, IndexHierarchy):
            index_values = list(array2d_to_tuples(self._index.values))
        else:
            index_values = self._index.values

        if isinstance(self._columns, IndexHierarchy):
            columns_values = list(array2d_to_tuples(self._columns.values))
        else:
            columns_values = self._columns.values

        if axis == 1:
            major = index_values
            minor = columns_values
        elif axis == 0:
            major = columns_values
            minor = index_values
        else:
            raise NotImplementedError()

        return tuple(
                zip(major, (tuple(zip(minor, v))
                for v in self._blocks.axis_values(axis))))

    def to_pandas(self) -> 'pd.DataFrame':
        '''
        Return a Pandas DataFrame.
        '''
        import pandas
        df = pandas.DataFrame(self.values.copy(),
                index=self._index.to_pandas(),
                columns=self._columns.to_pandas(),
                )
        if 'name' not in df.columns and self._name is not None:
            df.name = self._name
        return df


    def to_xarray(self) -> 'Dataset':
        '''
        Return an xarray Dataset.

        In order to preserve columnar types, and following the precedent of Pandas, the :obj:`Frame`, with a 1D index, is translated as a Dataset of 1D arrays, where each DataArray is a 1D array. If the index is an :obj:`IndexHierarhcy`, each column is mapped into an ND array of shape equal to the unique values found at each depth of the index.
        '''
        import xarray

        columns = self.columns
        index = self.index

        if index.depth == 1:
            index_name = index.name if index.name else 'index'
            coords = {index_name: index.values}
        else:
            # NOTE: not checking the index name attr, as may not be tuple
            index_name = tuple(f'level_{x}' for x in range(index.depth))

            # index values are reduced to unique values for 2d presentation
            coords = {f'level_{d}': np.unique(index.values_at_depth(d))
                    for d in range(index.depth)}
            # create dictionary version
            coords_index = {k: Index(v) for k, v in coords.items()}

        # columns form the keys in data_vars dict
        if columns.depth == 1:
            columns_values = columns.values
            # needs to be called with axis argument
            columns_arrays = partial(self._blocks.axis_values, axis=0)
        else: # must be hashable
            columns_values = array2d_to_tuples(columns.values)

            def columns_arrays() -> tp.Iterator[np.ndarray]:
                for c in self.iter_series(axis=0):
                    # dtype must be able to accomodate a float NaN
                    resolved = resolve_dtype(c.dtype, DTYPE_FLOAT_DEFAULT)
                    # create multidimensional arsdfray of all axis for each
                    array = np.full(
                            shape=[len(coords[v]) for v in coords],
                            fill_value=np.nan,
                            dtype=resolved)

                    for index_labels, value in c.items():
                        # translate to index positions
                        insert_pos = [coords_index[k].loc_to_iloc(label)
                                for k, label in zip(coords, index_labels)]
                        # must convert to tuple to give position per dimension
                        array[tuple(insert_pos)] = value

                    yield array

        data_vars = {k: (index_name, v)
                for k, v in zip(columns_values, columns_arrays())}

        return xarray.Dataset(data_vars, coords=coords)

    def to_frame_go(self) -> 'FrameGO':
        '''
        Return a FrameGO view of this Frame. As underlying data is immutable, this is a no-copy operation.
        '''
        # copying blocks does not copy underlying data
        return FrameGO(
                self._blocks.copy(),
                index=self.index, # can reuse
                columns=self.columns,
                columns_constructor=self.columns._MUTABLE_CONSTRUCTOR,
                name=self._name,
                own_data=True,
                own_index=True,
                own_columns=False # need to make grow only
                )

    def to_csv(self,
            fp: PathSpecifierOrFileLike,
            *,
            delimiter: str = ',',
            include_index: bool = True,
            include_columns: bool = True,
            encoding: tp.Optional[str] = None,
            line_terminator: str = '\n',
            store_filter: tp.Optional[StoreFilter] = STORE_FILTER_DEFAULT
            ):
        '''
        Given a file path or file-like object, write the Frame as delimited text.

        Args:
            delimiter: character to be used for delimiterarating elements.
        '''
        # to_str = str

        if isinstance(fp, str):
            f = open(fp, 'w', encoding=encoding)
            is_file = True
        else:
            f = fp # assume an open file like
            is_file = False

        if include_index:
            index_values = self._index.values # get once for caching

        if store_filter:
            filter_func = store_filter.from_type_filter_element

        try:
            if include_columns:
                if include_index:
                    # if this is included should be controlled by a Boolean switch
                    if self._index.name is not None:
                        f.write(f'{self._index.name}{delimiter}')
                    else:
                        f.write(f'index{delimiter}')
                # iter directly over columns in case it is an IndexGO and needs to update cache
                # TODO: support IndexHierarchy
                if store_filter:
                    f.write(delimiter.join(f'{filter_func(x)}' for x in self._columns))
                else:
                    f.write(delimiter.join(f'{x}' for x in self._columns))
                f.write(line_terminator)

            col_idx_last = self._blocks._shape[1] - 1
            # avoid row creation to avoid joining types; avoide creating a list for each row
            row_current_idx = None
            for (row_idx, col_idx), element in self._iter_element_iloc_items():
                if row_idx != row_current_idx:
                    if row_current_idx is not None:
                        f.write(line_terminator)
                    if include_index:
                        # TODO: support IndexHierarchy
                        if store_filter:
                            f.write(f'{filter_func(index_values[row_idx])}{delimiter}')
                        else:
                            f.write(f'{index_values[row_idx]}{delimiter}')
                    row_current_idx = row_idx
                if store_filter:
                    f.write(f'{filter_func(element)}')
                else:
                    f.write(f'{element}')
                if col_idx != col_idx_last:
                    f.write(delimiter)
        except:
            raise
        finally:
            if is_file:
                f.close()
        if is_file:
            f.close()

    def to_tsv(self,
            fp: PathSpecifierOrFileLike,
            **kwargs):
        '''
        Given a file path or file-like object, write the Frame as tab-delimited text.
        '''
        return self.to_csv(fp=fp, delimiter='\t', **kwargs)


    def to_xlsx(self,
            fp: PathSpecifier, # not sure I can take a file like yet
            *,
            sheet_name: tp.Optional[str] = None,
            include_index: bool = True,
            include_columns: bool = True,
            merge_hierarchical_labels: bool = True
            ) -> None:
        '''
        Write the Frame as single-sheet XLSX file.
        '''
        from static_frame.core.store_xlsx import StoreXLSX

        st = StoreXLSX(fp)
        st.write(((sheet_name, self),),
                include_index=include_index,
                include_columns=include_columns,
                merge_hierarchical_labels=merge_hierarchical_labels
                )


    @doc_inject(class_name='Frame')
    def to_html(self,
            config: tp.Optional[DisplayConfig] = None
            ):
        '''
        {}
        '''
        # if a config is given, try to use all settings; if using active, hide types
        config = config or DisplayActive.get(type_show=False)
        config = config.to_display_config(
                display_format=DisplayFormats.HTML_TABLE,
                )
        return repr(self.display(config))

    @doc_inject(class_name='Frame')
    def to_html_datatables(self,
            fp: tp.Optional[PathSpecifierOrFileLike] = None,
            show: bool = True,
            config: tp.Optional[DisplayConfig] = None
            ) -> str:
        '''
        {}
        '''
        config = config or DisplayActive.get(type_show=False)
        config = config.to_display_config(
                display_format=DisplayFormats.HTML_DATATABLES,
                )
        content = repr(self.display(config))
        fp = write_optional_file(content=content, fp=fp)

        if show:
            import webbrowser
            webbrowser.open_new_tab(fp)
        return fp




class FrameGO(Frame):
    '''A two-dimensional, ordered, labelled collection, immutable with grow-only columns. Initialization arguments are the same as for :py:class:`Frame`.
    '''

    __slots__ = (
            '_blocks',
            '_columns',
            '_index',
            '_name'
            )

    _COLUMNS_CONSTRUCTOR = IndexGO


    def __setitem__(self,
            key: tp.Hashable,
            value: tp.Any,
            fill_value=np.nan
            ) -> None:
        '''For adding a single column, one column at a time.
        '''
        if key in self._columns:
            raise RuntimeError('key already defined in columns; use .assign to get new Frame')

        row_count = len(self._index)

        if isinstance(value, Series):
            # NOTE: performance test if it is faster to compare indices and not call reindex() if we can avoid it?
            # select only the values matching our index
            self._blocks.append(
                    value.reindex(
                    self.index, fill_value=fill_value).values)
        elif isinstance(value, np.ndarray): # is numpy array
            # this permits unaligned assignment as no index is used, possibly remove
            if value.ndim != 1 or len(value) != row_count:
                # block may have zero shape if created without columns
                raise RuntimeError('incorrectly sized, unindexed value')
            self._blocks.append(value)
        else:
            if not hasattr(value, '__iter__') or isinstance(value, str):
                value = np.full(row_count, value)
            else:
                value, _ = iterable_to_array(value)

            if value.ndim != 1 or len(value) != row_count:
                raise RuntimeError('incorrectly sized, unindexed value')

            value.flags.writeable = False
            self._blocks.append(value)

        # this might fail if key is a sequence
        self._columns.append(key)


    def extend_items(self,
            pairs: tp.Iterable[tp.Tuple[tp.Hashable, Series]],
            fill_value=np.nan):
        '''
        Given an iterable of pairs of column name, column value, extend this FrameGO.
        '''
        for k, v in pairs:
            self.__setitem__(k, v, fill_value)


    def extend(self,
            container: tp.Union['Frame', Series],
            fill_value=np.nan
            ):
        '''Extend this FrameGO (in-place) with another Frame's blocks or Series array; as blocks are immutable, this is a no-copy operation when indices align. If indices do not align, the passed-in Frame or Series will be reindexed (as happens when adding a column to a FrameGO).

        If a Series is passed in, the column name will be taken from the Series ``name`` attribute.

        This method differs from FrameGO.extend_items() by permitting contiguous underlying blocks to be extended from another Frame into this Frame.
        '''

        if not len(container.index): # must be empty data, empty index container
            return

        # self's index will never change; we only take what aligns in the passed container
        if _requires_reindex(self._index, container._index):
            container = container.reindex(self._index, fill_value=fill_value)

        if isinstance(container, Frame):
            if not len(container.columns):
                return
            self._columns.extend(container.keys())
            self._blocks.extend(container._blocks)
        elif isinstance(container, Series):
            self._columns.append(container.name)
            self._blocks.append(container.values)
        else:
            raise NotImplementedError(
                    'no support for extending with %s' % type(container))

        if len(self._columns) != self._blocks._shape[1]:
            raise RuntimeError('malformed Frame was used in extension')


    #---------------------------------------------------------------------------
    def to_frame(self):
        '''
        Return Frame version of this Frame.
        '''
        # copying blocks does not copy underlying data
        return Frame(self._blocks.copy(),
                index=self.index,
                columns=self.columns.values,
                name=self._name,
                own_data=True,
                own_index=True,
                own_columns=False # need to make static only
                )


    def to_frame_go(self):
        '''
        Return a FrameGO version of this Frame.
        '''
        raise NotImplementedError('Already a FrameGO')


#-------------------------------------------------------------------------------
# utility delegates returned from selection routines and exposing the __call__ interface.

class FrameAssign:
    __slots__ = ('container', 'iloc_key',)

    def __init__(self,
            container: Frame,
            iloc_key: GetItemKeyTypeCompound
            ) -> None:
        # NOTE: the stored container reference here migth be best as weak reference
        self.container = container
        self.iloc_key = iloc_key

    def __call__(self, value, fill_value=np.nan) -> 'Frame':
        if isinstance(value, (Series, Frame)):
            value = self.container._reindex_other_like_iloc(value,
                    self.iloc_key,
                    fill_value=fill_value).values

        blocks = self.container._blocks.extract_iloc_assign(self.iloc_key, value)
        # can own the newly created block given by extract
        # pass Index objects unchanged, so as to let types be handled elsewhere
        return self.container.__class__(
                data=blocks,
                columns=self.container.columns,
                index=self.container.index,
                name=self.container._name,
                own_data=True)


class FrameAsType:
    '''
    The object returned from the getitem selector, exposing the functional (__call__) interface to pass in the dtype, as well as (optionally) whether blocks are consolidated.
    '''
    __slots__ = ('container', 'column_key',)

    def __init__(self,
            container: Frame,
            column_key: GetItemKeyType
            ) -> None:
        self.container = container
        self.column_key = column_key

    def __call__(self, dtype, consolidate_blocks: bool = True) -> 'Frame':

        blocks = self.container._blocks._astype_blocks(self.column_key, dtype)

        if consolidate_blocks:
            blocks = TypeBlocks.consolidate_blocks(blocks)

        blocks = TypeBlocks.from_blocks(blocks)

        return self.container.__class__(
                data=blocks,
                columns=self.container.columns,
                index=self.container.index,
                name=self.container._name,
                own_data=True)
