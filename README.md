# poptracker

泡泡玛特潮玩收藏投资与二级市场价格追踪产品。当前版本是一个零构建静态 MVP，适合直接部署到 GitHub Pages、Cloudflare Pages、Vercel Static Output 或任何静态托管服务。

## 功能

- 泡泡玛特热门 IP 资产矩阵：Labubu、SKULLPANDA、MOLLY、DIMOO、HIRONO。
- 二级市场指标：均价、中位数、七日涨跌、成交量、ROI、波动率、风险分。
- 投资与收藏双视角：收藏视角突出 IP、系列、稀缺属性；投资视角突出成交、风险和溢价。
- 中英文双语界面。
- 搜索、IP 筛选、排序、详情面板、30 日价格走势图。
- Python 数据生成脚本：多币种折算、IQR 异常值清洗、指标聚合、样例数据兜底。
- GitHub Actions 每日自动更新 `public/data/*.json`。

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

在 GitHub 仓库中配置：

- `Settings -> Secrets and variables -> Actions -> Secrets`
- 新建 `SOLDCOMPS_API_KEY`

如果你的 SoldComps 兼容 API 地址不是默认值，可以在：

- `Settings -> Secrets and variables -> Actions -> Variables`
- 新建 `SOLDCOMPS_ENDPOINT`

脚本预期接口返回 JSON 数组，或返回带 `results` 字段的对象。每条记录可以包含：

```json
{
  "soldPrice": 79.99,
  "shippingPrice": 5.5,
  "currency": "USD",
  "soldAt": "2026-06-11",
  "source": "eBay completed sales"
}
```

## GitHub Pages 部署

1. 推送本仓库到 GitHub。
2. 进入 `Settings -> Pages`。
3. 选择 `Deploy from a branch`。
4. 分支选择 `main`，目录选择 `/public`。
5. 手动运行一次 `Daily Pop Mart Price Sync` 工作流，生成最新 JSON。

## 免责声明

本项目用于收藏价格观察和数据产品原型演示，不构成投资建议。潮玩二级市场价格受品相、隐藏款概率、平台手续费、地区供需、真假鉴定、卖家信誉和短期热度影响，交易前请自行核验真实成交记录。
