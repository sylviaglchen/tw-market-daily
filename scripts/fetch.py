import json, os, time, urllib.request
from datetime import datetime, timedelta, timezone

TW = timezone(timedelta(hours=8))
INST_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={d}&response=json"
MARGIN_URL = "https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={d}&selectType=MS"
INST_FILE = "data/institutional.json"
MARGIN_FILE = "data/margin.json"
INST_KEYS = {"自營商(自行買賣)": "dealerOwn", "自營商(避險)": "dealerHedge",
             "投信": "trust", "外資及陸資(不含外資自營商)": "foreign"}
MARGIN_KEYS = {"融資(交易單位)": "margin", "融券(交易單位)": "short", "融資金額(仟元)": "amount"}


def num(s):
    return int(str(s).replace(",", "").strip())


def get(url):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("retry:", e)
            time.sleep(5)
    return None


def parse_inst(j):
    if not j or j.get("stat") != "OK":
        return None
    rows = {INST_KEYS[r[0]]: [num(r[1]), num(r[2])] for r in j.get("data", []) if r[0] in INST_KEYS}
    return rows if len(rows) == 4 else None


def parse_margin(j):
    if not j or j.get("stat") != "OK" or not j.get("tables") or not j["tables"][0].get("data"):
        return None
    out = {}
    for r in j["tables"][0]["data"]:
        if r[0] in MARGIN_KEYS:
            out[MARGIN_KEYS[r[0]]] = {"buy": num(r[1]), "sell": num(r[2]), "repay": num(r[3]),
                                      "prev": num(r[4]), "today": num(r[5])}
    return out if len(out) == 3 else None


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"days": []}


def upsert(store, rec):
    days = store["days"]
    for i, d in enumerate(days):
        if d["date"] == rec["date"]:
            if d == rec:
                return False
            days[i] = rec
            return True
    days.append(rec)
    return True


def correct_previous(store, date, new_rec):
    # 證交所隔天的「前日餘額」才是正確數字，用它覆蓋前一天的暫定數字
    older = sorted([d for d in store["days"] if d["date"] < date], key=lambda d: d["date"])
    if not older:
        return
    prev = older[-1]
    if (datetime.fromisoformat(date) - datetime.fromisoformat(prev["date"])).days > 7:
        return
    for k in ("margin", "short", "amount"):
        prev[k]["today"] = new_rec[k]["prev"]
    prev["final"] = True


def save(path, store, changed, now):
    if not changed:
        return
    store["days"].sort(key=lambda d: d["date"], reverse=True)
    store["updated"] = now
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)


def main():
    now = datetime.now(TW)
    n = int(os.environ.get("BACKFILL_DAYS") or 0)
    dates = [(now - timedelta(days=i)).date() for i in range(n, -1, -1)]
    dates = [d for d in dates if d.weekday() < 5]
    inst, margin = load(INST_FILE), load(MARGIN_FILE)
    c1 = c2 = False
    for d in dates:
        ds, iso = d.strftime("%Y%m%d"), d.isoformat()
        rows = parse_inst(get(INST_URL.format(d=ds)))
        if rows:
            c1 |= upsert(inst, {"date": iso, "rows": rows})
        time.sleep(3)
        m = parse_margin(get(MARGIN_URL.format(d=ds)))
        if m:
            rec = {"date": iso, "final": False, **m}
            c2 |= upsert(margin, rec)
            correct_previous(margin, iso, rec)
            c2 = True if n else c2
        time.sleep(3)
    stamp = now.isoformat(timespec="seconds")
    save(INST_FILE, inst, c1, stamp)
    save(MARGIN_FILE, margin, c2, stamp)
    print("institutional changed:", c1, "| margin changed:", c2)


if __name__ == "__main__":
    main()
