export function sessionTitle(runStatus) {
  switch (runStatus) {
    case "FAILED":
      return "Session Failed";
    case "COMPLETED":
      return "Session Completed";
    case "STOPPED":
      return "Session Stopped";
    case "STOPPING":
      return "Session Stopping";
    case "RUNNING":
    case "PENDING":
      return "Session Running";
    default:
      return "Session Idle";
  }
}

export function sessionTone(runStatus) {
  switch (runStatus) {
    case "FAILED":
      return "failed";
    case "COMPLETED":
      return "ok";
    default:
      return "running";
  }
}
