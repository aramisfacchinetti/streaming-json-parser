from collections.abc import Callable
from enum import Enum
from typing import Any, Literal, Protocol, TypeAlias, TypeVar, overload

_T = TypeVar("_T")
_JsonInput: TypeAlias = str | bytes | bytearray
_JsonScalar: TypeAlias = None | bool | int | float | str
_JsonValue: TypeAlias = _JsonScalar | list["_JsonValue"] | dict[str, "_JsonValue"]
_PathSegment: TypeAlias = str | int
_JsonPath: TypeAlias = tuple[_PathSegment, ...]


class ParseStatus(str, Enum):
    EMPTY: ParseStatus
    PARTIAL: ParseStatus
    COMPLETE: ParseStatus
    INVALID: ParseStatus


class ParseResult(Protocol):
    """Observable parser result contract; construction is not public API."""

    @property
    def status(self) -> ParseStatus: ...

    @property
    def value(self) -> object | None: ...

    @property
    def complete(self) -> bool: ...

    @property
    def error(self) -> str | None: ...


class HighPerformanceStreamingJsonParser:
    def __init__(
        self,
        *,
        framing: Literal["single", "ndjson"] = "single",
        schema_mode: Literal["generic", "adaptive"] = "generic",
        partial_mode: Literal["strict", "structural", "structural_trailing_strings"] = "strict",
        record_type: type[Any] | None = None,
        value_type: type[Any] | None = None,
    ) -> None: ...

    def consume(self, data: _JsonInput) -> None: ...
    def feed(self, data: _JsonInput, copy_value: bool = False) -> ParseResult: ...
    def poll(self, copy_value: bool = False) -> ParseResult: ...
    def poll_many(
        self, *, copy_value: bool = False, max_items: int | None = None
    ) -> list[object]: ...
    def finish(self, copy_value: bool = False) -> ParseResult: ...
    def reset(self) -> None: ...


@overload
def decode_complete_json(data: _JsonInput, *, value_type: type[_T]) -> _T: ...
@overload
def decode_complete_json(
    data: _JsonInput, *, value_type: None = None
) -> _JsonValue: ...

def decode_complete_json_view(data: _JsonInput) -> Any:
    """View results depend on optional simdjson proxy semantics."""


@overload
def decode_ndjson(data: _JsonInput, *, record_type: type[_T]) -> list[_T]: ...
@overload
def decode_ndjson(
    data: _JsonInput, *, record_type: None = None
) -> list[_JsonValue]: ...


def decode_ndjson_adaptive(data: _JsonInput) -> list[object]: ...
def decode_structural_partial_json(
    data: _JsonInput, *, trailing_strings: bool = False
) -> _JsonValue | None: ...


# A complete-document path can yield simdjson proxy values when that optional
# backend is selected, so retain broad leaf types but keep the result shape.
@overload
def extract_complete_json_paths(data: _JsonInput, path: _JsonPath) -> Any: ...
@overload
def extract_complete_json_paths(
    data: _JsonInput, path1: _JsonPath, path2: _JsonPath, *paths: _JsonPath
) -> tuple[Any, ...]: ...


@overload
def extract_ndjson_paths(data: _JsonInput, path: _JsonPath) -> list[_JsonValue]: ...
@overload
def extract_ndjson_paths(
    data: _JsonInput, path1: _JsonPath, path2: _JsonPath, *paths: _JsonPath
) -> list[tuple[_JsonValue, ...]]: ...


# Typed path helpers infer a model at runtime from the sample; the selected
# field types cannot be named statically, but tuple/list output shapes are known.
@overload
def extract_complete_json_typed_paths(
    data: _JsonInput,
    path: tuple[str, ...],
    *,
    sample: dict[str, Any] | None = None,
) -> Any: ...
@overload
def extract_complete_json_typed_paths(
    data: _JsonInput,
    path1: tuple[str, ...],
    path2: tuple[str, ...],
    *paths: tuple[str, ...],
    sample: dict[str, Any] | None = None,
) -> tuple[Any, ...]: ...


@overload
def extract_ndjson_paths_native(
    data: _JsonInput, path: _JsonPath
) -> list[_JsonValue]: ...
@overload
def extract_ndjson_paths_native(
    data: _JsonInput,
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
) -> list[tuple[_JsonValue, ...]]: ...


@overload
def extract_ndjson_typed_paths(
    data: _JsonInput,
    path: tuple[str, ...],
    *,
    sample: dict[str, Any] | None = None,
) -> list[Any]: ...
@overload
def extract_ndjson_typed_paths(
    data: _JsonInput,
    path1: tuple[str, ...],
    path2: tuple[str, ...],
    *paths: tuple[str, ...],
    sample: dict[str, Any] | None = None,
) -> list[tuple[Any, ...]]: ...


@overload
def extract_tuned_complete_json_paths(
    data: _JsonInput,
    path: _JsonPath,
    *,
    sample: dict[str, Any] | None = None,
) -> Any: ...
@overload
def extract_tuned_complete_json_paths(
    data: _JsonInput,
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    sample: dict[str, Any] | None = None,
) -> tuple[Any, ...]: ...


@overload
def extract_tuned_json_paths(
    data: _JsonInput,
    path: _JsonPath,
    *,
    framing: Literal["single"] = "single",
    sample: dict[str, Any] | None = None,
) -> Any: ...
@overload
def extract_tuned_json_paths(
    data: _JsonInput,
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    framing: Literal["single"] = "single",
    sample: dict[str, Any] | None = None,
) -> tuple[Any, ...]: ...
@overload
def extract_tuned_json_paths(
    data: _JsonInput,
    path: _JsonPath,
    *,
    framing: Literal["ndjson"],
    sample: dict[str, Any] | None = None,
) -> list[Any]: ...
@overload
def extract_tuned_json_paths(
    data: _JsonInput,
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    framing: Literal["ndjson"],
    sample: dict[str, Any] | None = None,
) -> list[tuple[Any, ...]]: ...


