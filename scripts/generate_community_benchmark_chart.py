"""Render charts for the adapted TkTech JSON benchmark corpus."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


RESULT_LABELS = {
    "decode_complete_json": "decode_complete_json",
    "reusable_complete_decoder": "Reusable complete decoder",
    "streaming_parser_one_buffer": "StreamingJsonParser.feed (one buffer)",
    "json_loads": "Python json.loads",
    "orjson_loads": "orjson",
    "msgspec_decode": "msgspec",
    "simdjson_loads": "simdjson (Python objects)",
    "yyjson_loads": "yyjson",
    "ujson_loads": "ujson",
    "rapidjson_loads": "python-rapidjson",
}

PROJECT_RESULTS = {
    "decode_complete_json",
    "reusable_complete_decoder",
    "streaming_parser_one_buffer",
}


def _format_bytes(value: int) -> str:
    return f"{value / (1024 * 1024):,.2f} MiB"


def render_community_corpus_chart(snapshot: dict[str, Any]) -> str:
    """Render deterministic per-corpus throughput bars from snapshot values."""
    sections = snapshot.get("sections", [])
    row_height = 24
    section_gap = 22
    section_header = 52
    header_height = 132
    footer_height = 34
    section_heights = [
        section_header + max(len(section.get("results", [])), 1) * row_height + section_gap
        for section in sections
    ]
    width = 1280
    height = header_height + sum(section_heights) + footer_height
    label_x = 36
    bar_x = 390
    bar_max = 720
    value_x = bar_x + bar_max + 16

    title = "TkTech JSON benchmark datasets: complete document loads"
    caption = (
        "Adapted whole-document workload · preloaded Python text · UTF-8 input throughput · higher is better"
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-description">',
        f'  <title id="chart-title">{html.escape(title)}</title>',
        '  <desc id="chart-description">Grouped horizontal bars compare complete JSON document loading throughput across public TkTech JSON benchmark corpus files. Each panel has its own scale. Project APIs are blue and alternative libraries are gray.</desc>',
        '  <rect width="100%" height="100%" fill="#ffffff"/>',
        f'  <text x="{label_x}" y="39" fill="#17202b" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="22" font-weight="700">{html.escape(title)}</text>',
        f'  <text x="{label_x}" y="66" fill="#44505e" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="14">{html.escape(caption)}</text>',
        '  <rect x="36" y="87" width="13" height="13" rx="2" fill="#315fc5"/>',
        '  <text x="56" y="98" fill="#344052" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">streaming-json-parser APIs</text>',
        '  <rect x="258" y="87" width="13" height="13" rx="2" fill="#98a3b1"/>',
        '  <text x="278" y="98" fill="#344052" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12">alternative libraries</text>',
    ]

    y = header_height
    for section, section_height in zip(sections, section_heights):
        name = html.escape(str(section.get("name", "JSON corpus file")))
        size_bytes = int(section.get("payload_size_bytes", 0))
        size_text = _format_bytes(size_bytes)
        lines.append(
            f'  <text x="{label_x}" y="{y + 19}" fill="#17202b" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="15" font-weight="700">{name} · {size_text}</text>'
        )
        results = sorted(
            section.get("results", []),
            key=lambda item: (-float(item["mib_per_second"]), str(item["name"])),
        )
        maximum = max((float(item["mib_per_second"]) for item in results), default=1.0) or 1.0
        for index, result in enumerate(results):
            result_name = str(result["name"])
            throughput = float(result["mib_per_second"])
            row_y = y + section_header + index * row_height
            is_project = result_name in PROJECT_RESULTS
            color = "#315fc5" if is_project else "#98a3b1"
            weight = "600" if is_project else "400"
            label = html.escape(RESULT_LABELS.get(result_name, result_name.replace("_", " ")))
            bar_width = max(2.0, bar_max * throughput / maximum)
            lines.extend(
                [
                    f'  <text x="{label_x}" y="{row_y + 17}" fill="#253142" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12" font-weight="{weight}">{label}</text>',
                    f'  <rect x="{bar_x}" y="{row_y + 3}" width="{bar_max}" height="16" rx="4" fill="#edf0f4"/>',
                    f'  <rect x="{bar_x}" y="{row_y + 3}" width="{bar_width:.2f}" height="16" rx="4" fill="{color}"/>',
                    f'  <text x="{value_x}" y="{row_y + 17}" fill="#253142" font-family="system-ui, -apple-system, Segoe UI, sans-serif" font-size="12" font-variant-numeric="tabular-nums">{throughput:,.1f} MiB/s</text>',
                ]
            )
        y += section_height

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def community_corpus_chart_path(output_dir: Path) -> Path:
    return output_dir / "assets" / "benchmarks" / "community-json-corpus-throughput.svg"
