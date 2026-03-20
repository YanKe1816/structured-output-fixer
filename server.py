#!/usr/bin/env python3
"""structured-output-fixer MCP-compatible task app."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

APP_NAME = "structured-output-fixer"
APP_VERSION = "1.0.0"
SUPPORT_EMAIL = "sidcraigau@gmail.com"
TOOL_NAME = "fix_structured_output"


def _json_error(code: int, message: str, error_type: str = "invalid_request") -> Dict[str, Any]:
    return {"code": code, "message": message, "data": {"type": error_type}}


def _result_template(status: str, data: Optional[Dict[str, Any]], repair_actions: List[str], notes: List[str], missing_fields: List[str]) -> Dict[str, Any]:
    return {
        "ok": True,
        "status": status,
        "data": data,
        "missing_fields": missing_fields,
        "repair_actions": repair_actions,
        "notes": notes,
    }


def _strip_bom(text: str) -> Tuple[str, bool]:
    if text.startswith("\ufeff"):
        return text[1:], True
    return text, False


def _strip_code_fences(text: str) -> Tuple[str, bool]:
    stripped = text.strip()
    pattern = re.compile(r"^```(?:json)?\s*([\s\S]*?)\s*```$", re.IGNORECASE)
    match = pattern.match(stripped)
    if match:
        return match.group(1).strip(), True
    return text, False


def _extract_balanced_json_object(text: str) -> Tuple[Optional[str], bool]:
    start = text.find("{")
    if start == -1:
        return None, False

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1], not (start == 0 and idx == len(text) - 1)

    return None, False


def _remove_trailing_commas(text: str) -> Tuple[str, bool]:
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    return fixed, fixed != text


def _safe_single_to_double_quotes(text: str) -> Tuple[str, bool]:
    converted = text
    converted = re.sub(r"(?<!\\)'([A-Za-z0-9_\-]+)'\s*:", r'"\1":', converted)
    converted = re.sub(r":\s*'([^'\\]*(?:\\.[^'\\]*)*)'", r': "\1"', converted)
    return converted, converted != text


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def fix_structured_output(input_text: str, required_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    required_fields = list(dict.fromkeys([field for field in (required_fields or []) if isinstance(field, str)]))
    repair_actions: List[str] = []
    notes: List[str] = []

    text, removed_bom = _strip_bom(input_text)
    if removed_bom:
        repair_actions.append("removed_bom")

    trimmed = text.strip()
    if trimmed != text:
        repair_actions.append("trimmed_whitespace")
    text = trimmed

    text, fences_removed = _strip_code_fences(text)
    if fences_removed:
        repair_actions.append("stripped_code_fences")

    parsed = _parse_json_object(text)

    if parsed is None:
        extracted, had_wrapper = _extract_balanced_json_object(text)
        if extracted is not None:
            text = extracted
            if had_wrapper:
                repair_actions.append("extracted_first_balanced_object")
            parsed = _parse_json_object(text)

    if parsed is None:
        changed = False
        text2, did_quotes = _safe_single_to_double_quotes(text)
        if did_quotes:
            repair_actions.append("converted_safe_single_quotes")
            changed = True
        text = text2

        text2, did_trailing = _remove_trailing_commas(text)
        if did_trailing:
            repair_actions.append("removed_trailing_commas")
            changed = True
        text = text2

        if changed:
            parsed = _parse_json_object(text)

    if parsed is None:
        notes.append("Input could not be safely repaired into a top-level JSON object.")
        return _result_template("cannot_fix", None, repair_actions, notes, [])

    status = "already_valid" if len(repair_actions) == 0 else "fixed"

    missing_fields: List[str] = []
    for field in required_fields:
        if isinstance(field, str) and field not in parsed:
            parsed[field] = None
            missing_fields.append(field)

    if missing_fields:
        repair_actions.append("added_missing_required_fields_as_null")

    notes.append("Minimal deterministic repair only. No inferred values were added.")

    return _result_template(status, parsed, repair_actions, notes, missing_fields)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_text(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        self._send_text(code, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _json_rpc_error(self, rpc_id: Any, code: int, message: str, error_type: str = "invalid_request") -> None:
        self._send_json(
            200,
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": _json_error(code, message, error_type),
            },
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path == "/health":
            self._send_json(200, {"status": "ok", "app": APP_NAME, "version": APP_VERSION})
            return
        if path == "/privacy":
            self._send_text(
                200,
                'Privacy Policy\n\nThis service ("structured-output-fixer") processes user-provided text inputs to repair and normalize structured JSON outputs.\n\nData Usage:\n- We only process the input text provided in each request.\n- No personal data is intentionally collected.\n- No data is stored after processing.\n- No tracking, logging, or analytics are performed.\n\nData Retention:\n- All processing is ephemeral.\n- No request data is persisted on the server.\n\nThird Parties:\n- This service does not share data with any third parties.\n\nContact:\nIf you have any questions, please contact:\nsidcraigau@gmail.com',
            )
            return
        if path == "/terms":
            self._send_text(
                200,
                'Terms of Service\n\nThis service ("structured-output-fixer") is provided for structured JSON repair only.\n\nUsage Rules:\n- Use this service at your own risk.\n- Do not rely on this service for legal, medical, financial, or safety-critical decisions.\n- The service performs minimal deterministic repair only.\n- The service does not infer, invent, or guarantee factual correctness of input content.\n\nAvailability:\n- Service may change, be updated, or be discontinued at any time without notice.\n\nLiability:\n- The provider is not responsible for any loss, damage, or downstream issues resulting from use of this service.\n\nContact:\nFor support or questions:\nsidcraigau@gmail.com',
            )
            return
        if path == "/support":
            self._send_text(
                200,
                "Support\n\nService: structured-output-fixer\nContact: sidcraigau@gmail.com\n\nFor help, bug reports, or policy questions, please email the address above.",
            )
            return
        if path == "/.well-known/openai-apps-challenge":
            self._send_text(200, "Dy8xICL5HRlpX9tCyBSxP9ibVWweh4c_9WROpp-y2BQ")
            return
        if path == "/mcp":
            manifest = {
                "name": APP_NAME,
                "version": APP_VERSION,
                "description": "Repair unstable AI output into stable structured JSON for downstream systems.",
                "tools": [
                    {
                        "name": TOOL_NAME,
                        "description": "Repairs unstable AI output into stable JSON object format with minimal deterministic fixes.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "input_text": {"type": "string", "description": "Raw AI output."},
                                "required_fields": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "default": [],
                                    "description": "Top-level required fields.",
                                },
                            },
                            "required": ["input_text"],
                            "additionalProperties": False,
                        },
                        "outputShape": {
                            "ok": "boolean",
                            "status": "string",
                            "data": "object|null",
                            "missing_fields": "array",
                            "repair_actions": "array",
                            "notes": "array",
                        },
                    }
                ],
            }
            self._send_json(200, manifest)
            return

        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/mcp":
            self._send_json(404, {"error": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)

        try:
            request = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json_rpc_error(None, -32700, "Parse error", "parse_error")
            return

        if not isinstance(request, dict):
            self._json_rpc_error(None, -32600, "Invalid Request", "invalid_request")
            return

        rpc_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            self._json_rpc_error(rpc_id, -32600, "Invalid Request", "invalid_request")
            return

        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": APP_NAME, "version": APP_VERSION},
                "capabilities": {"tools": {"listChanged": False}},
            }
            self._send_json(200, {"jsonrpc": "2.0", "id": rpc_id, "result": result})
            return

        if method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": TOOL_NAME,
                        "description": "Repairs unstable AI output into stable JSON object format with minimal deterministic fixes.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "input_text": {
                                    "type": "string",
                                    "description": "Raw AI output. May be valid JSON, broken JSON, markdown-wrapped JSON, or messy text.",
                                },
                                "required_fields": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of field names that must exist at the top level in the final JSON object.",
                                    "default": [],
                                },
                            },
                            "required": ["input_text"],
                            "additionalProperties": False,
                        },
                    }
                ]
            }
            self._send_json(200, {"jsonrpc": "2.0", "id": rpc_id, "result": result})
            return

        if method == "tools/call":
            if not isinstance(params, dict):
                self._json_rpc_error(rpc_id, -32602, "Invalid params", "invalid_params")
                return
            name = params.get("name")
            arguments = params.get("arguments", {})

            if name != TOOL_NAME:
                self._json_rpc_error(rpc_id, -32602, "Unknown tool", "invalid_params")
                return
            if not isinstance(arguments, dict):
                self._json_rpc_error(rpc_id, -32602, "Invalid arguments", "invalid_params")
                return
            if "input_text" not in arguments or not isinstance(arguments.get("input_text"), str):
                self._json_rpc_error(rpc_id, -32602, "input_text must be a string", "invalid_params")
                return

            required_fields = arguments.get("required_fields", [])
            if required_fields is None:
                required_fields = []
            if not isinstance(required_fields, list) or not all(isinstance(i, str) for i in required_fields):
                self._json_rpc_error(rpc_id, -32602, "required_fields must be an array of strings", "invalid_params")
                return

            output = fix_structured_output(arguments["input_text"], required_fields)
            self._send_json(200, {"jsonrpc": "2.0", "id": rpc_id, "result": {"structuredContent": output}})
            return

        self._json_rpc_error(rpc_id, -32601, "Method not found", "method_not_found")


def run() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"{APP_NAME} listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
