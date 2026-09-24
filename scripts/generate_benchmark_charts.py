#!/usr/bin/env python3
"""Render deterministic SVG charts from the benchmark snapshot JSON."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


CHARTS = (
    ("complete_1mb_object", "complete-decoding.svg", "Complete JSON decoding"),
    (
        "complete_selective_extraction",
        "selective-extraction.svg",
        "Complete-document selective extraction",
    ),
    (
        "ndjson_selective_extraction",
        "ndjson-selective-extraction.svg",
        "NDJSON selective extraction",
    ),
)

_PROJECT_RESULT_PREFIXES = (
    "facade_",
    "hybrid_",
    "repo_",
    "streaming_parser_",
    "tuned_",
    "typed_",
    "generic_",
    "native_",
)
_RESULT_LABELS = {
    "msgspec_decode": "msgspec",
    "facade_reusable_complete_decoder": "Reusable complete decoder",
    "simdjson_parse": "simdjson, materialized as dict",
    "streaming_parser_single_chunk": "StreamingJsonParser — single chunk",
    "facade_decode_complete_json": "decode_complete_json",
    "orjson_loads": "orjson",
    "repo_path_extractor": "make_json_path_extractor",
    "repo_extract_once": "extract_complete_json_paths",
    "typed_complete_path_extractor": "make_complete_json_typed_path_extractor",
    "typed_complete_extract_once": "extract_complete_json_typed_paths",
    "tuned_complete_path_extractor": "make_tuned_complete_json_path_extractor",
    "tuned_complete_extract_once": "extract_tuned_complete_json_paths",
    "tuned_json_path_extractor": "make_tuned_json_path_extractor",
    "tuned_json_extract_once": "extract_tuned_json_paths",
    "simdjson_proxy_manual": "simdjson parse + selected fields",
    "orjson_full_then_select": "orjson decode + selected paths",
    "msgspec_full_then_select": "msgspec decode + selected paths",
    "typed_ndjson_path_extractor": "make_ndjson_typed_path_extractor",
    "typed_ndjson_extract_once": "extract_ndjson_typed_paths",
    "tuned_ndjson_path_extractor": "make_tuned_ndjson_path_extractor",
    "tuned_ndjson_extract_once": "extract_tuned_ndjson_paths",
    "generic_ndjson_path_extractor": "make_ndjson_path_extractor",
    "generic_ndjson_extract_once": "extract_ndjson_paths",
    "native_ndjson_path_extractor": "make_ndjson_path_extractor_native",
    "native_ndjson_extract_once": "extract_ndjson_paths_native",
}


def _is_project_result(name: str) -> bool:
    return name.startswith(_PROJECT_RESULT_PREFIXES)


def _label(name: str) -> str:
    return _RESULT_LABELS.get(name, name.replace("_", " "))


def _workload_caption(section: dict[str, Any]) -> str:
    iterations = section.get("iterations", "?")
    workload = section.get("workload", "Benchmark workload")
    return f"{workload} · {iterations} iterations · total process CPU time · lower is better"


def render_chart(snapshot: dict[str, Any], section_name: str, title: str) -> str:
    """Render every result for a workload; timing values come only from snapshot."""
    section = next(
        (item for item in snapshot.get("sections", []) if item.get("section") == section_name),
        None,
    )
    results = sorted(
        section.get("results", []) if section else [],
        key=lambda item: (float(item["seconds"]), str(item["name"])),
    )

    width = 1160
    label_x = 36
    bar_x = 390
    bar_max = 600
    value_x = bar_x + bar_max + 18
    header_height = 112
    row_height = 34
    footer_height = 28
    height = header_height + max(len(results), 1) * row_height + footer_height
    escaped_title = html.escape(title)
    caption = html.escape(_workload_caption(section or {}))
    description = html.escape(
        f"{title}. Horizontal bars show total process CPU time across each benchmark batch. "
        "All benchmark results are included and lower is better."
    )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-description">',
        f"  <title id=\"chart-title\">{escaped_title}</title>",
        f"  <desc id=\"chart-description\">{description}</desc>",
        f'  <rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'  <text x="{label_x}" y="40" fill="#17202b" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="22" font-weight="700">{escaped_title}</text>',
        f'  <text x="{label_x}" y="67" fill="#44505e" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="14">{caption}</text>',
        '  <rect x="36" y="83" width="13" height="13" rx="2" fill="#315fc5"/>',
        '  <text x="56" y="94" fill="#344052" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">streaming-json-parser API</text>',
        '  <rect x="247" y="83" width="13" height="13" rx="2" fill="#98a3b1"/>',
        '  <text x="267" y="94" fill="#344052" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">alternative</text>',
    ]

    if not results:
        lines.append(
            f'  <text x="{label_x}" y="{header_height + 22}" fill="#44505e" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="14">No benchmark results recorded for this workload.</text>'
        )
    else:
        maximum = max(float(result["seconds"]) for result in results) or 1.0
        for index, result in enumerate(results):
            name = str(result["name"])
            seconds = float(result["seconds"])
            y = header_height + index * row_height
            bar_width = max(2.0, bar_max * seconds / maximum)
            color = "#315fc5" if _is_project_result(name) else "#98a3b1"
            weight = "600" if _is_project_result(name) else "400"
            label = html.escape(_label(name))
            duration = f"{seconds * 1000:,.2f} ms"
            lines.extend(
                [
                    f'  <text x="{label_x}" y="{y + 21}" fill="#253142" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="13" font-weight="{weight}">{label}</text>',
                    f'  <rect x="{bar_x}" y="{y + 7}" width="{bar_max}" height="18" rx="4" fill="#edf0f4"/>',
                    f'  <rect x="{bar_x}" y="{y + 7}" width="{bar_width:.2f}" height="18" rx="4" fill="{color}"/>',
                    f'  <text x="{value_x}" y="{y + 21}" fill="#253142" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="13" font-variant-numeric="tabular-nums">{duration}</text>',
                ]
            )

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_benchmark_charts(
    snapshot: dict[str, Any], output_dir: Path
) -> dict[str, tuple[Path, str]]:
    """Return stable chart paths and SVG source for the supplied snapshot."""
    destination = output_dir / "assets" / "benchmarks"
    return {
        f"chart:{section_name}": (
            destination / filename,
            render_chart(snapshot, section_name, title),
        )
        for section_name, filename, title in CHARTS
    }
