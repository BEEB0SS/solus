"""
Arduino Flasher — compile and upload sketches via arduino-cli.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path


class ArduinoFlasher:
    def __init__(self):
        self.sketch_dir = Path.home() / ".solus" / "sketches"

    def is_available(self) -> bool:
        return shutil.which("arduino-cli") is not None

    def list_boards(self) -> list[dict]:
        if not self.is_available():
            return []
        try:
            result = subprocess_run(
                ["arduino-cli", "board", "list", "--format", "json"],
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    return data
                return data.get("detected_ports", data.get("boards", []))
        except Exception as e:
            print(f"[flasher] list_boards error: {e}")
        return []

    def save_sketch(self, name: str, code: str) -> Path:
        sketch_path = self.sketch_dir / name
        sketch_path.mkdir(parents=True, exist_ok=True)
        ino_path = sketch_path / f"{name}.ino"
        ino_path.write_text(code)
        print(f"[flasher] saved sketch to {ino_path}")
        return ino_path

    async def compile_and_upload(self, name: str, code: str,
                                  port: str = "", fqbn: str = "arduino:avr:uno") -> dict:
        if not self.is_available():
            return {"success": False, "stage": "check", "output": "", "errors": "arduino-cli not found"}

        # Auto-detect port if not specified
        if not port:
            port = self._auto_detect_port()
            if not port:
                return {"success": False, "stage": "detect", "output": "", "errors": "No Arduino port detected"}

        ino_path = self.save_sketch(name, code)
        sketch_dir = str(ino_path.parent)

        # Compile
        try:
            proc = await asyncio.create_subprocess_exec(
                "arduino-cli", "compile", "--fqbn", fqbn, sketch_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            compile_output = stdout.decode("utf-8", errors="replace")
            compile_errors = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                return {
                    "success": False,
                    "stage": "compile",
                    "output": compile_output,
                    "errors": compile_errors,
                }
            print(f"[flasher] compiled {name}")
        except Exception as e:
            return {"success": False, "stage": "compile", "output": "", "errors": str(e)}

        # Upload
        try:
            proc = await asyncio.create_subprocess_exec(
                "arduino-cli", "upload", "--fqbn", fqbn, "--port", port, sketch_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            upload_output = stdout.decode("utf-8", errors="replace")
            upload_errors = stderr.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                return {
                    "success": False,
                    "stage": "upload",
                    "output": compile_output + "\n" + upload_output,
                    "errors": upload_errors,
                }
            print(f"[flasher] uploaded {name} to {port}")
        except Exception as e:
            return {"success": False, "stage": "upload", "output": compile_output, "errors": str(e)}

        return {
            "success": True,
            "stage": "done",
            "output": compile_output + "\n" + upload_output,
            "errors": "",
        }

    def _auto_detect_port(self) -> str:
        from .live_bench import LiveBench
        ports = LiveBench.list_serial_ports()
        for p in ports:
            if p.get("is_arduino"):
                return p["port"]
        if ports:
            return ports[0]["port"]
        return ""


def subprocess_run(cmd: list) -> "subprocess.CompletedProcess":
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
