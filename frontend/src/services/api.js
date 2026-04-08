export async function createRun(payload) {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `create run failed: ${response.status}`);
  }

  return response.json();
}

export async function stopRun(runId) {
  const response = await fetch(`/api/runs/${runId}/stop`, { method: "POST" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `stop run failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRunResult(runId) {
  const response = await fetch(`/api/runs/${runId}/result`);
  if (!response.ok) {
    return null;
  }
  return response.json();
}
