from collections import Counter
import re
from pathlib import Path

import streaming_json_parser


EXPECTED_PUBLIC_API = {
    "StreamingJsonParser",
    "__version__",
    "HighPerformanceStreamingJsonParser",
    "ParseResult",
    "ParseStatus",
    "decode_complete_json",
    "decode_complete_json_view",
    "decode_ndjson",
    "decode_ndjson_adaptive",
    "decode_structural_partial_json",
    "extract_complete_json_paths",
    "extract_complete_json_typed_paths",
    "extract_ndjson_paths",
    "extract_ndjson_paths_native",
    "extract_ndjson_typed_paths",
    "extract_tuned_complete_json_paths",
    "extract_tuned_json_paths",
    "extract_tuned_ndjson_paths",
    "make_complete_json_decoder",
    "make_complete_json_typed_path_extractor",
    "make_complete_json_view_decoder",
    "make_json_path_extractor",
    "make_ndjson_decoder",
    "make_ndjson_path_extractor",
    "make_ndjson_path_extractor_native",
    "make_ndjson_typed_path_extractor",
    "make_tuned_complete_json_decoder",
    "make_tuned_complete_json_path_extractor",
    "make_tuned_json_path_extractor",
    "make_tuned_ndjson_decoder",
    "make_tuned_ndjson_path_extractor",
    "make_tuned_structural_partial_decoder",
}


def test_top_level_public_api_is_intentional():
    assert len(streaming_json_parser.__all__) == len(EXPECTED_PUBLIC_API)
    assert set(streaming_json_parser.__all__) == EXPECTED_PUBLIC_API
    assert all(hasattr(streaming_json_parser, name) for name in EXPECTED_PUBLIC_API)


def test_streaming_parser_compatibility_alias_is_identical():
    assert (
        streaming_json_parser.StreamingJsonParser
        is streaming_json_parser.HighPerformanceStreamingJsonParser
    )

    def observed_results(parser_type):
        parser = parser_type()
        partial = parser.feed('{"value":"par')
        complete = parser.feed('tial"}')
        return tuple(
            (result.status, result.value, result.complete, result.error)
            for result in (partial, complete)
        )

    assert observed_results(
        streaming_json_parser.StreamingJsonParser
    ) == observed_results(streaming_json_parser.HighPerformanceStreamingJsonParser)


def test_api_inventory_and_migration_matrix_cover_exported_surface():
    documentation_path = Path(__file__).resolve().parents[1] / "docs" / "public-api.md"
    documentation = documentation_path.read_text(encoding="utf-8")
    inventory = documentation.split("| Export (kind) |", 1)[1].split(
        "The README shows the quickstart", 1
    )[0]
    inventory_tiers = {}
    for line in inventory.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        name_match = re.match(r"`([^`]+)`", cells[0])
        tier_match = re.search(
            r"\*\*(Primary|Advanced|Experimental|Compatibility|Internal candidate)",
            cells[-1],
        )
        assert name_match and tier_match, line
        inventory_tiers[name_match.group(1)] = tier_match.group(1)

    assert set(inventory_tiers) == set(streaming_json_parser.__all__)
    assert Counter(inventory_tiers.values()) == {
        "Primary": 12,
        "Advanced": 15,
        "Experimental": 2,
        "Compatibility": 2,
        "Internal candidate": 1,
    }

    usage = documentation.split(
        "| Export | Package calls | Test files | Benchmark scripts |", 1
    )[1].split("\n\n", 1)[0]
    usage_names = set()
    for line in usage.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        name_match = re.match(r"`([^`]+)`", cells[0])
        assert name_match and len(cells) == 7, line
        assert all(cell.isdigit() for cell in cells[1:]), line
        usage_names.add(name_match.group(1))
    assert usage_names == set(inventory_tiers)

    migration = documentation.split(
        "| Current API | Current tier | Canonical replacement |", 1
    )[1].split("\n\n", 1)[0]
    migration_tiers = {}
    for line in migration.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        name_match = re.match(r"`([^`]+)`", cells[0])
        assert name_match and len(cells) == 6, line
        migration_tiers[name_match.group(1)] = cells[1]

    expected_migration = {
        name: tier for name, tier in inventory_tiers.items() if tier != "Primary"
    }
    assert migration_tiers == expected_migration
