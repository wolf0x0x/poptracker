# poptracker 产品执行步骤

## 已直接实现

1. 数据检索词典

- 为每个核心 SKU 增加 `search_string`。
- 查询词包含 Pop Mart、IP、系列、款式关键词。
- 内置负面词过滤：`box only`、`card only`、`preorder`、`custom`、`fake`、`replica`。

2. FMV 估值算法

- API 返回成交列表后先做标题噪声过滤。
- 使用 IQR 清洗极端成交。
- 再剔除最高 10% 和最低 10% 后取中位数，生成 `fairMarketValue`。
- 前端单款刷新也使用同样的 10% trimmed median，而不是平均值。

3. 缓存与价格时间序列

- 每次脚本运行会把当天 FMV 追加进 `priceHistory`。
- 每个 SKU 最多保留 90 天价格点。
- 输出 `refreshTier` 与 `refreshIntervalHours`，用于区分高热产品每日刷新、长尾产品每 7 天刷新。

4. 前端商业化与 SEO

- 详情页动态注入 `Product` JSON-LD Schema。
- 价格使用当前 FMV。
- 增加动态 CTA：`Find Deals on eBay (~$xx.xx)`。
- CTA 链接基于 SKU 的精准检索词生成。

5. H5 操作体验

- 保留移动端资产网格、隐藏款动效、API 本地配置和行情刷新。
- 详情页显示估值方法说明。

## 需要人工完成

1. API 与密钥

- 在 GitHub Actions Secret 中配置 `SOLDCOMPS_API_KEY`。
- 如接口不是默认 Apify actor，配置 `SOLDCOMPS_ENDPOINT`。
- 在 H5 演示设备上，可通过右上角 API 设置面板手动写入 Token。

2. 商品数据库扩充

- 整理首批 50 个核心 SKU。
- 为每个 SKU 补充：
  - 标准中文名 / 英文名
  - IP
  - 系列
  - 官方价
  - `search_string`
  - `negative_keywords`
  - 是否隐藏款 / 是否高热款
  - 商品图片 URL

3. Affiliate 商业化

- 将 `affiliateUrl` 替换为真实 eBay Partner Network 链接。
- 替换页面里的 AdSense 占位 ID：
  - `ca-pub-XXXXXXXXXXXXXXXX`
  - `YYYYYYYYYY`
  - `ZZZZZZZZZZ`
  - `WWWWWWWWWW`

4. SEO 与上线

- 在 GitHub Pages 或独立域名启用 HTTPS。
- 提交 Google Search Console。
- 生成并提交 sitemap。
- 用 Rich Results Test 检查 Product Schema。

5. 用户运营

- 心愿单、价格提醒、邮件/机器人推送需要后端账号系统。
- 若要自动发送 Price Drop Alert，需要接入邮件服务或社区机器人。

## 下一阶段建议

1. 第 1-2 周：扩充 50 个核心 SKU，人工打磨搜索词和负面词。
2. 第 3-4 周：上线独立商品详情页、sitemap、Product Schema 批量生成。
3. 第 5 周：接入真实 Affiliate 参数、AdSense ID 和基础流量分析。
4. 第 6 周以后：接入 Supabase 或轻量后端，做心愿单、价格提醒和行情订阅。
