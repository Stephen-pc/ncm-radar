"""网易云只读接口：搜索、歌曲详情、评论分页。"""
import time

import requests

from .crypto import encrypt

BASE = "https://music.163.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Netease:
    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": BASE + "/",
            "Origin": BASE,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        self.s.get(BASE + "/", timeout=10)

    def _post(self, path: str, payload: dict) -> dict:
        payload.setdefault("csrf_token", "")
        r = self.s.post(BASE + path, data=encrypt(payload), timeout=15)
        r.raise_for_status()
        return r.json()

    def search(self, keyword: str, limit: int = 8) -> list:
        d = self._post("/weapi/search/get?csrf_token=",
                       {"s": keyword, "type": 1, "limit": limit,
                        "offset": 0, "total": True})
        songs = (d.get("result") or {}).get("songs") or []
        out = []
        for s in songs:
            artists = s.get("artists") or s.get("ar") or []
            out.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "artist": "/".join(a.get("name", "") for a in artists),
                "album": (s.get("album") or {}).get("name", ""),
            })
        return out

    def comments_page(self, song_id: int, cursor: str = "", page: int = 1,
                      size: int = 20, order: int = 3):
        rid = f"R_SO_4_{song_id}"
        d = self._post("/weapi/comment/resource/comments/get?csrf_token=", {
            "rid": rid, "threadId": rid, "pageNo": page, "pageSize": size,
            "cursor": cursor, "offset": 0, "orderType": order,
            "sortType": order,
        })
        data = d.get("data") or {}
        return (data.get("comments") or [], data.get("cursor") or "",
                data.get("totalCount"))

    def crawl(self, song_id: int, target: int = 400, order: int = 3,
              on_page=None):
        """用 cursor 往回翻，直到拿够 target 条或没有更多。"""
        seen, out, cursor, total = set(), [], "", None
        page = 0
        while len(out) < target:
            page += 1
            try:
                cs, cursor, total = self.comments_page(
                    song_id, cursor=cursor, page=page, order=order)
            except Exception as exc:
                if on_page:
                    on_page(page, len(out), f"请求失败 {exc}")
                break
            if not cs:
                break
            for c in cs:
                cid = c.get("commentId")
                if cid in seen:
                    continue
                seen.add(cid)
                out.append(c)
            if on_page:
                on_page(page, len(out), None)
            if not cursor:
                break
            time.sleep(self.delay)
        return out[:target], total
