# Vercel 静态报告部署

TrendRadar 的爬虫和定时任务不适合直接跑在 Vercel 上。推荐结构是：

1. GitHub Actions 每天运行 TrendRadar，生成 `output/index.html`。
2. 工作流把最新报告写入 `public/report.html`，并生成 `public/index.html` 控制台。
3. Vercel 部署 `public/` 里的静态页面，同时提供一个安全的触发接口。

## Vercel 项目设置

在 Vercel 导入仓库后使用这些设置：

- Framework Preset: `Other`
- Build Command: `npm run build`
- Output Directory: `public`
- Install Command: `npm install --ignore-scripts`

这些设置已经写入 `vercel.json`，多数情况下 Vercel 会自动识别。

## GitHub Secrets

在 GitHub 仓库中打开：

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

建议添加：

- `FEISHU_WEBHOOK_URL`
- `AI_ANALYSIS_ENABLED`，值为 `true`
- `AI_API_KEY`
- `AI_MODEL`，例如 `deepseek/deepseek-chat`
- `AI_API_BASE`，例如 `https://api.deepseek.com`

其他推送渠道按需添加。

## Vercel 环境变量

如果要使用网页上的“立即生成并推送飞书”按钮，需要在 Vercel 项目中打开：

`Settings` → `Environment Variables`

添加：

- `GITHUB_DISPATCH_TOKEN`

这个值需要是 GitHub token，并且对 `1518338634-byte/trendradar` 仓库有触发 Actions 的权限。建议使用 Fine-grained personal access token，只授权这个仓库，并开启 `Actions: Read and write`、`Contents: Read`。

可选变量：

- `TRENDRADAR_GITHUB_REPOSITORY`，默认 `1518338634-byte/trendradar`
- `TRENDRADAR_WORKFLOW_FILE`，默认 `update-vercel-report.yml`
- `TRENDRADAR_GITHUB_REF`，默认 `master`

这些变量只存在 Vercel 服务端，不会暴露在网页源码里。

## 手动生成第一版报告

第一次部署后，打开 GitHub 仓库：

`Actions` → `Update Vercel Static Report` → `Run workflow`

工作流完成后会提交新的 `public/index.html`，Vercel 会自动重新部署。

也可以打开 Vercel 站点首页，点击“立即生成并推送飞书”。按钮会触发同一个 GitHub Actions 工作流，并强制执行一次通知推送。

## 定时

当前工作流每天北京时间 `20:00` 运行一次：

```yaml
cron: "0 12 * * *"
```

GitHub Actions 使用 UTC 时间，所以 `12:00 UTC = 北京时间 20:00`。
