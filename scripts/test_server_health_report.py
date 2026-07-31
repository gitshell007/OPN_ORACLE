from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from server_health_report import (
    add_variations,
    format_bytes,
    parse_human_size,
    percentage_change,
    render_html,
    render_text,
)


SCRIPT = Path(__file__).with_name("server_health_report.py")


def payload(*, disk_free: int, memory_available: int, database: int, tasks: int) -> dict:
    return {
        "hostname": "fake-host",
        "os": "Fake Linux",
        "cpu_count": 2,
        "load_1m": 0.1,
        "memory": {"available_bytes": memory_available},
        "disk": {"free_bytes": disk_free, "total_bytes": 1000, "used_bytes": 100},
        "services": {"fake.service": "active"},
        "database": {"databases": [{"name": "fake", "size_bytes": database}], "errors": []},
        "tasks": {"rows": [{"source": "fake_jobs", "status": "succeeded", "kind": "unit", "count": tasks}], "errors": []},
        "snapshots": [],
        "docker": None,
        "errors": [],
    }


class ServerHealthReportTest(unittest.TestCase):
    def test_percentage_and_byte_format(self) -> None:
        self.assertEqual(percentage_change(120, 100), 20.0)
        self.assertEqual(percentage_change(80, 100), -20.0)
        self.assertIsNone(percentage_change(10, 0))
        self.assertEqual(format_bytes(1_000_000), "1.00 MB")
        self.assertEqual(parse_human_size("25.05GB"), 25_050_000_000)

    def test_docker_and_snapshot_details_are_present_in_report(self) -> None:
        capture = {
            "id": "oracle",
            "label": "Oracle",
            "host": "oracle.example.invalid",
            "status": "ok",
            "data": {
                "os": "Linux",
                "cpu_count": 2,
                "load_1m": 0.2,
                "memory": {"available_bytes": 200},
                "disk": {"free_bytes": 100},
                "database": {"databases": [], "errors": []},
                "tasks": {"rows": [], "errors": []},
                "docker": {"containers": [{"name": "api"}], "errors": [], "summary": [
                    {"type": "Images", "size": "25.05GB", "reclaimable": "24.09GB (96%)"},
                    {"type": "Build cache", "size": "25.14GB", "reclaimable": "24.28GB (96%)"},
                ]},
                "snapshots": [{"path": "/var/backups/opn-oracle", "total_bytes": 235_000_000}],
                "errors": [],
            },
        }
        add_variations(capture, None)
        text = render_text({"captured_at_local": "2026-07-31 12:00 CEST", "targets": [capture]})
        self.assertIn("Docker: Images: 25.05GB", text)
        self.assertIn("Build cache: 25.14GB", text)
        self.assertIn("Snapshot /var/backups/opn-oracle", text)

    def test_second_capture_contains_variation_against_first_capture(self) -> None:
        first = payload(disk_free=100, memory_available=200, database=1_000, tasks=4)
        second = payload(disk_free=80, memory_available=220, database=1_200, tasks=6)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text('#!/bin/sh\ncat "$FAKE_SSH_OUTPUT"\n', encoding="utf-8")
            fake_ssh.chmod(stat.S_IRWXU)
            config = root / "monitor.toml"
            state = root / "state.json"
            config.write_text(
                f"""[monitor]
state_file = "{state}"
ssh_user = "root"
ssh_known_hosts_file = "/dev/null"
recipients = ["info@example.invalid"]

[[targets]]
id = "fake"
label = "Fake"
host = "fake.example.invalid"
db_mode = "none"
task_mode = "none"
services = []
""",
                encoding="utf-8",
            )
            output_file = root / "output.json"
            output_file.write_text(json.dumps(first) + "\n", encoding="utf-8")
            environment = dict(os.environ)
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            environment["FAKE_SSH_OUTPUT"] = str(output_file)
            command = [sys.executable, str(SCRIPT), "--config", str(config), "--no-send", "--print-json"]
            first_run = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(first_run.returncode, 0, first_run.stderr)
            output_file.write_text(json.dumps(second) + "\n", encoding="utf-8")
            second_run = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(second_run.returncode, 0, second_run.stderr)
            report = json.loads(second_run.stdout)
            variation = report["targets"][0]["variation"]
            self.assertEqual(variation["disk_free_bytes"], -20.0)
            self.assertEqual(variation["memory_available_bytes"], 10.0)
            self.assertEqual(variation["database_total_bytes"], 20.0)
            self.assertEqual(variation["tasks_total"], 50.0)

    def test_openrouter_spend_is_in_summary_detail_and_mobile_html(self) -> None:
        capture = {
            "id": "signal",
            "label": "Signal",
            "host": "signal.example.invalid",
            "status": "ok",
            "data": {
                "os": "Linux",
                "cpu_count": 4,
                "load_1m": 0.2,
                "memory": {"available_bytes": 200},
                "disk": {"free_bytes": 100},
                "database": {"databases": [], "errors": []},
                "tasks": {"rows": [], "errors": []},
                "snapshots": [],
                "docker": None,
                "openrouter_spend": {
                    "provider": "openrouter",
                    "window_hours": 24,
                    "total_usd": 0.055862,
                    "requests": 16,
                    "input_tokens": 74940,
                    "output_tokens": 13352,
                    "error_requests": 0,
                    "missing_cost_requests": 0,
                    "errors": [],
                    "rows": [{
                        "consumer": "OPN Oracle",
                        "model": "google/gemini-2.5-flash",
                        "task": "dossier_situation_summary",
                        "project": "(sin proyecto)",
                        "status": "ok",
                        "requests": 16,
                        "cost_usd": 0.055862,
                        "input_tokens": 74940,
                        "output_tokens": 13352,
                        "missing_cost_requests": 0,
                    }],
                },
                "errors": [],
            },
        }
        add_variations(capture, None)
        report = {"captured_at_local": "2026-07-31 12:00 CEST", "targets": [capture]}
        text = render_text(report)
        rendered = render_html(report)
        self.assertIn("Gasto OpenRouter: 0.0559 USD", text)
        self.assertIn("google/gemini-2.5-flash", text)
        self.assertIn("Gasto de IA", rendered)
        self.assertIn("google/gemini-2.5-flash", rendered)
        self.assertIn("width=device-width", rendered)
        self.assertIn("@media(max-width:620px)", rendered)


if __name__ == "__main__":
    unittest.main()
