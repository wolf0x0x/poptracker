# poptracker

泡泡玛特潮玩收藏投资与二级市场价格追踪产品。当前版本是一个零构建静态 H5 产品，适合直接部署到 GitHub Pages、Cloudflare Pages、Vercel Static Output 或任何静态托管服务。

GitHub 仓库地址：<https://github.com/wolf0x0x/poptracker>

## 功能

- 首页市场大盘：综合指数、30 日趋势图、SKU 数、样本成交、平均 ROI、热点 IP。
- 实时成交记录：基于最新静态成交样本生成二级市场成交流，点击即可进入单品详情。
- 发现页瀑布流：按 IP、搜索词、ROI、涨幅、成交量和风险筛选热门单品。
- 系列详情页：点击系列潮玩进入 PC 端图文介绍页，包含 Hero、设计理念、角色图鉴、包装发售信息和市场方法说明。
- 单品详情页：展示 FMV、官方价、ROI、风险分、成交走势图、估值方法和 eBay 动态 CTA。
- 二级市场指标：均价、中位数、七日涨跌、成交量、ROI、风险分。
- 动态 SEO：详情页自动注入 `Product Schema`，用于搜索引擎理解成交价区间。
- AdSense：已接入发布者 `ca-pub-8695398658548679`，广告位 slot 需在 AdSense 后台创建后补入。
- 伪纯前端架构：GitHub Actions 每日拉取 SoldComps，前端读取同域 `public/data/*.json`。
- Python 数据生成脚本：多币种折算、IQR 异常值清洗、指标聚合、SoldComps GET 接口兼容、live/demo 数据源标记。

## 产品执行步骤

详见 [docs/product_execution_plan.md](docs/product_execution_plan.md)。

## 本地运行

生成数据：

```bash
python3 scripts/fetch_and_clean.py
```

启动静态服务：

```bash
python3 -m http.server 8080 -d public
```

然后打开：

```text
http://localhost:8080
```

## 官方图片同步

`sku_dictionary.json` 的 `image` 字段是前端图片唯一来源。无图片时保持 `null`，不要写入无法访问的占位 CDN。

尝试从 POP MART 官方搜索接口同步图片：

```bash
python3 scripts/fetch_popmart_images.py
python3 scripts/fetch_and_clean.py
```

脚本会将图片下载到 `public/assets/sku/`，并把字典中的 `image` 回填为 `/assets/sku/<sku>.<ext>`。每次运行都会写入诊断报告：

```text
work/popmart_image_sync_report.json
```

POP MART 官方接口当前有 Cloudflare / 风控会话校验；若命令返回 `HTTP 471`，脚本会保留 `image: null` 并在报告中记录失败原因，避免把无效图片再次写回页面数据。若已通过浏览器开发者工具导出官方搜索或详情 JSON，可使用：

```bash
python3 scripts/fetch_popmart_images.py --manual-json path/to/popmart-response.json
python3 scripts/fetch_and_clean.py
```

### StockX 角色图导入

StockX 白底图适合做潮玩角色图库，但不要依赖手拼固定 URL；若 URL 已失效会直接返回 404。更稳定的自动化路径是用图片搜索 API 找到真实 `contentUrl` 后下载到本地，例如 Bing Image Search API：

```bash
export BING_IMAGE_SEARCH_KEY="your-key"
python3 scripts/search_character_images_bing.py path/to/sku-or-stockx-list.txt
python3 scripts/fetch_and_clean.py
```

脚本会按 `sku_dictionary.json` 中的系列与角色名生成搜索词，图片保存到 `public/assets/characters/`，并写入：

```text
work/bing_character_image_report.json
```

如果已经整理出可访问的 StockX 白底角色图 URL 清单，可运行：

```bash
python3 scripts/import_stockx_character_images.py path/to/stockx-url-list.txt
python3 scripts/fetch_and_clean.py
```

如果在本机或海外服务器已批量下载到 `popmart_stockx_images/`，且文件名为 `SKU_Character.jpg` 这类格式，可复制该目录到项目根目录后运行：

```bash
python3 scripts/import_downloaded_character_images.py popmart_stockx_images
python3 scripts/fetch_and_clean.py
```

## 真实数据接入

