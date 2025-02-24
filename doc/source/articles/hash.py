


import hashlib
import os
import sys
import tempfile
import timeit
import typing as tp
from itertools import repeat

import frame_fixtures as ff
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.append(os.getcwd())

import static_frame as sf
from static_frame.core.display_color import HexColor
from static_frame.core.util import bytes_to_size_label


class HashingTest:
    SUFFIX = '.tmp'

    def __init__(self, fixture: str):
        self.sff = ff.parse(fixture)
        self.pdf = self.sff.to_pandas()

    def __call__(self):
        raise NotImplementedError()


class SFDigestSHA256(HashingTest):

    def __call__(self):
        post = self.sff.via_hashlib(include_name=False).sha256().hexdigest()


class PandasHash(HashingTest):

    def __call__(self):
        post = pd.util.hash_pandas_object(self.pdf)


class PandasHashSHA256(HashingTest):

    def __call__(self):
        post = pd.util.hash_pandas_object(self.pdf)
        x  = hashlib.sha256(post.values.tobytes()).hexdigest()

class PandasJsonSHA256(HashingTest):
    def __call__(self):
        x  = hashlib.sha256(self.pdf.to_json().encode()).hexdigest()

#-------------------------------------------------------------------------------
NUMBER = 100

def scale(v):
    return int(v * 10)

VALUES_UNIFORM = 'float'
VALUES_MIXED = 'int,int,int,int,bool,bool,bool,bool,float,float,float,float,str,str,str,str'
VALUES_COLUMNAR = 'int,bool,float,str'

FF_wide_uniform = f's({scale(100)},{scale(10_000)})|v({VALUES_UNIFORM})|i(I,int)|c(I,str)'
FF_wide_mixed   = f's({scale(100)},{scale(10_000)})|v({VALUES_MIXED})|i(I,int)|c(I,str)'
FF_wide_columnar = f's({scale(100)},{scale(10_000)})|v({VALUES_COLUMNAR})|i(I,int)|c(I,str)'


FF_tall_uniform = f's({scale(10_000)},{scale(100)})|v({VALUES_UNIFORM})|i(I,int)|c(I,str)'
FF_tall_mixed   = f's({scale(10_000)},{scale(100)})|v({VALUES_MIXED})|i(I,int)|c(I,str)'
FF_tall_columnar   = f's({scale(10_000)},{scale(100)})|v({VALUES_COLUMNAR})|i(I,int)|c(I,str)'

FF_square_uniform = f's({scale(1_000)},{scale(1_000)})|v(float)|i(I,int)|c(I,str)'
FF_square_mixed   = f's({scale(1_000)},{scale(1_000)})|v({VALUES_MIXED})|i(I,int)|c(I,str)'
FF_square_columnar = f's({scale(1_000)},{scale(1_000)})|v({VALUES_COLUMNAR})|i(I,int)|c(I,str)'

#-------------------------------------------------------------------------------

def seconds_to_display(seconds: float) -> str:
    seconds /= NUMBER
    if seconds < 1e-4:
        return f'{seconds * 1e6: .1f} (µs)'
    if seconds < 1e-1:
        return f'{seconds * 1e3: .1f} (ms)'
    return f'{seconds: .1f} (s)'


