"""命令行入口：搜索歌曲 → 抓评论 → 出报告。

用法:
    python -m ncm_radar 晴天                 单次分析
    python -m ncm_radar 晴天 --track         分析并加入追踪列表
    python -m ncm_radar --run-all            跑追踪列表里的全部歌曲
    python -m ncm_radar --list               看追踪列表
    python -m ncm_radar --untrack 1330348068 移除
"""

import argparse
import glob
import json
import os
import sys
import time

from . import report, sentiment
from .api import Netease

WATCHLIST = "watchlist.json"


def safe_name(name):
    return "".join(ch for ch in name if ch not in r'\/:*?"<>|').strip()


def load_watchlist():
    if not os.path.exists(WATCHLIST):
        return []
    try:
        with open(WATCHLIST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_watchlist(items):
    with open(WATCHLIST, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def find_prev(out_dir, song_name, today):
    """找这首歌上一次的报告数据（排除今天）。"""
    pattern = os.path.join(out_dir, f"{safe_name(song_name)}_*.json")
    files = [f for f in sorted(glob.glob(pattern)) if today not in os.path.basename(f)]
    if not files:
        return None, None
    try:
        with open(files[-1], encoding="utf-8") as f:
            return json.load(f), os.path.basename(files[-1])
    except Exception:
        return None, None


def pick_song(api, keyword, index):
    songs = api.search(keyword)
    if not songs:
        print(f"没搜到「{keyword}」")
        return None
    if len(songs) == 1 or index is not None:
        s = songs[(index or 1) - 1]
        print(f"选中：{s['name']} - {s['artist']}  (id={s['id']})")
        return s
    print("\n搜索结果：")
    for i, s in enumerate(songs, 1):
        print(f"  [{i}] {s['name']} - {s['artist']}   《{s['album']}》")
    while True:
        raw = input("\n选第几个（回车=1）：").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(songs):
            return songs[int(raw) - 1]
        print("输入不合法，重来")


def analyze(api, song, args, compare=True):
    print(f"\n开始抓取「{song['name']}」，目标 {args.count} 条…")
    t0 = time.time()

    def on_page(page, got, err):
        if err:
            print(f"\r  第 {page} 页出错：{err}", flush=True)
        else:
            print(f"\r  第 {page:>2} 页  已拿到 {got:>4} 条", end="", flush=True)

    raw, total = api.crawl(song["id"], target=args.count, on_page=on_page)
    print(f"\n抓取完成：{len(raw)} 条，耗时 {time.time() - t0:.1f}s，全站 {total or '未知'} 条")

    items = [sentiment.extract(c) for c in raw]
    raw_n = len(items)
    items = [i for i in items if i.get("valid", True)]
    if raw_n != len(items):
        print(f"过滤掉系统占位评论 {raw_n - len(items)} 条")
    if not items:
        print("没有有效评论，跳过")
        return None

    avg = sum(i["score"] for i in items) / len(items)
    print(f"有效评论 {len(items)} 条，平均情绪 {avg:+.2f}")

    os.makedirs(args.out, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    base = os.path.join(args.out, f"{safe_name(song['name'])}_{stamp}")

    prev, prev_file = (None, None)
    if compare:
        prev, prev_file = find_prev(args.out, song["name"], stamp)
        if prev:
            prev_ids = {i["id"] for i in prev.get("items", [])}
            new = [i for i in items if i["id"] not in prev_ids]
            if new:
                new_avg = sum(i["score"] for i in new) / len(new)
                print(f"对比上次（{prev_file}）：新增 {len(new)} 条，新评论情绪 {new_avg:+.2f}")
            else:
                print(f"对比上次（{prev_file}）：没有新增评论")

    with open(base + ".html", "w", encoding="utf-8") as f:
        f.write(report.build(song, items, total, prev=prev, prev_name=prev_file))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"song": song, "total": total,
                   "fetched_at": int(time.time()), "items": items},
                  f, ensure_ascii=False, indent=1)

    print(f"报告：{os.path.abspath(base + '.html')}")
    return base + ".html"


def main():
    ap = argparse.ArgumentParser(description="网易云评论区情绪分析")
    ap.add_argument("keyword", nargs="?", help="歌名或关键词")
    ap.add_argument("--count", type=int, default=400, help="抓取条数，默认 400")
    ap.add_argument("--pick", type=int, default=None, help="直接指定搜索结果序号")
    ap.add_argument("--delay", type=float, default=0.5, help="请求间隔秒，默认 0.5")
    ap.add_argument("--out", default="reports", help="报告输出目录")
    ap.add_argument("--track", action="store_true", help="加入追踪列表")
    ap.add_argument("--run-all", action="store_true", help="跑追踪列表里的全部歌曲")
    ap.add_argument("--list", action="store_true", help="列出追踪列表")
    ap.add_argument("--untrack", metavar="ID", help="从追踪列表移除")
    ap.add_argument("--no-compare", action="store_true", help="不做历史对比")
    args = ap.parse_args()

    if args.list:
        wl = load_watchlist()
        if not wl:
            print("追踪列表是空的。用 --track 添加。")
            return
        print(f"追踪列表（{len(wl)} 首）：")
        for i, s in enumerate(wl, 1):
            print(f"  [{i}] {s['name']} - {s['artist']}  id={s['id']}")
        return

    if args.untrack:
        wl = load_watchlist()
        keep = [s for s in wl if str(s["id"]) != str(args.untrack)]
        save_watchlist(keep)
        print(f"已移除，剩 {len(keep)} 首")
        return

    api = Netease(delay=args.delay)

    if args.run_all:
        wl = load_watchlist()
        if not wl:
            print("追踪列表是空的。先跑一次带 --track 的命令。")
            return
        print(f"开始跑追踪列表，共 {len(wl)} 首\n" + "=" * 50)
        ok = 0
        for i, s in enumerate(wl, 1):
            print(f"\n[{i}/{len(wl)}] {s['name']} - {s['artist']}")
            try:
                if analyze(api, s, args, compare=not args.no_compare):
                    ok += 1
            except Exception as exc:
                print(f"  失败：{exc}")
            if i < len(wl):
                time.sleep(1.5)
        print("\n" + "=" * 50)
        print(f"完成 {ok}/{len(wl)} 首")
        return

    if not args.keyword:
        ap.print_help()
        return

    song = pick_song(api, args.keyword, args.pick)
    if not song:
        sys.exit(1)

    if args.track:
        wl = load_watchlist()
        if not any(str(s["id"]) == str(song["id"]) for s in wl):
            wl.append({"id": song["id"], "name": song["name"],
                       "artist": song["artist"], "album": song.get("album", "")})
            save_watchlist(wl)
            print(f"已加入追踪列表，共 {len(wl)} 首")

    analyze(api, song, args, compare=not args.no_compare)


if __name__ == "__main__":
    main()
