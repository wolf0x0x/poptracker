# poptracker

泡泡玛特潮玩收藏投资与二级市场价格追踪产品。当前版本是一个零构建静态 H5 产品，适合直接部署到 GitHub Pages、Cloudflare Pages、Vercel Static Output 或任何静态托管服务。

GitHub 仓库地址：<https://github.com/wolf0x0x/poptracker>

## 功能

- 首页市场大盘：综合指数、30 日趋势图、SKU 数、样本成交、平均 ROI、热点 IP。
- 实时成交记录：基于最新静态成交样本生成二级市场成交流，点击即可进入单品详情。
- 发现页瀑布流：按 IP、搜索词、ROI、涨幅、成交量和风险筛选热门单品。
- 单品详情页：展示 FMV、官方价、ROI、风险分、成交走势图、估值方法和 eBay 动态 CTA。
- 二级市场指标：均价、中位数、七日涨跌、成交量、ROI、风险分。
- 动态 SEO：详情页自动注入 `Product Schema`，用于搜索引擎理解成交价区间。
- AdSense 广告位：顶部 Leaderboard、侧栏 300x250、后续可替换真实广告单元。
- API Key 本地配置：`SOLD_COMPS_API_KEY` 仅保存在浏览器 `localStorage`。
- 单款一键刷新：通过 sold-comps.com / Apify completed sales 接口刷新最新成交中位价。
- 伪纯前端架构：GitHub Actions 每日拉取 SoldComps，前端读取同域 `public/data/*.json`。
- Python 数据生成脚本：多币种折算、IQR 异常值清洗、指标聚合、Apify POST 接口兼容、样例数据兜底。

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

## 真实数据接入

生产环境推荐通过环境变量或 GitHub Secret 注入，不要把真实 Token 写入代码仓库。

### GitHub Actions / GitHub Pages 数据生成

在 GitHub 仓库中配置：

- `Settings -> Secrets and variables -> Actions -> Secrets`
- 新建 `SOLDCOMPS_API_KEY`

如果你的 sold-comps / Apify 兼容 API 地址不是默认值，可以在：

- `Settings -> Secrets and variables -> Actions -> Variables`
- 新建 `SOLDCOMPS_ENDPOINT`

### 本地脚本 `.env`

复制 `.env.example` 为 `.env`，填入真实 Token：

```bash
cp .env.example .env
```

```text
SOLDCOMPS_API_KEY=your_real_token
```

`.env` 已在 `.gitignore` 中排除，只用于本机运行 `python3 scripts/fetch_and_clean.py`。

### H5 离线 / 演示模式

前端页面右上角点击 `缺 API` / `API ready` 打开设置面板，填入 `SOLD_COMPS_API_KEY`。该值只写入当前浏览器 `localStorage`，用于当前设备上的单款“刷新市值”。

脚本默认调用 Apify 同步接口：

```text
https://api.apify.com/v2/acts/caffein.dev~ebay-sold-listings/run-sync-get-dataset-items
```

脚本预期接口返回 JSON 数组，或返回带 `results` / `items` 字段的对象。每条记录可以包含：

```json
{
  "soldPrice": 79.99,
  "shippingPrice": 5.5,
  "currency": "USD",
  "soldAt": "2026-06-11",
  "source": "eBay completed sales"
}
```

前端单款刷新请求流向为：

```text
H5 客户端 -> 本地组装 Pop Mart + IP + 系列 + 款式关键词 -> sold-comps / Apify 网关
          <- 返回近 30 天成交列表，本地过滤并计算中位数 <-
```

这适合个人 H5 盘点场景，但生产级多人协作建议改成后端代理，避免在共享设备或录屏环境中暴露 Token。

## GitHub Pages 部署

1. 推送本仓库到 GitHub：`wolf0x0x/poptracker`。
2. 进入 `Settings -> Pages`。
3. 选择 `Deploy from a branch`。
4. 分支选择 `main`，目录选择 `/public`。
5. 手动运行一次 `Daily Pop Mart Price Sync` 工作流，生成最新 JSON。

## 免责声明

本项目用于收藏价格观察和数据产品原型演示，不构成投资建议。潮玩二级市场价格受品相、隐藏款概率、平台手续费、地区供需、真假鉴定、卖家信誉和短期热度影响，交易前请自行核验真实成交记录。
