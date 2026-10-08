---
name: industry-heat-bubble-forecast
description: 看行业短热等位图，输出随后若干日的气泡结构场，供系统重绘（非收益预测）
window_trading_days: 40
forecast_trading_days: 5
board_type: industry
output_format: json
model:
  provider:
  base_url:
  model:
  api_key:
---

你是在「看图续气泡」：附图是 A 股行业短热等位图（横轴=行业叶序，纵轴=交易日向上变新，颜色蓝冷红热）。
虚线附近是截止日 {{as_of}}。请只根据图像里的热力气泡形态，推演截止日后这 {{forecast_trading_days}} 个交易日气泡会如何形变。

推演日：{{forecast_dates}}

要求：
1. 先读图：顶端（最近几日）主气泡在左/中/右，是竖脊、团块还是碎斑，正在扩、缩、裂还是漂移。
2. 再续画结构场：不要行业涨跌故事，不要买卖建议；用气泡几何描述后 {{forecast_trading_days}} 日色场。
3. 允许明显形变（漂移、分裂、侧向扩散、旧脊消退、新芽冒出），禁止五日几乎不动的延拓。
4. 坐标系（归一化）：
   - cx：横轴位置，0=最左行业，1=最右行业
   - ct：推演时间条带中心，0=第一个推演日，1=最后一个推演日
   - rx / rt：横轴/时间方向半宽（约 0.03～0.25）
   - peak：峰值热度 0～1（红亮接近 1）
5. 每天可有多个气泡；跨日竖脊用较大的 rt，并把 ct 放在脊的时间中心。

输出严格 JSON（不要 markdown 围栏）：

{
  "thesis": "80字内总判断（结构形变，不是涨跌）",
  "read_image": "一句话读图：顶端气泡位置与形态",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "note": "一句该日气泡变化",
      "blobs": [
        {
          "id": "A",
          "cx": 0.32,
          "ct": 0.25,
          "rx": 0.07,
          "rt": 0.35,
          "peak": 0.9,
          "name_hint": "可选短标签"
        }
      ]
    }
  ]
}

约束：
- days 必须覆盖全部推演日，日期与顺序一致。
- 每个推演日 blobs 至少 1 个、最多 8 个。
- 全体气泡中至少出现一次：分裂或新生芽（新 id），以及一次旧脊 peak 下降或 rt/rx 收缩。
- cx/ct/rx/rt/peak 均为数字；id 用短字母或数字。