def plot_performance(frame: sf.Frame):
    fixture_total = len(frame['fixture'].unique())
    cat_total = len(frame['category'].unique())
    name_total = len(frame['name'].unique())

    fig, axes = plt.subplots(cat_total, fixture_total)

    # for legend
    name_replace = {
        SFDigestSHA256.__name__: 'StaticFrame\nvia_hashlib().sha256()',
        PandasHash.__name__: 'Pandas\nhash_pandas_object()',
        PandasHashSHA256.__name__: 'Pandas\nhash_pandas_object()\nhashlib.sha256()',
        PandasJsonSHA256.__name__: 'Pandas\nto_json()\nhashlib.sha256()',
    }

    name_order = {
        SFDigestSHA256.__name__: 0,
        PandasHash.__name__: 1,
        PandasHashSHA256.__name__: 2,
        PandasJsonSHA256.__name__: 3,
    }

    # cmap = plt.get_cmap('terrain')
    cmap = plt.get_cmap('plasma')
    color_count = name_total
    color = cmap(np.arange(color_count) / color_count)

    # categories are read, write
    for cat_count, (cat_label, cat) in enumerate(frame.iter_group_items('category')):
        for fixture_count, (fixture_label, fixture) in enumerate(
                cat.iter_group_items('fixture')):
            ax = axes[cat_count][fixture_count]

            # set order
            fixture = fixture.sort_values('name', key=lambda s:s.iter_element().map_all(name_order))
            results = fixture['time'].values.tolist()
            names = fixture['name'].values.tolist()
            x = np.arange(len(results))
            names_display = [name_replace[l] for l in names]
            post = ax.bar(names_display, results, color=color)

            # ax.set_ylabel()
            title = f'{cat_label.title()}\n{FIXTURE_SHAPE_MAP[fixture_label]}'
            ax.set_title(title, fontsize=8)
            ax.set_box_aspect(0.75) # makes taller tan wide
            time_max = fixture['time'].max()
            ax.set_yticks([0, time_max * 0.5, time_max])
            ax.set_yticklabels(['',
                    seconds_to_display(time_max * 0.5),
                    seconds_to_display(time_max),
                    ], fontsize=6)
            # ax.set_xticks(x, names_display, rotation='vertical')
            ax.tick_params(
                    axis='x',
                    which='both',
                    bottom=False,
                    top=False,
                    labelbottom=False,
                    )

    fig.set_size_inches(6, 3.5) # width, height
    fig.legend(post, names_display, loc='center right', fontsize=8)
    # horizontal, vertical
    count = ff.parse(FF_tall_uniform).size
    fig.text(.05, .96, f'DataFrame to SHA256 Digest Performance: {count:.0e} Elements, {NUMBER} Iterations', fontsize=10)
    fig.text(.05, .90, get_versions(), fontsize=6)

    # get fixtures size reference
    shape_map = {shape: FIXTURE_SHAPE_MAP[shape] for shape in frame['fixture'].unique()}
    shape_msg = ' / '.join(f'{v}: {k}' for k, v in shape_map.items())
    fig.text(.05, .90, shape_msg, fontsize=6)

    fp = '/tmp/delimited.png'
    plt.subplots_adjust(
            left=0.05,
            bottom=0.05,
            right=0.75,
            top=0.75,
            wspace=-0.2, # width
            hspace=1,
            )
    # plt.rcParams.update({'font.size': 22})
    plt.savefig(fp, dpi=300)

    if sys.platform.startswith('linux'):
        os.system(f'eog {fp}&')
    else:
        os.system(f'open {fp}')


#-------------------------------------------------------------------------------

def get_versions() -> str:
    import platform
    return f'OS: {platform.system()} / Pandas: {pd.__version__} / StaticFrame: {sf.__version__} / NumPy: {np.__version__}\n'

FIXTURE_SHAPE_MAP = {
    '1000x10': 'Tall',
    '100x100': 'Square',
    '10x1000': 'Wide',
    '10000x100': 'Tall',
    '1000x1000': 'Square',
    '100x10000': 'Wide',
    '100000x1000': 'Tall',
    '10000x10000': 'Square',
    '1000x100000': 'Wide',
}

def get_format():

    name_root_last = None
    name_root_count = 0

    def format(key: tp.Tuple[tp.Any, str], v: object) -> str:
        nonlocal name_root_last
        nonlocal name_root_count

        if isinstance(v, float):
            if np.isnan(v):
                return ''
            return str(round(v, 4))
        if isinstance(v, (bool, np.bool_)):
            if v:
                return HexColor.format_terminal('green', str(v))
            return HexColor.format_terminal('orange', str(v))

        return str(v)

    return format

def fixture_to_pair(label: str, fixture: str) -> tp.Tuple[str, str, str]:
    # get a title
    f = ff.parse(fixture)
    return label, f'{f.shape[0]:}x{f.shape[1]}', fixture

CLS_READ = (
    SFDigestSHA256,
    # PandasHash,
    PandasJsonSHA256,
    PandasHashSHA256,
    )


def run_test():
    records = []
    for dtype_hetero, fixture_label, fixture in (
            fixture_to_pair('uniform', FF_wide_uniform),
            fixture_to_pair('mixed', FF_wide_mixed),
            fixture_to_pair('columnar', FF_wide_columnar),

            fixture_to_pair('uniform', FF_tall_uniform),
            fixture_to_pair('mixed', FF_tall_mixed),
            fixture_to_pair('columnar', FF_tall_columnar),

            fixture_to_pair('uniform', FF_square_uniform),
            fixture_to_pair('mixed', FF_square_mixed),
            fixture_to_pair('columnar', FF_square_columnar),
            ):

        for cls in CLS_READ:
            runner = cls(fixture)
            category = f'{dtype_hetero}'

            record = [cls.__name__, NUMBER, category, fixture_label]
            print(record)
            try:
                result = timeit.timeit(
                        f'runner()',
                        globals=locals(),
                        number=NUMBER)
            except OSError:
                result = np.nan
            finally:
                pass
            record.append(result)
            records.append(record)

    f = sf.FrameGO.from_records(records,
            columns=('name', 'number', 'category', 'fixture', 'time')
            )

    display = f.iter_element_items().apply(get_format())

    config = sf.DisplayConfig(
            cell_max_width_leftmost=np.inf,
            cell_max_width=np.inf,
            type_show=False,
            display_rows=200,
            include_index=False,
            )
    print(display.display(config))

    plot_performance(f)

if __name__ == '__main__':

    run_test()



