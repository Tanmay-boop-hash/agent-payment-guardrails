import inspect, json, os, time
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

PROVIDER = "groq"
MODEL_NAME = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
MIN_INTERVAL = float(os.getenv("LLM_MIN_INTERVAL", "4"))   # seconds between calls (client-side throttle)
MODEL = f"{PROVIDER}:{MODEL_NAME}"                         # used in eval cache keys

class DailyQuotaExceeded(Exception):
    pass

class ModelCallFailed(Exception):
    pass

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict

_JSON_TYPES = {str: "string", float: "number", int: "integer", bool: "boolean"}

def tool_schemas(tools: dict) -> list:
    """Build OpenAI-style tool schemas from the Python callables (names, type hints, docstrings)."""
    out = []
    for name, fn in tools.items():
        params = inspect.signature(fn).parameters
        props = {p: {"type": _JSON_TYPES.get(v.annotation, "string")} for p, v in params.items()}
        out.append({"type": "function", "function": {
            "name": name, "description": inspect.getdoc(fn) or "",
            "parameters": {"type": "object", "properties": props, "required": list(props)}}})
    return out

class GroqBackend:
    def __init__(self, tools: dict, system: str | None = None):
        from groq import Groq
        self.client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0, timeout=60)
        self.schemas = tool_schemas(tools)
        self.messages = [{"role": "system", "content": system}] if system else []
        self._last = 0.0

    def start(self, prompt: str):
        self.messages.append({"role": "user", "content": prompt})

    def step(self):
        msg = self._call()
        entry = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls]
        self.messages.append(entry)
        calls = []
        for tc in msg.tool_calls or []:
            raw = tc.function.arguments or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"_unparsed": raw}         # policy blocks it; unguarded tool call errors safely
            calls.append(ToolCall(tc.id, tc.function.name, args))
        return msg.content, calls

    def add_results(self, calls, results):
        for c, r in zip(calls, results):
            self.messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(r)})

    def _call(self, retries=4):
        from groq import APIStatusError, APIConnectionError, RateLimitError
        for attempt in range(retries + 1):
            gap = MIN_INTERVAL - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            t0 = time.monotonic()
            try:
                resp = self.client.chat.completions.create(
                    model=MODEL_NAME, messages=self.messages, tools=self.schemas,
                    tool_choice="auto", temperature=0)
                self._last = time.monotonic()
                tok = getattr(resp.usage, "total_tokens", "?")
                print(f"[model {self._last - t0:.1f}s, {tok} tokens]")
                return resp.choices[0].message
            except RateLimitError as e:
                self._last = time.monotonic()
                text = str(e).lower()
                if "per day" in text or "(tpd)" in text or "(rpd)" in text:
                    raise DailyQuotaExceeded(str(e)) from e
                ra = e.response.headers.get("retry-after")
                wait, err = (float(ra) + 1 if ra else 5 * 2 ** attempt), e
            except APIStatusError as e:
                if e.status_code == 400 and "tool_use_failed" in str(e):
                    raise ModelCallFailed("tool_use_failed") from e
                if e.status_code < 500:
                    raise
                wait, err = 5 * 2 ** attempt, e
            except APIConnectionError as e:
                wait, err = 5 * 2 ** attempt, e
            if attempt == retries:
                raise err
            print(f"[{type(err).__name__}] retry {attempt + 1} in {wait:.0f}s")
            time.sleep(wait)