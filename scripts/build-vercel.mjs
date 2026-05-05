import { mkdir, copyFile, access } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const outputReport = path.join(root, "output", "index.html");
const publicDir = path.join(root, "public");
const publicReport = path.join(publicDir, "index.html");

await mkdir(publicDir, { recursive: true });

try {
  await access(outputReport);
  await copyFile(outputReport, publicReport);
  console.log("Copied output/index.html to public/index.html");
} catch {
  console.log("No generated report found. Keeping existing public/index.html placeholder.");
}
