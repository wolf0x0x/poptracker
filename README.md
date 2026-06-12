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
- 伪纯前端架构：前端读取同域 `public/data/*.json`，市场数据由本地私有 eBay completed-sales 采集流程生成后推送。
- Python 数据生成脚本：多币种折算、IQR 异常值清洗、指标聚合、eBay completed-sales 缓存数据源标记。

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

正式版数据源已切换为 eBay completed-sales 本地缓存流程。抓取程序和浏览器快照只保存在本机 ignored 目录 `outputs/local_ebay/`，不会推送到 GitHub；仓库只发布清洗后的 `public/data/*.json` 静态数据。

生产数据刷新流向为：

```text
本地浏览器自动打开 eBay 已售页面 -> 保存可见成交文本到 outputs/local_ebay/snapshots/
                              -> 本地私有脚本清洗价格、计算 FMV/ROI/趋势
                              -> 只提交 public/data/*.json 到 GitHub Pages
```

正式版前端不暴露任何 API 密钥入口，只读取已经生成的静态 JSON。

## GitHub Pages 部署

1. 推送本仓库到 GitHub：`wolf0x0x/poptracker`。
2. 进入 `Settings -> Pages`。
3. 选择 `Deploy from a branch`。
4. 分支选择 `main`，目录选择 `/public`。
5. 数据更新由本机私有自动化推送 `public/data/*.json` 后触发 Pages 部署。

## 免责声明

本项目用于收藏价格观察和数据产品原型演示，不构成投资建议。潮玩二级市场价格受品相、隐藏款概率、平台手续费、地区供需、真假鉴定、卖家信誉和短期热度影响，交易前请自行核验真实成交记录。
