/** Filesystem layout + helpers for agent-run streaming logs.
 *
 *  Each run gets its own dir under <repo>/eval_results/_runs/<run_id>/:
 *
 *    stdout.log    appended-only output from the spawned `python main.py`
 *                  (stdout + stderr merged)
 *    status.json   {status, ticker, date, started_at, finished_at?, exit_code?}
 *
 *  status.status moves running → done | error → done as the child closes.
 *  Both the trigger route (writer) and the logs SSE route (reader) speak to
 *  this single source of truth — no in-process state needed, so the dashboard
 *  survives reloads and parallel clients can each tail the same run.
 */

import path from "node:path"
import { promises as fs } from "node:fs"

export type RunStatus = "running" | "done" | "error"

export type RunStatusFile = {
  status: RunStatus
  ticker: string
  date: string
  started_at: string
  finished_at?: string
  exit_code?: number | null
}

const REPO_ROOT = path.resolve(process.cwd(), "..")
export const RUNS_ROOT = path.join(REPO_ROOT, "eval_results", "_runs")

export function runDir(runId: string): string {
  // Defensive: keep runId path-safe. We mint it ourselves (UUID v4), but the
  // log route accepts it back from the URL so this also guards against
  // crafted requests.
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(runId)) {
    throw new Error(`invalid run id: ${runId}`)
  }
  return path.join(RUNS_ROOT, runId)
}

export function logPath(runId: string): string {
  return path.join(runDir(runId), "stdout.log")
}

export function statusPath(runId: string): string {
  return path.join(runDir(runId), "status.json")
}

export async function readStatus(runId: string): Promise<RunStatusFile | null> {
  try {
    const raw = await fs.readFile(statusPath(runId), "utf-8")
    return JSON.parse(raw) as RunStatusFile
  } catch {
    return null
  }
}

export async function writeStatus(runId: string, status: RunStatusFile): Promise<void> {
  await fs.mkdir(runDir(runId), { recursive: true })
  // Write to a tmp sibling then rename so concurrent readers never see a
  // half-written JSON. The status file is small enough that this overhead
  // doesn't matter.
  const tmp = statusPath(runId) + ".tmp"
  await fs.writeFile(tmp, JSON.stringify(status, null, 2), "utf-8")
  await fs.rename(tmp, statusPath(runId))
}
