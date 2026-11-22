"""Low-level I/O helpers: chunked CSV reading and streaming sinks."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .schema import ALL_COLUMNS, SCHEMA

PARQUET_COMPRESSION = "zstd"
PARQUET_COMPRESSION_LEVEL = 3


def chunked_csv(
    path: Path,
    chunksize: int,
    *,
    usecols: Iterable[str] | None = None,
    dtypes: dict[str, str] | None = None,
    **kwargs,
) -> Iterator[pd.DataFrame]:
    """Yield chunks of a CSV file (plain or gzip, auto-detected by pandas)."""
    return pd.read_csv(
        path,
        chunksize=chunksize,
        usecols=list(usecols) if usecols else None,
        dtype=dtypes,
        low_memory=False,
        **kwargs,
    )


def read_header(path: Path) -> list[str]:
    """Return the column names of a CSV file without reading the body."""
    return list(pd.read_csv(path, nrows=0).columns)


def _empty_table(schema: pa.Schema) -> pa.Table:
    return pa.table({f.name: pa.nulls(0, f.type) for f in schema})


class ParquetSink:
    """Append-only Parquet writer with a fixed schema."""

    def __init__(self, path: Path, schema: pa.Schema = SCHEMA) -> None:
        self.path = Path(path)
        self.schema = schema
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()
        self._writer = pq.ParquetWriter(
            self.path,
            schema,
            compression=PARQUET_COMPRESSION,
            compression_level=PARQUET_COMPRESSION_LEVEL,
            use_dictionary=True,
        )
        self.rows = 0

    def write(self, frame: pd.DataFrame) -> None:
        table = self._to_table(frame)
        if table.num_rows == 0:
            return
        self._writer.write_table(table)
        self.rows += table.num_rows

    def _to_table(self, frame: pd.DataFrame) -> pa.Table:
        if frame.empty:
            return _empty_table(self.schema)
        missing = [f for f in self.schema if f.name not in frame.columns]
        present = frame[[f.name for f in self.schema if f.name in frame.columns]]
        table = pa.Table.from_pandas(present, preserve_index=False)
        for f in missing:
            table = table.append_column(f.name, pa.nulls(len(frame), f.type))
        return table.select(self.schema.names).cast(self.schema)

    def close(self) -> None:
        self._writer.close()
        if self.rows == 0:
            # Ensure a valid (empty) file with the full schema exists.
            pq.write_table(_empty_table(self.schema), self.path, compression="zstd")

    def __enter__(self) -> "ParquetSink":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class CsvSink:
    """Append-only UTF-8 CSV writer (optionally gzip)."""

    def __init__(self, path: Path, columns: Iterable[str] = ALL_COLUMNS) -> None:
        self.path = Path(path)
        self.columns = list(columns)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._first = True
        if self.path.exists():
            self.path.unlink()
        self.rows = 0

    def write(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        out = frame.reindex(columns=self.columns)
        out = out.copy()
        for col in ("time", "issued_utc"):
            if col in out.columns:
                out[col] = out[col].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.to_csv(
            self.path,
            mode="a",
            header=self._first,
            index=False,
            quoting=csv.QUOTE_MINIMAL,
        )
        self._first = False
        self.rows += len(out)

    def close(self) -> None:
        if self._first:
            pd.DataFrame(columns=self.columns).to_csv(self.path, index=False)

    def __enter__(self) -> "CsvSink":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
