


The Performance Advantage of No-Copy DataFrame Operations
=================================================================


    As a significant performance optimization, NumPy arrays share memory among instances that are derived by reshaping, transposing, or slicing an array. By adding an immutable data model, StaticFrame makes full use of NumPy's memory sharing to offer no-copy DataFrame operations at significant performance advantage to Pandas.


A NumPy array is a Python object that stores data in a contiguous C-array buffer. The excellent performance of these arrays comes not only from this compact representation, but also from the ability of arrays to share "views" of that buffer among many arrays. NumPy makes frequent use of "no-copy" array operations, producing derived arrays without copying underling data buffers. By taking full advantage of NumPy's efficiency, the StaticFrame DataFrame library offers orders-of-magnitude better performance than Pandas for many common operations.


No-Copy Operations with NumPy Arrays
-------------------------------------

The phrase "no-copy" describes an operation on a container (here, an array or a DataFrame) where a new instance is created, but underlying data is referenced, not copied. While some new memory is allocated for the instance, the size is generally insignificant compared to a potentially very large amount of underlying data.

NumPy makes no-copy operations the primary way of working with arrays. When you slice a NumPy array, you get a new array that shares the data from which it was sliced. Slicing an array is a no-copy operation. Extraordinary performance is gained by not having to copy already-allocated contiguous buffers, but instead just storing offsets and strides into that data.

For example, the difference between slicing an array of 100,000 integers (~0.1 µs), and slicing and then copying the same array (~10 µs), is two orders of magnitude.

>>> data = np.arange(100_000)
>>> %timeit data[:50_000]
123 ns ± 0.565 ns per loop (mean ± std. dev. of 7 runs, 10000000 loops each)
>>> %timeit data[:50_000].copy()
13.1 µs ± 48.4 ns per loop (mean ± std. dev. of 7 runs, 100000 loops each)


We can illustrate how this works by examining two attributes of NumPy arrays. The ``flags`` attribute displays details of how the array's memory is being referenced. The ``base`` attribute, if set, provides a handle to the array that actually holds the buffer this array references.

In the example below, we create an array, take a slice, and look at the ``flags`` of the slice. We see that, for the slice, ``OWNDATA`` is ``False``, and that the ``base`` of the slice is the original array (they have the same object identifier).

>>> a1 = np.arange(12)
>>> a1
array([ 0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11])

>>> a2 = a1[:6]
>>> a2.flags
  C_CONTIGUOUS : True
  F_CONTIGUOUS : True
  OWNDATA : False
  WRITEABLE : True
  ALIGNED : True
  WRITEBACKIFCOPY : False
  UPDATEIFCOPY : False

>>> id(a1), id(a2.base)
(140506320732848, 140506320732848)


These derived arrays are "views" of the original array. Views can only be taken under certain conditions: re-shapping, transposing, or slicing.

For example, after reshaping the initial 1D array into a 2D array, ``OWNDATA`` is ``False``, showing that it still references the original array's data.

>>> a3 = a1.reshape(3,4)
>>> a3
array([[ 0,  1,  2,  3],
       [ 4,  5,  6,  7],
       [ 8,  9, 10, 11]])
>>> a3.flags
  C_CONTIGUOUS : True
  F_CONTIGUOUS : False
  OWNDATA : False
  WRITEABLE : True
  ALIGNED : True
  WRITEBACKIFCOPY : False
  UPDATEIFCOPY : False

>>> id(a3.base), id(a1)
(140506320732848, 140506320732848)


Both horizontal and vertical slices of this 2D array similarly result in arrays that simply reference the original array's data. Again, ``OWNDATA`` is ``False``, and the ``base`` of the slice is the original array.

>>> a4 = a3[:, 2]
>>> a4
array([ 2,  6, 10])

>>> a4.flags
  C_CONTIGUOUS : False
  F_CONTIGUOUS : False
  OWNDATA : False
  WRITEABLE : True
  ALIGNED : True
  WRITEBACKIFCOPY : False
  UPDATEIFCOPY : False

>>> id(a1), id(a4.base)
(140506320732848, 140506320732848)


While creating light-weight views of shared memory buffers offers significant performance advantages, there is a risk: mutating any one of those arrays will mutate all of them. As shown below, the assignment of -1 into our most-derived array is reflected in every associated array.

>>> a4[0] = -1
>>> a4
array([-1,  6, 10])
>>> a3
array([[ 0,  1, -1,  3],
       [ 4,  5,  6,  7],
       [ 8,  9, 10, 11]])
>>> a2
array([ 0,  1, -1,  3,  4,  5])
>>> a1
array([ 0,  1, -1,  3,  4,  5,  6,  7,  8,  9, 10, 11])


Side-effects like this should concern you. Passing around views of shared buffers to clients that can mutate those buffers can lead to serious flaws. There are two solutions to this problem.

One option is for the caller to make explicit "defensive" copies every time a new array is created. This removes the performance advantage of sharing views but ensures that mutating an array does not lead to unexpected side effects.

