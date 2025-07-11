#!/usr/bin/env python
# vim: sw=4:ts=4:expandtab

"""
csv2ofx.main
~~~~~~~~~~~~

Provides the primary ofx and qif conversion functions

Examples:
    literal blocks::

        python example_google.py

Attributes:
    ENCODING (str): Default file encoding.
"""

import itertools as it
import os.path
import pathlib
import sys
import time
import traceback
from argparse import ArgumentParser, RawTextHelpFormatter
from datetime import datetime as dt
from importlib import import_module, util
from math import inf
from operator import itemgetter
from pkgutil import iter_modules
from pprint import pprint

try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError

import builtins

from dateutil.parser import parse
from meza.io import IterStringIO, read_csv, write

from . import BalanceError, utils
from .ofx import OFX
from .qif import QIF

parser = ArgumentParser(  # pylint: disable=invalid-name
    description="description: csv2ofx converts a csv file to ofx and qif",
    prog="csv2ofx",
    usage="%(prog)s [options] <source> <dest>",
    formatter_class=RawTextHelpFormatter,
)

TYPES = ["CHECKING", "SAVINGS", "MONEYMRKT", "CREDITLINE", "Bank", "Cash"]
MAPPINGS = import_module("csv2ofx.mappings")
MODULES = tuple(itemgetter(1)(m) for m in iter_modules(MAPPINGS.__path__))


def load_package_module(name):
    return import_module(f"csv2ofx.mappings.{name}")


def load_custom_module(filepath: str):
    """
    >>> mod = load_custom_module("csv2ofx/mappings/amazon.py")
    >>> mod.__name__
    'amazon'
    """
    path = pathlib.Path(filepath)
    spec = util.spec_from_file_location(path.stem, path)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parser.add_argument(
    dest="source", nargs="?", help="the source csv file (default: stdin)"
)
parser.add_argument(dest="dest", nargs="?", help="the output file (default: stdout)")
parser.add_argument(
    "-a",
    "--account",
    metavar="TYPE",
    dest="account_type",
    choices=TYPES,
    help="default account type 'CHECKING' for OFX and 'Bank' for QIF.",
)
parser.add_argument(
    "-i",
    "--institution",
    metavar="INSTITUTION",
    help="financial institution ID to include in the header (default: None)",
)
parser.add_argument(
    "-e",
    "--end",
    metavar="DATE",
    help="end date (default: today)",
    default=str(dt.now()),
)
parser.add_argument(
    "-B",
    "--ending-balance",
    metavar="BALANCE",
    type=float,
    help="ending balance (default: None)",
)
parser.add_argument(
    "-l", "--language", help="the language (default: ENG)", default="ENG"
)
parser.add_argument("-s", "--start", metavar="DATE", help="the start date")
parser.add_argument(
    "-y",
    "--dayfirst",
    help="interpret the first value in ambiguous dates (e.g. 01/05/09) as the day",
    action="store_true",
    default=False,
)
parser.add_argument(
    "-m",
    "--mapping",
    metavar="MAPPING_NAME",
    help="the account mapping (default: default)",
    default="default",
    choices=MODULES,
)
parser.add_argument(
    "-x",
    "--custom",
    metavar="FILE_PATH",
    help="path to a custom mapping file",
    type=load_custom_module,
)
parser.add_argument(
    "-c",
    "--collapse",
    metavar="FIELD_NAME",
    help=(
        "field used to combine transactions within a split for double entry statements"
    ),
)
parser.add_argument(
    "-C",
    "--chunksize",
    metavar="ROWS",
    type=int,
    default=2**14,
    help="number of rows to process at a time (default: 2 ** 14)",
)
parser.add_argument(
    "-r",
    "--first-row",
    metavar="ROWS",
    type=int,
    default=0,
    help="the first row to process (zero based)",
)
parser.add_argument(
    "-R",
    "--last-row",
    metavar="ROWS",
    type=int,
    default=inf,
    help="the last row to process (zero based, negative values count from the end)",
)
parser.add_argument(
    "-O",
    "--first-col",
    metavar="COLS",
    type=int,
    default=0,
    help="the first column to process (zero based)",
)
parser.add_argument(
    "-L",
    "--list-mappings",
    help="list the available mappings",
    action="store_true",
    default=False,
)
parser.add_argument(
    "-V", "--version", help="show version and exit", action="store_true", default=False
)
parser.add_argument(
    "-q",
    "--qif",
    help="enables 'QIF' output instead of 'OFX'",
    action="store_true",
    default=False,
)
parser.add_argument(
    "-S",
    "--strict",
    help="enables strict mode requiring extended headers, back ID and balance",
    action="store_true",
    default=False,
)
parser.add_argument(
    "-o",
    "--overwrite",
    action="store_true",
    default=False,
    help="overwrite destination file if it exists",
)
parser.add_argument(
    "-D",
    "--server-date",
    metavar="DATE",
    help="OFX server date (default: source file mtime)",
)
parser.add_argument(
    "-E", "--encoding", default="utf-8", help="File encoding (default: utf-8)"
)
parser.add_argument(
    "-d",
    "--debug",
    action="store_true",
    default=False,
    help="display the options and arguments passed to the parser",
)
parser.add_argument(
    "-v", "--verbose", help="verbose output", action="store_true", default=False
)