@overload
def extract_tuned_ndjson_paths(
    data: _JsonInput,
    path: _JsonPath,
    *,
    sample: dict[str, Any] | None = None,
) -> list[Any]: ...
@overload
def extract_tuned_ndjson_paths(
    data: _JsonInput,
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    sample: dict[str, Any] | None = None,
) -> list[tuple[Any, ...]]: ...


@overload
def make_complete_json_decoder(*, value_type: type[_T]) -> Callable[[_JsonInput], _T]: ...
@overload
def make_complete_json_decoder(
    *, value_type: None = None
) -> Callable[[_JsonInput], _JsonValue]: ...


@overload
def make_complete_json_typed_path_extractor(
    path: tuple[str, ...], *, sample: dict[str, Any]
) -> Callable[[_JsonInput], Any]: ...
@overload
def make_complete_json_typed_path_extractor(
    path1: tuple[str, ...],
    path2: tuple[str, ...],
    *paths: tuple[str, ...],
    sample: dict[str, Any],
) -> Callable[[_JsonInput], tuple[Any, ...]]: ...

# The optional simdjson decoder exposes backend-specific proxy objects.
def make_complete_json_view_decoder() -> Callable[[_JsonInput], Any]: ...


@overload
def make_json_path_extractor(path: _JsonPath) -> Callable[[_JsonInput], Any]: ...
@overload
def make_json_path_extractor(
    path1: _JsonPath, path2: _JsonPath, *paths: _JsonPath
) -> Callable[[_JsonInput], tuple[Any, ...]]: ...


@overload
def make_ndjson_decoder(*, record_type: type[_T]) -> Callable[[_JsonInput], list[_T]]: ...
@overload
def make_ndjson_decoder(
    *, record_type: None = None
) -> Callable[[_JsonInput], list[_JsonValue]]: ...


@overload
def make_ndjson_path_extractor(path: _JsonPath) -> Callable[[_JsonInput], list[_JsonValue]]: ...
@overload
def make_ndjson_path_extractor(
    path1: _JsonPath, path2: _JsonPath, *paths: _JsonPath
) -> Callable[[_JsonInput], list[tuple[_JsonValue, ...]]]: ...


@overload
def make_ndjson_path_extractor_native(
    path: _JsonPath,
) -> Callable[[_JsonInput], list[_JsonValue]]: ...
@overload
def make_ndjson_path_extractor_native(
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
) -> Callable[[_JsonInput], list[tuple[_JsonValue, ...]]]: ...


@overload
def make_ndjson_typed_path_extractor(
    path: tuple[str, ...], *, sample: dict[str, Any]
) -> Callable[[_JsonInput], list[Any]]: ...
@overload
def make_ndjson_typed_path_extractor(
    path1: tuple[str, ...],
    path2: tuple[str, ...],
    *paths: tuple[str, ...],
    sample: dict[str, Any],
) -> Callable[[_JsonInput], list[tuple[Any, ...]]]: ...


@overload
def make_tuned_complete_json_decoder(
    *,
    value_type: type[_T],
    payload_size_hint: int | None = None,
    sample: _JsonInput | None = None,
    mode: Literal["materialize"] = "materialize",
) -> Callable[[_JsonInput], _T]: ...
@overload
def make_tuned_complete_json_decoder(
    *,
    value_type: None = None,
    payload_size_hint: int | None = None,
    sample: _JsonInput | None = None,
    mode: Literal["materialize"] = "materialize",
) -> Callable[[_JsonInput], _JsonValue]: ...
@overload
def make_tuned_complete_json_decoder(
    *,
    value_type: type[Any] | None = None,
    payload_size_hint: int | None = None,
    sample: _JsonInput | None = None,
    mode: Literal["view"],
) -> Callable[[_JsonInput], Any]: ...


@overload
def make_tuned_complete_json_path_extractor(
    path: _JsonPath,
    *,
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], Any]: ...
@overload
def make_tuned_complete_json_path_extractor(
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], tuple[Any, ...]]: ...


@overload
def make_tuned_json_path_extractor(
    path: _JsonPath,
    *,
    framing: Literal["single"] = "single",
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], Any]: ...
@overload
def make_tuned_json_path_extractor(
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    framing: Literal["single"] = "single",
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], tuple[Any, ...]]: ...
@overload
def make_tuned_json_path_extractor(
    path: _JsonPath,
    *,
    framing: Literal["ndjson"],
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], list[Any]]: ...
@overload
def make_tuned_json_path_extractor(
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    framing: Literal["ndjson"],
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], list[tuple[Any, ...]]]: ...


@overload
def make_tuned_ndjson_decoder(
    *,
    record_type: type[_T],
    sample: _JsonInput | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], list[_T]]: ...
@overload
def make_tuned_ndjson_decoder(
    *,
    record_type: None = None,
    sample: _JsonInput | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], list[_JsonValue]]: ...


# The tuned NDJSON extractor may choose a sample-inferred record path.
@overload
def make_tuned_ndjson_path_extractor(
    path: _JsonPath,
    *,
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], list[Any]]: ...
@overload
def make_tuned_ndjson_path_extractor(
    path1: _JsonPath,
    path2: _JsonPath,
    *paths: _JsonPath,
    sample: dict[str, Any] | None = None,
    payload_size_hint: int | None = None,
) -> Callable[[_JsonInput], list[tuple[Any, ...]]]: ...

def make_tuned_structural_partial_decoder(
    *, sample: _JsonInput | None = None, trailing_strings: bool = False
) -> Callable[[_JsonInput], _JsonValue | None]: ...