Another option, requiring no sacrifice in performance, is to make the array immutable. By doing so, views of arrays can be shared without concern of mutation causing unexpected side effects.

A NumPy array can easily be made immutable by setting the ``writeable`` flag to ``False`` on the ``flags`` interface. After setting this value, the ``flags`` display shows ``WRITEABLE`` as ``False``, and attempting to mutate this array results in an exception.

>>> a1.flags.writeable = False
>>> a1.flags
  C_CONTIGUOUS : True
  F_CONTIGUOUS : True
  OWNDATA : True
  WRITEABLE : False
  ALIGNED : True
  WRITEBACKIFCOPY : False
  UPDATEIFCOPY : False

>>> a1[0] = -1
Traceback (most recent call last):
  File "<console>", line 1, in <module>
ValueError: assignment destination is read-only

The best performance is possible, with no risk of side-effects, by embracing immutable views of NumPy arrays.



The Advantages of No-Copy DataFrame Operations
------------------------------------------------

This insight, that an immutable-array-based data model offers the best performance with the minimum risk, was foundational to the creation of the StaticFrame DataFrame library. As StaticFrame (like Pandas) manages data stored in NumPy arrays, embracing the usage of data views (without having to make defensive copies) offers significant performance advantages. Without an immutable data model, Pandas cannot make such use of array views.

StaticFrame is not yet always faster than Pandas: Pandas has very performant operations for joins and other specialized transformations. But when leveraging no-copy array operations, StaticFrame can be a lot faster.

To compare performance, we will use the `FrameFixtures <https://github.com/static-frame/frame-fixtures>`_ library to create two DataFrames of 10,000 rows by 1,000 columns of heterogeneous types. For both we can convert the StaticFrame ``Frame`` into a Pandas ``DataFrame``.

>>> import static_frame as sf
>>> import pandas as pd
>>> sf.__version__, pd.__version__
('0.9.21', '1.5.1')

>>> import frame_fixtures as ff
>>> f1 = ff.parse('s(10_000,1000)|v(int,int,str,float)')
>>> df1 = f1.to_pandas()
>>> f2 = ff.parse('s(10_000,1000)|v(int,bool,bool,float)')
>>> df2 = f2.to_pandas()


A simple example of the advantage of a no-copy operation is renaming an axis. With Pandas, all underlying data is defensively copied. With StaticFrame, all underlying data is re-used; only lightweight outer containers have to be created. StaticFrame (~0.01 ms) is almost four orders of magnitude faster than Pandas (~100 ms).

>>> %timeit f1.rename(index='foo')
35.8 µs ± 496 ns per loop (mean ± std. dev. of 7 runs, 10000 loops each)
>>> %timeit df1.rename_axis('foo')
167 ms ± 4.72 ms per loop (mean ± std. dev. of 7 runs, 1 loop each)


Given a DataFrame, it is often necessary to make a column into the index. When Pandas does this, it has to copy the column data to the index, as well as copy all the underlying data. StaticFrame can re-use a view of the column in the index, as well as re-use all of the underlying data. StaticFrame (~1 ms) is two orders of magnitude faster than Pandas (~100 ms).

>>> %timeit f1.set_index(0)
1.25 ms ± 23.7 µs per loop (mean ± std. dev. of 7 runs, 1000 loops each)
>>> %timeit df1.set_index(0, drop=False)
166 ms ± 3.52 ms per loop (mean ± std. dev. of 7 runs, 1 loop each)


Extracting a subset of columns from a DataFrame is another common operation. For StaticFrame, this is a no-copy operation: the returned DataFrame simply holds views to the column data in the original DataFrame. StaticFrame (~10 µs) can do this an order of magnitude faster than Pandas (~100 µs).

>>> %timeit f1[[10, 50, 100, 500]]
25.4 µs ± 471 ns per loop (mean ± std. dev. of 7 runs, 10000 loops each)
>>> %timeit df1[[10, 50, 100, 500]]
729 µs ± 4.14 µs per loop (mean ± std. dev. of 7 runs, 1000 loops each)


It is common to concatenate two or more DataFrames. If they have the same index, and we concatenate them horizontally, StaticFrame can re-use all the underlying data of the inputs, making this form of concatenation a no-copy operation. StaticFrame (~1 ms) can do this two orders of magnitude faster than Pandas (~100 ms).

>>> %timeit sf.Frame.from_concat((f1, f2), axis=1, columns=sf.IndexAutoFactory)
1.16 ms ± 50.1 µs per loop (mean ± std. dev. of 7 runs, 1000 loops each)
>>> %timeit pd.concat((df1, df2), axis=1)
102 ms ± 14.4 ms per loop (mean ± std. dev. of 7 runs, 10 loops each)


NumPy was designed to take advantage of sharing views of data. Because Pandas permits in-place mutation, it cannot make optimal use of NumPy views. As StaticFrame is built on an immutable data model, side-effect mutation risk is eliminated and no-copy operations are embraced, providing a significant performance advantage.