def _time_from_file(path):
    return os.path.getmtime(path)


def run(args=None):  # noqa: C901
    """Parses the CLI options and runs the main program"""
    args = parser.parse_args(args)
    if args.debug:
        pprint(dict(args._get_kwargs()))  # pylint: disable=W0212
        sys.exit(0)

    if args.version:
        from . import __version__ as version

        print(f"v{version}")
        sys.exit(0)

    if args.list_mappings:
        print(", ".join(MODULES))
        sys.exit(0)

    mapping = (args.custom or load_package_module(args.mapping)).mapping

    okwargs = {
        "def_type": args.account_type or ("Bank" if args.qif else "CHECKING"),
        "start": parse(args.start, dayfirst=args.dayfirst) if args.start else None,
        "end": parse(args.end, dayfirst=args.dayfirst) if args.end else None,
        "strict": args.strict,
        "institution": args.institution,
    }

    cont = QIF(mapping, **okwargs) if args.qif else OFX(mapping, **okwargs)
    source = (
        builtins.open(args.source, encoding=args.encoding) if args.source else sys.stdin
    )

    ckwargs = {
        "has_header": cont.has_header,
        "custom_header": getattr(cont, "custom_header", None),
        "delimiter": mapping.get("delimiter", ","),
        "first_row": mapping.get("first_row", args.first_row),
        "last_row": mapping.get("last_row", args.last_row),
        "first_col": mapping.get("first_col", args.first_col),
    }

    try:
        records = read_csv(source, **ckwargs)
        groups = cont.gen_groups(records, args.chunksize)
        trxns = cont.gen_trxns(groups, args.collapse)
        cleaned_trxns = cont.clean_trxns(trxns)
        data = utils.gen_data(cleaned_trxns)
        body = cont.gen_body(data)

        if args.server_date:
            server_date = parse(args.server_date, dayfirst=args.dayfirst)
        else:
            try:
                mtime = _time_from_file(source.name)
            except (AttributeError, FileNotFoundError):
                mtime = time.time()

            server_date = dt.fromtimestamp(mtime)

        header = cont.header(date=server_date, language=args.language)
        footer = cont.footer(date=server_date, balance=args.ending_balance)
        filtered = filter(None, [header, body, footer])
        content = it.chain.from_iterable(filtered)
        kwargs = {
            "overwrite": args.overwrite,
            "chunksize": args.chunksize,
            "encoding": args.encoding,
        }
    except Exception as err:  # pylint: disable=broad-except
        source.close() if args.source else None
        sys.exit(err)

    dest = (
        builtins.open(args.dest, "w", encoding=args.encoding)
        if args.dest
        else sys.stdout
    )

    try:
        res = write(dest, IterStringIO(content), **kwargs)
    except KeyError as err:
        traceback.print_exc()
        msg = f"Field {err} is missing from file. Check `mapping` option."
    except TypeError as err:
        msg = f"No data to write. {str(err)}. "

        if args.collapse:
            msg += "Check `start` and `end` options."
        else:
            msg += "Try again with `-c` option."
    except ValueError as err:
        # csv2ofx called with no arguments or broken mapping
        msg = f"Possible mapping problem: {str(err)}."
        parser.print_help()
    except BalanceError as err:
        msg = f"{err}.  Try again with `--ending-balance` option."
    except Exception:  # pylint: disable=broad-except
        msg = 1
        traceback.print_exc()
    else:
        msg = 0 if res else "No data to write. Check `start` and `end` options."
    finally:
        source.close() if args.source else None
        dest.close() if args.dest else None
        sys.exit(msg)


if __name__ == "__main__":
    run()
