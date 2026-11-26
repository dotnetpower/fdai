"""Private child entrypoint; copied into the read-only sandbox source mount."""

import contextlib
import io
import json
import sys

sys.path.insert(0, "/source")
from fdai_pipeline_client import PipelineClient  # type: ignore[import-not-found]  # noqa: E402


class BoundedText(io.TextIOBase):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data = bytearray()
        self.truncated = False

    def write(self, text: str) -> int:
        encoded = text.encode("utf-8")
        if len(self.data) + len(encoded) > self.limit:
            self.truncated = True
        self.data.extend(encoded[: max(0, self.limit - len(self.data))])
        return len(text)

    def getvalue(self) -> str:
        return self.data.decode("utf-8", errors="ignore")


data = json.load(sys.stdin)
out, err = BoundedText(data["max_stdout"]), BoundedText(data["max_stderr"])
envelope: dict[str, object] = {"ok": False}
try:
    namespace: dict[str, object] = {"__name__": "fdai_reviewed_pipeline"}
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with open("/source/pipeline.py", encoding="utf-8") as source:
            exec(compile(source.read(), "/source/pipeline.py", "exec"), namespace)  # noqa: S102
        main = namespace["main"]
        if not callable(main):
            raise ValueError("pipeline main is not callable")
        result = main(PipelineClient(), tuple(json.loads(x) for x in data["inputs"]))
    final = json.dumps(
        result, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    )
    final_truncated = len(final.encode("utf-8")) > data["max_final"]
    envelope = {
        "ok": True,
        "final_json": None if final_truncated else final,
        "final_truncated": final_truncated,
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
        "stdout_truncated": out.truncated,
        "stderr_truncated": err.truncated,
    }
except Exception:  # noqa: BLE001 - never return child data or exception text on failure
    envelope = {"ok": False}
sys.stdout.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
