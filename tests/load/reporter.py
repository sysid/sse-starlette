"""
Report generation for load test results.

Produces JSON and HTML reports with inline SVG charts.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .baseline import ComparisonResult
    from .metrics import (
        LatencyStats,
        MemoryStats,
        ReliabilityStats,
        TestReport,
        ThroughputStats,
    )


class ReportGenerator:
    """Generates JSON and HTML reports from test results."""

    def __init__(self, output_dir: Path | str = "tests/load/results"):
        self.output_dir = Path(output_dir)

    def _report_path(self, test_name: str, ext: str) -> Path:
        """Get path to report file."""
        safe_name = test_name.replace("::", "_").replace("/", "_").replace("\\", "_")
        return self.output_dir / f"{safe_name}.{ext}"

    def save_json(self, report: TestReport) -> Path:
        """Save report as JSON."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self._report_path(report.test_name, "json")

        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        return path

    def save_html(
        self, report: TestReport, comparison: ComparisonResult | None = None
    ) -> Path:
        """Save report as HTML with inline SVG charts."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self._report_path(report.test_name, "html")

        html_content = self._render_html(report, comparison)
        with open(path, "w") as f:
            f.write(html_content)

        return path

    def print_summary(
        self, report: TestReport, comparison: ComparisonResult | None = None
    ) -> None:
        """Print summary to console."""
        sep = "=" * 70
        print(f"\n{sep}")
        print(f"  SSE Load Test Results: {report.test_name}")
        print(sep)
        print(
            f"Run:     {report.timestamp} | commit: {report.git_commit} | "
            f"branch: {report.git_branch}"
        )
        print(
            f"Scale:   {report.scale} connections | Duration: {report.duration_minutes} min"
        )
        print()

        # Latency
        if report.latency:
            print("LATENCY (inter-event)")
            self._print_latency_line(
                "  p50:", report.latency.p50_ms, comparison, "latency_p50"
            )
            print(f"  p95:   {report.latency.p95_ms:.1f} ms")
            self._print_latency_line(
                "  p99:", report.latency.p99_ms, comparison, "latency_p99"
            )
            print(f"  max:   {report.latency.max_ms:.1f} ms")
            print()

        # TTFE
        if report.ttfe:
            print("TIME TO FIRST EVENT")
            print(f"  p50:   {report.ttfe.p50_ms:.1f} ms")
            self._print_latency_line(
                "  p99:", report.ttfe.p99_ms, comparison, "ttfe_p99"
            )
            print()

        # Throughput
        if report.throughput:
            print("THROUGHPUT")
            self._print_throughput_line(
                report.throughput.aggregate_events_per_sec, comparison
            )
            print(
                f"  Per client: {report.throughput.per_client_events_per_sec:.1f} events/sec"
            )
            print()

        # Memory
        if report.memory:
            print("MEMORY")
            print(f"  Baseline:  {report.memory.baseline_mb:.1f} MB")
            print(f"  Peak:      {report.memory.peak_mb:.1f} MB")
            self._print_memory_line(
                "  Growth:", report.memory.growth_mb, comparison, "memory_growth"
            )
            self._print_slope_line(report.memory.slope_mb_per_sec)
            print()

        # Reliability
        if report.reliability:
            total = (
                report.reliability.successful_connections
                + report.reliability.failed_connections
            )
            pct = (
                report.reliability.successful_connections / total * 100
                if total > 0
                else 0
            )
            print("RELIABILITY")
            print(
                f"  Successful: {report.reliability.successful_connections}/{total} ({pct:.1f}%)"
            )
            if report.reliability.errors:
                print(f"  Errors:     {len(report.reliability.errors)}")
            print()

        # Comparison summary
        if comparison and (comparison.regression_reasons or comparison.warnings):
            if comparison.regression_detected:
                print("REGRESSIONS DETECTED:")
                for reason in comparison.regression_reasons or []:
                    print(f"  - {reason}")
            if comparison.warnings:
                print("WARNINGS:")
                for warning in comparison.warnings:
                    print(f"  - {warning}")
            print()

        print(sep)
        result = "PASS"
        if comparison and comparison.regression_detected:
            result = "FAIL (regression detected)"
        elif comparison and comparison.warnings:
            result = f"PASS ({len(comparison.warnings)} warnings)"
        print(f"Result: {result}")
        print(sep + "\n")

    def _print_latency_line(
        self,
        label: str,
        value: float,
        comparison: ComparisonResult | None,
        key: str,
    ) -> None:
        """Print latency line with optional comparison."""
        line = f"{label}   {value:.1f} ms"
        if comparison:
            change = getattr(comparison, f"{key}_change_pct", None)
            if change is not None:
                symbol = "+" if change > 0 else ""
                indicator = "!" if abs(change) > 20 else ""
                line += f"  ({symbol}{change:.1f}% vs baseline) {indicator}"
        print(line)

    def _print_throughput_line(
        self, value: float, comparison: ComparisonResult | None
    ) -> None:
        """Print throughput line with optional comparison."""
        line = f"  Aggregate:  {value:,.0f} events/sec"
        if comparison and comparison.throughput_change_pct is not None:
            change = comparison.throughput_change_pct
            symbol = "+" if change > 0 else ""
            indicator = "!" if change < -20 else ""
            line += f"  ({symbol}{change:.1f}% vs baseline) {indicator}"
        print(line)

    def _print_memory_line(
        self,
        label: str,
        value: float,
        comparison: ComparisonResult | None,
        key: str,
    ) -> None:
        """Print memory line with optional comparison."""
        line = f"{label}    {value:.1f} MB"
        if comparison:
            change = getattr(comparison, f"{key}_change_pct", None)
            if change is not None:
                symbol = "+" if change > 0 else ""
                indicator = "!" if change > 50 else ""
                line += f"  ({symbol}{change:.1f}% vs baseline) {indicator}"
        print(line)

    def _print_slope_line(self, slope: float) -> None:
        """Print memory slope line."""
        indicator = "!" if slope > 0.1 else ""
        print(f"  Slope:     {slope:.3f} MB/sec {indicator}")

    def _render_html(
        self, report: TestReport, comparison: ComparisonResult | None
    ) -> str:
        """Render full HTML report."""
        charts_html = ""

        # Latency histogram
        if report.latency:
            charts_html += self._render_section(
                "Latency Distribution",
                self._render_latency_summary(report.latency, comparison),
            )

        # TTFE stats
        if report.ttfe:
            charts_html += self._render_section(
                "Time to First Event",
                self._render_ttfe_summary(report.ttfe, comparison),
            )

        # Memory chart
        if report.memory and report.memory.samples:
            charts_html += self._render_section(
                "Memory Usage Over Time",
                self._render_memory_chart(report.memory)
                + self._render_memory_summary(report.memory, comparison),
            )

        # Throughput
        if report.throughput:
            charts_html += self._render_section(
                "Throughput",
                self._render_throughput_summary(report.throughput, comparison),
            )

        # Reliability
        if report.reliability:
            charts_html += self._render_section(
                "Reliability",
                self._render_reliability_summary(report.reliability),
            )

        # Comparison
        comparison_html = ""
        if comparison and (comparison.regression_reasons or comparison.warnings):
            comparison_html = self._render_comparison_section(comparison)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Load Test Report: {html.escape(report.test_name)}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: #1a1a2e;
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .header h1 {{
            margin: 0 0 10px 0;
            font-size: 1.5em;
        }}
        .metadata {{
            color: #aaa;
            font-size: 0.9em;
        }}
        .section {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            margin-top: 0;
            color: #333;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }}
        .chart-container {{
            margin: 20px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            text-align: left;
            padding: 8px 12px;
            border-bottom: 1px solid #eee;
        }}
        th {{
            color: #666;
            font-weight: 500;
        }}
        .value {{
            font-family: 'SF Mono', Monaco, monospace;
            font-weight: 600;
        }}
        .change {{
            font-size: 0.85em;
            color: #666;
        }}
        .change.positive {{ color: #e74c3c; }}
        .change.negative {{ color: #27ae60; }}
        .regression {{
            background: #fee;
            border-left: 4px solid #e74c3c;
            padding: 15px;
            margin: 10px 0;
        }}
        .warning {{
            background: #fff8e1;
            border-left: 4px solid #f9a825;
            padding: 15px;
            margin: 10px 0;
        }}
        svg {{
            max-width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{html.escape(report.test_name)}</h1>
        <div class="metadata">
            <span>Timestamp: {html.escape(report.timestamp)}</span> |
            <span>Commit: {html.escape(report.git_commit)}</span> |
            <span>Branch: {html.escape(report.git_branch)}</span><br>
            <span>Scale: {report.scale} connections</span> |
            <span>Duration: {report.duration_minutes} min</span>
        </div>
    </div>

    {comparison_html}
    {charts_html}
</body>
</html>
"""

    def _render_section(self, title: str, content: str) -> str:
        """Render a section with title."""
        return f"""
    <div class="section">
        <h2>{html.escape(title)}</h2>
        {content}
    </div>
"""

    def _render_latency_summary(
        self, stats: LatencyStats, comparison: ComparisonResult | None
    ) -> str:
        """Render latency summary table."""
        p99_change = ""
        if comparison and comparison.latency_p99_change_pct is not None:
            cls = "positive" if comparison.latency_p99_change_pct > 0 else "negative"
            sign = "+" if comparison.latency_p99_change_pct > 0 else ""
            p99_change = (
                f'<span class="change {cls}">'
                f"({sign}{comparison.latency_p99_change_pct:.1f}%)</span>"
            )

        return f"""
        <table>
            <tr><th>Percentile</th><th>Value</th></tr>
            <tr><td>p50</td><td class="value">{stats.p50_ms:.2f} ms</td></tr>
            <tr><td>p90</td><td class="value">{stats.p90_ms:.2f} ms</td></tr>
            <tr><td>p95</td><td class="value">{stats.p95_ms:.2f} ms</td></tr>
            <tr><td>p99</td><td class="value">{stats.p99_ms:.2f} ms {p99_change}</td></tr>
            <tr><td>max</td><td class="value">{stats.max_ms:.2f} ms</td></tr>
            <tr><td>mean</td><td class="value">{stats.mean_ms:.2f} ms</td></tr>
            <tr><td>stdev</td><td class="value">{stats.stdev_ms:.2f} ms</td></tr>
            <tr><td>samples</td><td class="value">{stats.sample_count:,}</td></tr>
        </table>
"""

    def _render_ttfe_summary(
        self, stats: LatencyStats, comparison: ComparisonResult | None
    ) -> str:
        """Render TTFE summary table."""
        p99_change = ""
        if comparison and comparison.ttfe_p99_change_pct is not None:
            cls = "positive" if comparison.ttfe_p99_change_pct > 0 else "negative"
            sign = "+" if comparison.ttfe_p99_change_pct > 0 else ""
            p99_change = (
                f'<span class="change {cls}">'
                f"({sign}{comparison.ttfe_p99_change_pct:.1f}%)</span>"
            )

        return f"""
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>p50</td><td class="value">{stats.p50_ms:.1f} ms</td></tr>
            <tr><td>p99</td><td class="value">{stats.p99_ms:.1f} ms {p99_change}</td></tr>
            <tr><td>max</td><td class="value">{stats.max_ms:.1f} ms</td></tr>
            <tr><td>samples</td><td class="value">{stats.sample_count:,}</td></tr>
        </table>
"""

    def _render_memory_chart(self, memory: MemoryStats) -> str:
        """Render SVG line chart for memory over time."""
        if not memory.samples:
            return ""

        # Chart dimensions
        width = 600
        height = 200
        padding = 40

        times = [s[0] for s in memory.samples]
        values = [s[1] for s in memory.samples]

        if not times or len(times) < 2:
            return ""

        x_min, x_max = min(times), max(times)
        y_min = min(values) * 0.9
        y_max = max(values) * 1.1

        def scale_x(t: float) -> float:
            if x_max == x_min:
                return padding
            return padding + (t - x_min) / (x_max - x_min) * (width - 2 * padding)

        def scale_y(v: float) -> float:
            if y_max == y_min:
                return height - padding
            return (
                height
                - padding
                - (v - y_min) / (y_max - y_min) * (height - 2 * padding)
            )

        # Generate path
        points = [f"{scale_x(t):.1f},{scale_y(v):.1f}" for t, v in memory.samples]
        path_d = "M " + " L ".join(points)

        # Generate axis labels
        y_labels = ""
        for i in range(5):
            y_val = y_min + (y_max - y_min) * i / 4
            y_pos = scale_y(y_val)
            y_labels += f'<text x="{padding - 5}" y="{y_pos}" text-anchor="end" font-size="10">{y_val:.0f}</text>'

        x_labels = ""
        for i in range(5):
            x_val = x_min + (x_max - x_min) * i / 4
            x_pos = scale_x(x_val)
            x_labels += f'<text x="{x_pos}" y="{height - padding + 15}" text-anchor="middle" font-size="10">{x_val:.0f}s</text>'

        return f"""
        <div class="chart-container">
            <svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
                <!-- Grid -->
                <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{height - padding}"
                      stroke="#ddd" stroke-width="1"/>
                <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}"
                      stroke="#ddd" stroke-width="1"/>

                <!-- Y axis label -->
                <text x="15" y="{height / 2}" text-anchor="middle" font-size="11"
                      transform="rotate(-90 15 {height / 2})">Memory (MB)</text>

                <!-- Axis labels -->
                {y_labels}
                {x_labels}

                <!-- Data line -->
                <path d="{path_d}" fill="none" stroke="#3498db" stroke-width="2"/>

                <!-- Baseline reference -->
                <line x1="{padding}" y1="{scale_y(memory.baseline_mb)}"
                      x2="{width - padding}" y2="{scale_y(memory.baseline_mb)}"
                      stroke="#27ae60" stroke-width="1" stroke-dasharray="5,5"/>
            </svg>
        </div>
"""

    def _render_memory_summary(
        self, memory: MemoryStats, comparison: ComparisonResult | None
    ) -> str:
        """Render memory summary table."""
        growth_change = ""
        if comparison and comparison.memory_growth_change_pct is not None:
            cls = "positive" if comparison.memory_growth_change_pct > 0 else "negative"
            sign = "+" if comparison.memory_growth_change_pct > 0 else ""
            growth_change = (
                f'<span class="change {cls}">'
                f"({sign}{comparison.memory_growth_change_pct:.1f}%)</span>"
            )

        return f"""
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Baseline</td><td class="value">{memory.baseline_mb:.1f} MB</td></tr>
            <tr><td>Peak</td><td class="value">{memory.peak_mb:.1f} MB</td></tr>
            <tr><td>Final</td><td class="value">{memory.final_mb:.1f} MB</td></tr>
            <tr><td>Growth</td><td class="value">{memory.growth_mb:.1f} MB {growth_change}</td></tr>
            <tr><td>Slope</td><td class="value">{memory.slope_mb_per_sec:.4f} MB/sec</td></tr>
        </table>
"""

    def _render_throughput_summary(
        self, throughput: "ThroughputStats", comparison: ComparisonResult | None
    ) -> str:
        """Render throughput summary table."""
        from .metrics import ThroughputStats

        if not isinstance(throughput, ThroughputStats):
            return ""

        change = ""
        if comparison and comparison.throughput_change_pct is not None:
            cls = "negative" if comparison.throughput_change_pct < 0 else "positive"
            sign = "+" if comparison.throughput_change_pct > 0 else ""
            change = (
                f'<span class="change {cls}">'
                f"({sign}{comparison.throughput_change_pct:.1f}%)</span>"
            )

        return f"""
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Aggregate</td><td class="value">{throughput.aggregate_events_per_sec:,.0f} events/sec {change}</td></tr>
            <tr><td>Per Client</td><td class="value">{throughput.per_client_events_per_sec:.1f} events/sec</td></tr>
            <tr><td>Total Events</td><td class="value">{throughput.total_events:,}</td></tr>
            <tr><td>Duration</td><td class="value">{throughput.total_duration_sec:.1f} sec</td></tr>
            <tr><td>Clients</td><td class="value">{throughput.client_count:,}</td></tr>
        </table>
"""

    def _render_reliability_summary(self, reliability: "ReliabilityStats") -> str:
        """Render reliability summary."""
        from .metrics import ReliabilityStats

        if not isinstance(reliability, ReliabilityStats):
            return ""

        total = reliability.successful_connections + reliability.failed_connections
        pct = reliability.successful_connections / total * 100 if total > 0 else 0

        errors_html = ""
        if reliability.errors:
            error_items = "".join(
                f"<li>{html.escape(e)}</li>" for e in reliability.errors[:10]
            )
            errors_html = f"<ul>{error_items}</ul>"

        return f"""
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Successful</td><td class="value">{reliability.successful_connections:,} / {total:,} ({pct:.1f}%)</td></tr>
            <tr><td>Failed</td><td class="value">{reliability.failed_connections:,}</td></tr>
            <tr><td>Error Rate</td><td class="value">{reliability.error_rate * 100:.2f}%</td></tr>
        </table>
        {errors_html}
"""

    def _render_comparison_section(self, comparison: ComparisonResult) -> str:
        """Render comparison alerts section."""
        content = ""

        if comparison.regression_reasons:
            reasons = "".join(
                f"<li>{html.escape(r)}</li>" for r in comparison.regression_reasons
            )
            content += f"""
    <div class="regression">
        <strong>Regressions Detected</strong>
        <ul>{reasons}</ul>
    </div>
"""

        if comparison.warnings:
            warnings = "".join(
                f"<li>{html.escape(w)}</li>" for w in comparison.warnings
            )
            content += f"""
    <div class="warning">
        <strong>Warnings</strong>
        <ul>{warnings}</ul>
    </div>
"""

        if comparison.baseline_commit:
            content += f"""
    <div class="section" style="padding: 10px;">
        <small>Compared against baseline: {html.escape(comparison.baseline_commit)}
        ({html.escape(comparison.baseline_timestamp or 'unknown')})</small>
    </div>
"""

        return content
