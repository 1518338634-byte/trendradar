import { createServer } from "node:http";
import { readFile, writeFile, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const dockerDir = path.join(rootDir, "docker");
const configDir = path.join(rootDir, "config");
const outputDir = path.join(rootDir, "output");
const envPath = path.join(dockerDir, ".env");
const frequencyPath = path.join(configDir, "frequency_words.txt");
const configPath = path.join(configDir, "config.yaml");
const timelinePath = path.join(configDir, "timeline.yaml");
const reportPath = path.join(outputDir, "index.html");
const port = Number(process.env.CONTROL_PANEL_PORT || 8092);

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload, null, 2);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(body);
}

function sendText(res, status, body, type = "text/plain; charset=utf-8") {
  res.writeHead(status, { "content-type": type, "cache-control": "no-store" });
  res.end(body);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function parseEnv(text) {
  const data = {};
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (match) data[match[1]] = match[2];
  }
  return data;
}

function mask(value) {
  if (!value) return "";
  if (value.length <= 12) return "已配置";
  return `${value.slice(0, 8)}...${value.slice(-4)}`;
}

async function getStatus() {
  const [envText, configText, timelineText, frequencyText] = await Promise.all([
    readFile(envPath, "utf8"),
    readFile(configPath, "utf8"),
    readFile(timelinePath, "utf8"),
    readFile(frequencyPath, "utf8"),
  ]);
  const env = parseEnv(envText);
  const reportStat = existsSync(reportPath) ? await stat(reportPath) : null;
  const preset = configText.match(/^\s*preset:\s*"([^"]+)"/m)?.[1] || "unknown";
  const customIndex = timelineText.search(/^custom:/m);
  const customTimeline = customIndex >= 0 ? timelineText.slice(customIndex) : timelineText;
  const scheduleWindow = customTimeline.match(/evening_summary:[\s\S]*?start:\s*"([^"]+)"[\s\S]*?end:\s*"([^"]+)"/);

  return {
    reportUrl: `http://localhost:${env.WEBSERVER_PORT || "8080"}/`,
    reportUpdatedAt: reportStat ? reportStat.mtime.toISOString() : null,
    webPort: env.WEBSERVER_PORT || "8080",
    schedulePreset: preset,
    pushWindow: scheduleWindow ? `${scheduleWindow[1]}-${scheduleWindow[2]}` : "未识别",
    cronSchedule: env.CRON_SCHEDULE || "",
    immediateRun: env.IMMEDIATE_RUN || "",
    feishuConfigured: Boolean(env.FEISHU_WEBHOOK_URL),
    aiEnabled: env.AI_ANALYSIS_ENABLED === "true",
    aiModel: env.AI_MODEL || "",
    aiKey: mask(env.AI_API_KEY || ""),
    keywordGroups: extractKeywordGroups(frequencyText),
  };
}

function extractKeywordGroups(text) {
  const groups = [];
  let current = null;
  let inWordGroups = false;

  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed === "[WORD_GROUPS]") {
      inWordGroups = true;
      continue;
    }
    if (!inWordGroups || !trimmed || trimmed.startsWith("#")) continue;
    const header = trimmed.match(/^\[(.+)]$/);
    if (header) {
      current = { name: header[1], keywords: [] };
      groups.push(current);
      continue;
    }
    if (current && !trimmed.startsWith("@")) current.keywords.push(trimmed);
  }

  return groups.slice(-30);
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || rootDir,
      env: process.env,
      shell: false,
    });
    let output = "";
    const append = (chunk) => {
      output += chunk.toString();
      if (output.length > 20000) output = output.slice(-20000);
    };
    child.stdout.on("data", append);
    child.stderr.on("data", append);
    child.on("error", (error) => resolve({ ok: false, code: -1, output: error.message }));
    child.on("close", (code) => resolve({ ok: code === 0, code, output }));
  });
}

async function appendKeywordGroup(input) {
  const name = String(input.name || "").trim();
  const keywords = String(input.keywords || "")
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const limit = Number(input.limit || 0);

  if (!name) throw new Error("需要填写监控名称");
  if (!keywords.length) throw new Error("至少填写一个关键词");

  const block = [
    "",
    "",
    `[${name}]`,
    ...keywords,
    Number.isFinite(limit) && limit > 0 ? `@${Math.floor(limit)}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const original = await readFile(frequencyPath, "utf8");
  await writeFile(frequencyPath, `${original.trimEnd()}${block}\n`, "utf8");
  return { name, keywords, limit: limit > 0 ? Math.floor(limit) : null };
}

async function handleApi(req, res, pathname) {
  try {
    if (req.method === "GET" && pathname === "/api/status") {
      sendJson(res, 200, await getStatus());
      return;
    }

    if (req.method === "POST" && pathname === "/api/run") {
      const result = await runCommand("docker", ["exec", "trendradar", "python", "manage.py", "run"]);
      sendJson(res, result.ok ? 200 : 500, {
        ok: result.ok,
        message: result.ok ? "抓取完成，报告已更新。" : "抓取失败，请检查 Docker 是否运行。",
        output: result.output,
      });
      return;
    }

    if (req.method === "POST" && pathname === "/api/restart") {
      const down = await runCommand("docker", ["compose", "down"], { cwd: dockerDir });
      const up = await runCommand("docker", ["compose", "up", "-d", "trendradar"], { cwd: dockerDir });
      sendJson(res, down.ok && up.ok ? 200 : 500, {
        ok: down.ok && up.ok,
        output: `${down.output}\n${up.output}`.trim(),
      });
      return;
    }

    if (req.method === "POST" && pathname === "/api/keywords") {
      const created = await appendKeywordGroup(await readBody(req));
      sendJson(res, 200, { ok: true, created });
      return;
    }

    sendJson(res, 404, { ok: false, message: "Not found" });
  } catch (error) {
    sendJson(res, 500, { ok: false, message: error.message });
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  if (url.pathname.startsWith("/api/")) {
    await handleApi(req, res, url.pathname);
    return;
  }
  if (url.pathname === "/" || url.pathname === "/index.html") {
    sendText(res, 200, await readFile(path.join(__dirname, "index.html"), "utf8"), "text/html; charset=utf-8");
    return;
  }
  sendJson(res, 404, { ok: false, message: "Not found" });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`TrendRadar control panel: http://localhost:${port}`);
});
