# structured-output-fixer

## What this node does
`structured-output-fixer` is a single-purpose MCP task node that repairs unstable AI-generated structured output into a stable, parseable top-level JSON object for downstream systems.

## Pipeline position
This node sits **after AI generation** and **before downstream system consumption**.

## Tool name
- `fix_structured_output`

## Input contract
Tool input schema:

```json
{
  "type": "object",
  "properties": {
    "input_text": {
      "type": "string",
      "description": "Raw AI output. May be valid JSON, broken JSON, markdown-wrapped JSON, or messy text."
    },
    "required_fields": {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of field names that must exist at the top level in the final JSON object.",
      "default": []
    }
  },
  "required": ["input_text"],
  "additionalProperties": false
}
```

## Output contract
The tool always returns `structuredContent` with this shape:

```json
{
  "ok": true,
  "status": "fixed" | "already_valid" | "cannot_fix",
  "data": "object|null",
  "missing_fields": ["string"],
  "repair_actions": ["string"],
  "notes": ["string"]
}
```

## Deterministic behavior
- No guessing
- No invented values
- Top-level object only
- Minimal repair only
- No external calls, storage, tracking, or side effects

## Required environment variable
- `OPENAI_APPS_CHALLENGE` (used by `GET /.well-known/openai-apps-challenge`)

## Run locally
```bash
python3 server.py
```

Optional port override:
```bash
PORT=8000 python3 server.py
```

## Render deploy steps
1. Push this repository to GitHub.
2. In Render, create a new **Web Service** from the repo.
3. Runtime: **Python 3**.
4. Build command: *(leave empty)*.
5. Start command:
   ```bash
   python3 server.py
   ```
6. Add environment variable:
   - `OPENAI_APPS_CHALLENGE=<your_challenge_value>`
7. Deploy.

## curl examples
### /health
```bash
curl -s http://localhost:8000/health
```

### initialize
```bash
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

### tools/list
```bash
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

### tools/call
```bash
curl -s http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"fix_structured_output",
      "arguments":{
        "input_text":"```json\\n{\\"a\\":1,}\\n```",
        "required_fields":["a","b"]
      }
    }
  }'
```

## Example test inputs
- Valid JSON object:
  - `{"event":"ok","count":1}`
- JSON with trailing comma:
  - `{"event":"ok",}`
- Markdown fenced JSON:
  - ```` ```json
    {"event":"ok"}
    ``` ````
- Plain text that cannot be fixed:
  - `hello this is not json`
- Object missing required fields:
  - Input `{"name":"alice"}` with `required_fields=["name","id"]`

## Add in ChatGPT / developer mode
1. Deploy the service (Render or equivalent HTTPS host).
2. Confirm these endpoints are reachable:
   - `GET /mcp`
   - `POST /mcp`
   - `GET /.well-known/openai-apps-challenge`
3. Register the MCP server URL in ChatGPT developer mode.
4. Verify one tool is listed: `fix_structured_output`.
5. Call tool with raw model output and consume returned `structuredContent` only.

## Limitations
- No guessing or semantic inference.
- Accepts only top-level JSON object as success.
- Performs only minimal deterministic repair.
- If safe repair is not possible, returns `cannot_fix` with `data: null`.
