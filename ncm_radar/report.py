"""把抓到的评论渲染成一份自包含的 HTML 报告。"""

import html
import re
import time
from collections import Counter, defaultdict

import jieba

from . import sentiment

STOPWORDS = set("""
的 了 是 我 你 他 她 它 们 这 那 就 都 也 还 又 很 太 在 有 和 与 但 却 而
一个 一首 什么 怎么 为什么 因为 所以 如果 就是 不是 没有 可以 自己 时候
现在 已经 一样 这样 那样 这个 那个 我们 你们 他们 真的 感觉 觉得 知道
听 歌 歌曲 音乐 好听 一首歌 这首歌 评论 网易 云 音乐 播放 循环 喜欢
啊 呀 吧 呢 吗 哦 嗯 哈 啦 嘛 的话 一次 一直 还是 只是 然后 其实
首歌 一定 一起 一天 今天 还有 以后 可能 如果 开始 曾经 后来 因为
所以 但是 不过 虽然 即使 无论 总是 终于 突然 接着 于是 之后 之前
不会 不要 这么 那么 多少 几个 东西 事情 地方 时间 世界 生活 人生
""".split())


def _agg(items):
    """按天或按月聚合，并标出异常日。"""
    ts = [it["time"] for it in items]
    span_days = (max(ts) - min(ts)) / 86400000
    fmt = "%Y-%m-%d" if span_days <= 120 else "%Y-%m"

    buckets = defaultdict(lambda: {"n": 0, "s": 0.0})
    dist = Counter()
    for it in items:
        key = time.strftime(fmt, time.localtime(it["time"] / 1000))
        buckets[key]["n"] += 1
        buckets[key]["s"] += it["score"]
        dist[sentiment.label(it["score"])] += 1

    series = [{"m": k, "n": v["n"], "avg": round(v["s"] / v["n"], 3)}
              for k, v in sorted(buckets.items())]

    # 异常检测：评论量或情绪偏离均值超过 2 个标准差
    ns = [s["n"] for s in series]
    avs = [s["avg"] for s in series]
    mean_n = sum(ns) / len(ns)
    mean_a = sum(avs) / len(avs)

    def sd(vals, mu):
        return (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5

    sd_n, sd_a = sd(ns, mean_n), sd(avs, mean_a)
    for s in series:
        s["hot"] = sd_n > 0 and s["n"] > mean_n + 2 * sd_n
        s["shift"] = sd_a > 0 and abs(s["avg"] - mean_a) > 2 * sd_a
    return series, dist, {"fmt": fmt, "mean_n": mean_n, "mean_a": mean_a,
                          "span_days": span_days}


def _keywords(items, top=18):
    counter = Counter()
    for it in items:
        # 表情标签 [爱心] [哭哭] 不该进词频
        text = re.sub(r"\[[^\[\]]{1,8}\]", " ", it["text"])
        for w in jieba.cut(text):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS or w.isdigit():
                continue
            counter[w] += 1
    return counter.most_common(top)


# 评论区常见形态，用高频词反推
SCENES = {
    "许愿墙": ("加油", "考上", "高考", "中考", "考研", "上岸", "成功", "顺利",
             "保佑", "如愿", "目标", "分数", "录取"),
    "怀旧现场": ("青春", "回忆", "那年", "小时候", "以前", "曾经", "学生时代",
               "童年", "初恋", "回到", "记得"),
    "夸赞现场": ("好听", "神仙", "绝了", "循环", "单曲", "宝藏", "封神",
               "惊艳", "嗓音", "编曲"),
    "深夜倾诉": ("深夜", "失眠", "孤独", "一个人", "撑不住", "难受", "眼泪"),
    "打卡现场": ("打卡", "第", "路过", "签到", "考古", "收藏"),
}


def _portrait(words):
    """用高频词反推评论区形态，返回 (名称, 命中词)。"""
    wd = dict(words)
    best, best_hits = None, []
    for name, kws in SCENES.items():
        hits = [(w, wd[w]) for w in kws if wd.get(w)]
        score = sum(c for _, c in hits)
        if score > sum(c for _, c in best_hits):
            best, best_hits = name, hits
    if not best_hits:
        return None, []
    return best, best_hits[:4]


def _compare_block(items, avg, prev, prev_name):
    """与上一次抓取对比：整体情绪变化 + 新增评论的情绪。"""
    if not prev:
        return ""
    p_items = prev.get("items") or []
    if not p_items:
        return ""
    p_avg = sum(i["score"] for i in p_items) / len(p_items)
    p_date = time.strftime("%Y-%m-%d", time.localtime(prev.get("fetched_at", 0)))
    p_ids = {i["id"] for i in p_items}
    new = [i for i in items if i["id"] not in p_ids]

    delta = round(avg - p_avg, 2)
    if delta > 0:
        tone, arrow = "#3fb98a", "↑"
    elif delta < 0:
        tone, arrow = "#e26a6a", "↓"
    else:
        tone, arrow = "#8d8d96", "→"
    delta_txt = f"{delta:+.2f}" if abs(delta) >= 0.01 else "0.00"

    if new:
        new_avg = sum(i["score"] for i in new) / len(new)
        new_tone = "#3fb98a" if new_avg > 0.01 else ("#e26a6a" if new_avg < -0.01 else "#8d8d96")
        new_card = (f'<div class="cmp-c hl"><div class="k">新增评论</div>'
                    f'<div class="v" style="color:{new_tone}">{new_avg:+.2f}</div>'
                    f'<div class="d">{len(new)} 条</div></div>')
        new_note = f"两次抓取之间有 <b>{len(new)}</b> 条新评论，它们的平均情绪是 <b>{new_avg:+.2f}</b>。"
    else:
        new_card = ('<div class="cmp-c hl"><div class="k">新增评论</div>'
                    '<div class="v" style="color:#8d8d96">0</div><div class="d">没有新评论</div></div>')
        new_note = "两次抓取之间没有新评论（或者这次没抓到）。"

    return f"""<h2>与上次相比</h2>
<div class="cmp">
  <div class="cmp-c"><div class="k">上次 · {p_date}</div>
    <div class="v">{p_avg:+.2f}</div><div class="d">{len(p_items)} 条</div></div>
  <div class="cmp-arrow">→</div>
  <div class="cmp-c"><div class="k">本次</div>
    <div class="v" style="color:{tone}">{avg:+.2f}</div><div class="d">{len(items)} 条</div></div>
  {new_card}
</div>
<div class="cmp-note">整体情绪 {arrow} <b style="color:{tone}">{delta_txt}</b>。{new_note}</div>"""


def build(song, items, total_count, order_name="按时间", prev=None, prev_name=None):
    series, dist, meta = _agg(items)
    n = len(items)
    if n == 0:
        raise ValueError("没有可分析的评论")

    avg = round(sum(i["score"] for i in items) / n, 3)
    pos = dist.get("强烈共鸣", 0) + dist.get("正面", 0)
    neg = dist.get("负面", 0) + dist.get("强烈负面", 0)
    neu = dist.get("中性", 0)

    peak = max(series, key=lambda x: x["n"])
    warm = max(series, key=lambda x: x["avg"])
    cold = min(series, key=lambda x: x["avg"])
    hot_days = [s for s in series if s.get("hot")]
    shift_days = [s for s in series if s.get("shift")]
    top_comments = sorted(items, key=lambda x: x["likes"], reverse=True)[:8]
    words = _keywords(items)
    portrait, phits = _portrait(words)

    labels = [s["m"] for s in series]
    counts = [s["n"] for s in series]
    avgs = [s["avg"] for s in series]
    bar_colors = ["#E26A6A" if s.get("hot") else "#7F77DD" for s in series]
    word_max = words[0][1] if words else 1
    unit = "天" if meta["fmt"] == "%Y-%m-%d" else "月"

    if portrait:
        hits_txt = "、".join(f"{w} {c}" for w, c in phits)
        portrait_html = (f'<div class="portrait"><span class="ptag">{portrait}</span>'
                         f'<span class="pdesc">评论区形态 · 依据：{hits_txt}</span></div>')
    else:
        portrait_html = ""

    compare_html = _compare_block(items, avg, prev, prev_name)

    anomaly_html = ""
    if hot_days:
        txt = "、".join(f"{s['m']}（{s['n']} 条）" for s in hot_days[:3])
        ratio = hot_days[0]["n"] / meta["mean_n"]
        anomaly_html += (f"<p>评论量异常高峰：<b>{txt}</b>，是平时（{meta['mean_n']:.0f} 条）的 "
                         f"<b>{ratio:.1f}</b> 倍。这种尖峰通常对应一次事件。</p>")
    if shift_days:
        txt = "、".join(f"{s['m']}（{s['avg']:+.2f}）" for s in shift_days[:3])
        anomaly_html += f"<p>情绪显著偏离整体水平的日子：<b>{txt}</b>。</p>"
    if not anomaly_html:
        anomaly_html = "<p>样本期内没有出现显著异常，评论量和情绪都保持平稳。</p>"

    def esc(x):
        return html.escape(str(x))

    comment_cards = "".join(
        f"""<div class="cm">
          <div class="cm-top"><span class="cm-user">{esc(c['user'])}</span>
          <span class="cm-like">{c['likes']:,} 赞</span></div>
          <p class="cm-text">{esc(c['text'][:180])}</p>
          <div class="cm-meta"><span>{time.strftime('%Y-%m-%d', time.localtime(c['time']/1000))}</span>
          <span class="cm-score s{_tone(c['score'])}">{sentiment.label(c['score'])} {c['score']:+.2f}</span></div>
        </div>"""
        for c in top_comments)

    word_html = "".join(
        f"""<div class="wrow"><span class="wt">{esc(w)}</span>
        <span class="wbar"><i style="width:{max(6, int(c / word_max * 100))}%"></i></span>
        <span class="wc">{c}</span></div>"""
        for w, c in words)

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(song['name'])} · 评论区情绪报告</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#141417;color:#e9e9ec;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
line-height:1.65;padding:40px 20px 80px}}
.wrap{{max-width:960px;margin:0 auto}}
.tag{{display:inline-block;font-size:12px;color:#9a9aa2;border:1px solid #2e2e35;
border-radius:20px;padding:3px 12px;margin-bottom:18px}}
h1{{font-size:26px;font-weight:500;letter-spacing:-.3px;margin-bottom:6px}}
.sub{{color:#8d8d96;font-size:14px;margin-bottom:32px}}
.sub b{{color:#c9c9d1;font-weight:500}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:34px}}
.card{{background:#1c1c21;border-radius:12px;padding:16px 18px}}
.card .k{{font-size:12px;color:#8d8d96;margin-bottom:6px}}
.card .v{{font-size:24px;font-weight:500;letter-spacing:-.5px}}
.card .u{{font-size:12px;color:#71717a;margin-left:3px;font-weight:400}}
h2{{font-size:14px;font-weight:500;color:#b9b9c2;margin:36px 0 14px;
padding-left:10px;border-left:2px solid #7F77DD}}
.chart{{background:#1c1c21;border-radius:12px;padding:20px 18px 12px;height:340px;position:relative}}
.legend{{display:flex;gap:18px;font-size:12px;color:#8d8d96;margin-bottom:12px}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}
.dist{{display:flex;height:34px;border-radius:8px;overflow:hidden;font-size:12px}}
.dist div{{display:flex;align-items:center;justify-content:center;color:#0e0e11;font-weight:500}}
.wrow{{display:flex;align-items:center;gap:10px;margin-bottom:7px;font-size:13px}}
.portrait{{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}}
.cmp{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.cmp-c{{background:#1c1c21;border-radius:12px;padding:14px 18px;min-width:120px;flex:1}}
.cmp-c.hl{{background:#20202a}}
.cmp-c .k{{font-size:12px;color:#8d8d96;margin-bottom:5px}}
.cmp-c .v{{font-size:20px;font-weight:500}}
.cmp-c .d{{font-size:12px;color:#71717a;margin-top:3px}}
.cmp-arrow{{color:#5d5d66;font-size:16px}}
.cmp-note{{font-size:13px;color:#a9a9b2;margin-top:12px;background:#1c1c21;
border-radius:10px;padding:12px 16px}}
.ptag{{background:#2a2a33;color:#c9b6f7;border-radius:6px;padding:4px 12px;
font-size:13px;font-weight:500}}
.pdesc{{font-size:12px;color:#7d7d86}}
.wt{{width:96px;text-align:right;color:#c9c9d1;flex:none;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}}
.wbar{{flex:1;height:8px;background:#232329;border-radius:4px;overflow:hidden}}
.wbar i{{display:block;height:100%;background:#7F77DD;border-radius:4px}}
.wc{{width:34px;color:#71717a;font-size:12px;flex:none}}
.cm{{background:#1c1c21;border-radius:12px;padding:15px 17px;margin-bottom:10px}}
.cm-top{{display:flex;justify-content:space-between;font-size:12px;color:#8d8d96;margin-bottom:8px}}
.cm-user{{color:#a9a9b2}}
.cm-like{{color:#EF9F27}}
.cm-text{{font-size:14px;color:#dcdce2;margin-bottom:10px}}
.cm-meta{{display:flex;justify-content:space-between;font-size:12px;color:#6e6e77}}
.s1{{color:#3fb98a}} .s0{{color:#8d8d96}} .sm{{color:#e26a6a}}
.summary{{background:#1c1c21;border-radius:12px;padding:18px 20px;font-size:14px;color:#c9c9d1}}
.summary p{{margin-bottom:9px}} .summary p:last-child{{margin-bottom:0}}
.summary b{{color:#e9e9ec;font-weight:500}}
.foot{{margin-top:44px;font-size:12px;color:#5d5d66;text-align:center}}
</style></head><body><div class="wrap">
<div class="tag">评论区情绪报告 · {order_name}</div>
<h1>{esc(song['name'])}</h1>
<div class="sub">{esc(song['artist'])}　<b>{esc(song.get('album') or '')}</b>　·　样本 {n:,} 条 / 全站 {total_count or '未知'} 条　·　{time.strftime('%Y-%m-%d %H:%M')}</div>

<div class="cards">
  <div class="card"><div class="k">平均情绪</div><div class="v">{avg:+.2f}</div></div>
  <div class="card"><div class="k">正面占比</div><div class="v">{pos/n*100:.1f}<span class="u">%</span></div></div>
  <div class="card"><div class="k">负面占比</div><div class="v">{neg/n*100:.1f}<span class="u">%</span></div></div>
  <div class="card"><div class="k">时间跨度</div><div class="v" style="font-size:15px">{series[0]['m']} → {series[-1]['m']}</div></div>
</div>

{compare_html}
<h2>情绪构成</h2>
<div class="dist">
  <div style="width:{pos/n*100}%;background:#3fb98a">{pos}</div>
  <div style="width:{neu/n*100}%;background:#3a3a42;color:#a9a9b2">{neu}</div>
  <div style="width:{neg/n*100}%;background:#e26a6a">{neg}</div>
</div>

<h2>评论量与情绪的时间线</h2>
<div class="chart">
  <div class="legend">
    <span><i style="background:#7F77DD"></i>每{unit}评论量</span>
    <span><i style="background:#E26A6A"></i>评论量异常</span>
    <span><i style="background:#EF9F27"></i>平均情绪（右轴）</span>
  </div>
  <canvas id="c"></canvas>
</div>

<h2>高频词</h2>
{portrait_html}
<div>{word_html}</div>

<h2>高赞评论</h2>
{comment_cards}

<h2>结论</h2>
<div class="summary">
  <p>最活跃的{unit}是 <b>{peak['m']}</b>（{peak['n']} 条），情绪最高的是 <b>{warm['m']}</b>（{warm['avg']:+.2f}），
  最低的是 <b>{cold['m']}</b>（{cold['avg']:+.2f}）。</p>
  <p>整体平均情绪 <b>{avg:+.2f}</b>，属于<b>{sentiment.label(avg)}</b>区间，
  正面评论是负面的 <b>{(pos/neg if neg else pos):.1f}</b> 倍。</p>
  {anomaly_html}
</div>

<div class="foot">由 ncm_radar 生成 · 数据来自网易云音乐公开评论区 · 仅用于个人分析</div>
</div>
<script>
new Chart(document.getElementById('c'), {{
  data: {{
    labels: {labels!r},
    datasets: [
      {{type:'bar', label:'评论量', data:{counts!r}, backgroundColor:{bar_colors!r},
        borderRadius:3, barPercentage:0.7, yAxisID:'y'}},
      {{type:'line', label:'平均情绪', data:{avgs!r}, borderColor:'#EF9F27',
        backgroundColor:'rgba(239,159,39,0.10)', borderWidth:2, pointRadius:0,
        tension:0.35, fill:false, yAxisID:'y1'}}
    ]
  }},
  options: {{
    responsive:true, maintainAspectRatio:false,
    plugins:{{legend:{{display:false}}, tooltip:{{mode:'index', intersect:false}}}},
    scales:{{
      x:{{ticks:{{color:'#8d8d96', font:{{size:10}}, maxRotation:45, autoSkip:true}},
         grid:{{display:false}}, border:{{color:'#2e2e35'}}}},
      y:{{position:'left', ticks:{{color:'#8d8d96', font:{{size:10}}}},
         grid:{{color:'rgba(255,255,255,0.05)'}}, border:{{display:false}}}},
      y1:{{position:'right', min:-1, max:1, ticks:{{color:'#EF9F27', font:{{size:10}}}},
         grid:{{display:false}}, border:{{display:false}}}}
    }}
  }}
}});
</script>
</body></html>"""


def _tone(s):
    if s > 0.12:
        return 1
    if s < -0.12:
        return "m"
    return 0
