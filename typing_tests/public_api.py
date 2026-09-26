from collections.abc import Callable
from dataclasses import dataclass

from streaming_json_parser import (
    ParseResult,
    ParseStatus,
    StreamingJsonParser,
    decode_complete_json,
    decode_ndjson,
    decode_structural_partial_json,
    extract_complete_json_paths,
    extract_ndjson_paths,
    make_complete_json_decoder,
    make_ndjson_decoder,
    make_tuned_complete_json_decoder,
    make_tuned_json_path_extractor,
    make_tuned_ndjson_decoder,
    make_tuned_structural_partial_decoder,
)


@dataclass
class User:
    id: int
    name: str


parser = StreamingJsonParser()
result: ParseResult = parser.feed(b'{"id": 7, "name": "Ada"}')
status: ParseStatus = result.status
complete: bool = result.complete
error: str | None = result.error
if status is ParseStatus.COMPLETE and result.value is not None:
    retained_snapshot: object = result.value

ndjson_parser = StreamingJsonParser(framing="ndjson")
ndjson_parser.feed(b'{"id": 7}\n')
ready_records: list[object] = ndjson_parser.poll_many()

decoded_json = decode_complete_json('{"id": 7, "name": "Ada"}')
decoded_records = decode_ndjson(b'{"id": 7}\n')
structural_value = decode_structural_partial_json('{"id": 7')

generic_decoder: Callable[[str | bytes | bytearray], object] = (
    make_complete_json_decoder()
)
tuned_decoder: Callable[[str | bytes | bytearray], object] = (
    make_tuned_complete_json_decoder(
        sample=b'{"id": 7, "name": "Ada"}', payload_size_hint=64
    )
)
generic_ndjson_decoder: Callable[[str | bytes | bytearray], object] = (
    make_ndjson_decoder()
)
typed_decoder: Callable[[str | bytes | bytearray], User] = (
    make_complete_json_decoder(value_type=User)
)
typed_tuned_decoder: Callable[[str | bytes | bytearray], User] = (
    make_tuned_complete_json_decoder(value_type=User)
)
typed_ndjson_decoder: Callable[[str | bytes | bytearray], list[User]] = (
    make_ndjson_decoder(record_type=User)
)
typed_tuned_ndjson_decoder: Callable[[str | bytes | bytearray], list[User]] = (
    make_tuned_ndjson_decoder(record_type=User)
)

decoded_user: User = decode_complete_json(
    b'{"id": 7, "name": "Ada"}', value_type=User
)
decoded_typed_records: list[User] = decode_ndjson(
    b'{"id": 7, "name": "Ada"}\n', record_type=User
)

single_path_value = extract_complete_json_paths(
    b'{"user": {"id": 7}}', ("user", "id")
)
multiple_path_values = extract_complete_json_paths(
    b'{"user": {"id": 7, "name": "Ada"}}',
    ("user", "id"),
    ("user", "name"),
)
ndjson_path_values = extract_ndjson_paths(
    b'{"user": {"id": 7}}\n', ("user", "id")
)
single_extractor = make_tuned_json_path_extractor(
    ("user", "id"), framing="single"
)
ndjson_extractor = make_tuned_json_path_extractor(
    ("user", "id"), framing="ndjson"
)
multiple_extractor = make_tuned_json_path_extractor(
    ("user", "id"), ("user", "name"), framing="single"
)
structural_decoder = make_tuned_structural_partial_decoder(sample=b'{"id": 7')
structural_result = structural_decoder(b'{"id": 7')
