export interface StageFrame {
  event_id: string;
  correlation_id: string;
  stage: string;
  phase: string;
  ts: string;
  detail?: Record<string, unknown>;
  error?: string;
}

export async function consumeSse(
  url: string,
  onFrame: (frame: StageFrame) => void,
  onStatus: (status: string) => void,
  signal: AbortSignal,
): Promise<void> {
  try {
    const response = await fetch(url, {
      signal,
      headers: { accept: "text/event-stream" },
    });
    if (!response.ok || !response.body) {
      onStatus(`stream ${response.status}`);
      return;
    }
    onStatus("live");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let event = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (event === "stage" && data) {
          try {
            onFrame(JSON.parse(data) as StageFrame);
          } catch {
            /* ignore */
          }
        }
      }
    }
  } catch (error) {
    if (!signal.aborted) onStatus(`stream error: ${(error as Error).message}`);
  }
}
