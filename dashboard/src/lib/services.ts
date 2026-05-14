/** Auto-orchestration for the trend_news FastAPI server.
 *
 *  The trade-agent's `get_news` tool reaches `http://localhost:8000` for
 *  Vietnamese-market news. Rather than make the user `bash trend_news/
 *  start-http.sh` in a separate terminal, the dashboard probes the server
 *  on-demand and spawns uvicorn if it's down.
 *
 *  State lives in eval_results/_runs/_services/trend_news.{log,pid,json}.
 *  The pid file lets a subsequent /api/services/status call reuse / check
 *  the existing process; the log file is what the dashboard surfaces if
 *  the user clicks "show service log".
 */

import path from "node:path"
import { promises as fs } from "node:fs"
import { spawn } from "node:child_process"
import { createWriteStream } from "node:fs"

const REPO_ROOT = path.resolve(process.cwd(), "..")
const SERVICES_DIR = path.join(REPO_ROOT, "eval_results", "_runs", "_services")

export type ServiceName = "trend_news"

export type ServiceStatus = {
  name: ServiceName
  state: "up" | "starting" | "down"
  url: string
  pid?: number
  message?: string
  log_path?: string
}

const TREND_NEWS_URL = "http://localhost:8000"
const TREND_NEWS_HEALTH = `${TREND_NEWS_URL}/health`

async function fileExists(p: string): Promise<boolean> {
  try { await fs.access(p); return true } catch { return false }
}

async function probeUrl(url: string, timeoutMs = 1500): Promise<boolean> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: ctl.signal, cache: "no-store" })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(t)
  }
}

async function readPid(pidFile: string): Promise<number | null> {
  try {
    const raw = await fs.readFile(pidFile, "utf-8")
    const pid = parseInt(raw.trim(), 10)
    if (Number.isFinite(pid) && pid > 0) {
      // Verify the pid is still alive — kill(0) throws if not.
      try { process.kill(pid, 0); return pid } catch { return null }
    }
  } catch { /* file missing */ }
  return null
}

/** Probe trend_news; return current status with no side effects. */
export async function getTrendNewsStatus(): Promise<ServiceStatus> {
  const pidFile = path.join(SERVICES_DIR, "trend_news.pid")
  const logFile = path.join(SERVICES_DIR, "trend_news.log")
  const live = await probeUrl(TREND_NEWS_HEALTH)
  const pid = (await readPid(pidFile)) ?? undefined
  return {
    name: "trend_news",
    state: live ? "up" : "down",
    url: TREND_NEWS_URL,
    pid,
    log_path: (await fileExists(logFile)) ? logFile : undefined,
  }
}

/** Ensure trend_news is reachable, spawning uvicorn if needed.
 *  Returns within `waitMs` regardless of outcome — caller decides whether
 *  to proceed with degraded news routing.
 */
export async function ensureTrendNewsRunning(waitMs = 8000): Promise<ServiceStatus> {
  if (await probeUrl(TREND_NEWS_HEALTH)) {
    return getTrendNewsStatus()
  }

  await fs.mkdir(SERVICES_DIR, { recursive: true })
  const pidFile = path.join(SERVICES_DIR, "trend_news.pid")
  const logFile = path.join(SERVICES_DIR, "trend_news.log")

  // Reuse existing pid if process is alive but the health probe was just
  // flaky. We don't want two uvicorns racing for port 8000.
  const existingPid = await readPid(pidFile)
  if (existingPid) {
    // Wait briefly to see if it comes up on its own.
    for (let i = 0; i < Math.ceil(waitMs / 500); i++) {
      await new Promise((r) => setTimeout(r, 500))
      if (await probeUrl(TREND_NEWS_HEALTH)) return getTrendNewsStatus()
    }
    return {
      name: "trend_news",
      state: "starting",
      url: TREND_NEWS_URL,
      pid: existingPid,
      message: "existing process not responding to /health yet",
    }
  }

  // Find a viable Python. trend_news ships its own venv; fall back to the
  // repo-root venv (where uvicorn is also installed for the parent
  // tradingagents project) if trend_news/venv is missing.
  const candidates = [
    path.join(REPO_ROOT, "trend_news", "venv", "bin", "python"),
    path.join(REPO_ROOT, "venv", "bin", "python"),
  ]
  let py: string | null = null
  for (const c of candidates) {
    if (await fileExists(c)) { py = c; break }
  }
  if (!py) {
    return {
      name: "trend_news",
      state: "down",
      url: TREND_NEWS_URL,
      message: "no python venv found (tried trend_news/venv and ./venv)",
    }
  }

  const out = createWriteStream(logFile, { flags: "a" })
  out.write(`\n[services] starting trend_news at ${new Date().toISOString()}\n`)
  out.write(`[services] python=${py}\n`)

  // uvicorn is the entry point used by trend_news's own start-http.sh.
  const child = spawn(
    py,
    ["-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"],
    {
      cwd: path.join(REPO_ROOT, "trend_news"),
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    },
  )
  child.stdout?.pipe(out, { end: false })
  child.stderr?.pipe(out, { end: false })
  child.unref()
  // Best-effort: detach errors don't crash the dashboard.
  child.on("error", (e) => { out.write(`[services] spawn error: ${e.message}\n`) })

  if (child.pid) {
    await fs.writeFile(pidFile, String(child.pid), "utf-8").catch(() => {})
  }

  // Poll /health until up or timeout.
  const deadline = Date.now() + waitMs
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 500))
    if (await probeUrl(TREND_NEWS_HEALTH)) {
      out.write(`[services] trend_news healthy after ${Date.now() - deadline + waitMs}ms\n`)
      return getTrendNewsStatus()
    }
  }
  return {
    name: "trend_news",
    state: "starting",
    url: TREND_NEWS_URL,
    pid: child.pid,
    message: `did not become healthy within ${waitMs}ms (still booting?)`,
    log_path: logFile,
  }
}

/** Forcefully restart trend_news (kill pid → spawn). */
export async function restartTrendNews(): Promise<ServiceStatus> {
  const pidFile = path.join(SERVICES_DIR, "trend_news.pid")
  const pid = await readPid(pidFile)
  if (pid) {
    try { process.kill(pid, "SIGTERM") } catch { /* already gone */ }
    // Give it a moment to release port 8000.
    await new Promise((r) => setTimeout(r, 800))
    await fs.unlink(pidFile).catch(() => {})
  }
  return ensureTrendNewsRunning()
}