生产环境推荐通过环境变量或 GitHub Secret 注入，不要把真实 Token 写入代码仓库。

### GitHub Actions / GitHub Pages 数据生成

在 GitHub 仓库中配置：

- `Settings -> Secrets and variables -> Actions -> Secrets`
- 新建 `SOLDCOMPS_API_KEY`

默认生产接口为：

```text
GET https://api.sold-comps.com/v1/scrape
Authorization: Bearer SOLDCOMPS_API_KEY
```

如果你的 sold-comps 兼容 API 地址不是默认值，可以在：

- `Settings -> Secrets and variables -> Actions -> Variables`
- 新建 `SOLDCOMPS_ENDPOINT`
- 可选新建 `SOLDCOMPS_METHOD`，默认 SoldComps 为 `GET`
- 可选新建 `SOLDCOMPS_COUNT`，默认每个 SKU 拉取 10 条成交记录，降低 429 风险
- 可选新建 `SOLDCOMPS_REQUEST_DELAY`，默认每个 SKU 请求后等待 1.5 秒
- 可选新建 `SOLDCOMPS_MONTHLY_QUOTA`，默认每月最多 50 次请求
- 可选新建 `SOLDCOMPS_DAILY_BUDGET`，默认每天最多 1 次请求
- 可选新建 `SOLDCOMPS_RUN_BUDGET`，默认每次工作流最多 1 次请求

`Daily Pop Mart Price Sync` 会每天定时运行，但默认只更新 1 个 SKU，并把剩余 SKU 继续使用已有缓存数据。脚本会把月度请求量、每日请求量和 SKU 最近同步状态写入 `public/data/sync_state.json`，用于在后续运行中轮询更新 SKU，避免 50 个 SKU 在同一天耗尽 SoldComps 额度。

### 本地脚本 `.env`

复制 `.env.example` 为 `.env`，填入真实 Token：

```bash
cp .env.example .env
```

```text
SOLDCOMPS_API_KEY=your_real_token
```

`.env` 已在 `.gitignore` 中排除，只用于本机运行 `python3 scripts/fetch_and_clean.py`。

生产环境 GitHub Actions 已启用严格模式：

```text
LIVE_DATA_REQUIRED=true
ALLOW_DEMO_DATA=false
```

当 sold-comps 兼容接口失败时，脚本只会保留已有的 `live` JSON 数据；如果本地只有 `demo` 数据或没有旧数据，则工作流失败，避免把 demo 数据伪装成真实行情。
如果月度或每日预算已经用完，脚本不会继续请求 SoldComps；如果接口返回 HTTP 429，脚本会立即停止剩余 SKU 请求，保留已有数据并记录同步状态，避免继续消耗 API 额度。

脚本默认调用 SoldComps 同步接口：

```text
https://api.sold-comps.com/v1/scrape
```

脚本预期接口返回 JSON 数组，或返回带 `results` / `items` 字段的对象。每条记录可以包含：

```json
{
  "soldPrice": 79.99,
  "soldCurrency": "USD",
  "shippingPrice": 5.5,
  "endedAt": "2026-06-11T18:42:00.000Z",
  "source": "eBay completed sales"
}
```

生产数据刷新流向为：

```text
GitHub Actions / 本地脚本 -> 组装简洁关键词（Pop Mart + IP + 系列 + 款式关键词）-> SoldComps /v1/scrape
                         <- 返回成交列表，脚本过滤并计算中位数，写入 public/data/*.json <-
```

正式版前端不暴露手动输入密钥入口，只读取已经生成的静态 JSON。真实密钥仅应放在 GitHub Actions Secret 或本机 `.env`。

## GitHub Pages 部署

1. 推送本仓库到 GitHub：`wolf0x0x/poptracker`。
2. 进入 `Settings -> Pages`。
3. 选择 `Deploy from a branch`。
4. 分支选择 `main`，目录选择 `/public`。
5. 等待 `Daily Pop Mart Price Sync` 每日自动轮询更新；若当天 SoldComps 额度已用完，不要手动触发该工作流。

## 免责声明

本项目用于收藏价格观察和数据产品原型演示，不构成投资建议。潮玩二级市场价格受品相、隐藏款概率、平台手续费、地区供需、真假鉴定、卖家信誉和短期热度影响，交易前请自行核验真实成交记录。
