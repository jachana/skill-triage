#!/usr/bin/env python3
"""
board.py — an offline-first kanban that *optionally* syncs to a remote provider
(Trello, Jira, or others). The point: the project-management skills work the same
whether you have an account or not.

Providers (auto-detected from env, override with PM_PROVIDER):
  local   — pure board.json, no network (default; always available)
  trello  — needs TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID
  jira    — needs JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY

Stdlib only. Creds read from the environment (or a sibling .env); NEVER stored
in board.json. Adding another provider = implement pull()/push() in a class
following the Provider interface below.

Usage:
  python board.py init [--lists "Backlog,To Do,In progress,In review,Done"]
  python board.py show | status
  python board.py add  "Card name" [--list "Backlog"] [--desc "..."]
  python board.py move "Card name" --to "In progress"
  python board.py claim "Card name"          # -> In progress
  python board.py ship  "Card name"          # -> In review
  python board.py pick                         # top "ready" card
  python board.py rm   "Card name"
  python board.py pull                          # remote -> local (remote wins)
  python board.py push                          # local  -> remote
All commands accept --file <path> (default: ./board.json). Spanish flag aliases too.
"""
import argparse, base64, json, os, sys, urllib.parse, urllib.request, urllib.error
from pathlib import Path

DEFAULT_LISTS = ["Backlog", "To Do", "In progress", "In review", "Done"]
CLAIM_LIST, SHIP_LIST = "In progress", "In review"


# ── env / provider selection ───────────────────────────────────────────────
def load_env(start: Path):
    for d in [start, *start.parents]:
        envf = d / ".env"
        if envf.is_file():
            for line in envf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break


def detect_provider():
    p = os.environ.get("PM_PROVIDER", "").strip().lower()
    if p:
        return p
    if all(os.environ.get(k) for k in ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_BOARD_ID")):
        return "trello"
    if all(os.environ.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT_KEY")):
        return "jira"
    return "local"


def _get_json(url, headers=None, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code}: {e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error: {e.reason}. (Work offline — your local board still works.)")


# ── providers ───────────────────────────────────────────────────────────────
class LocalProvider:
    """No remote. pull/push are no-ops with a clear message."""
    name = "local"
    online = False
    def pull(self, board): sys.exit("Provider 'local' has no remote to pull from. (That's fine — keep working offline.)")
    def push(self, board): sys.exit("Provider 'local' has no remote to push to. (Your board.json is the source of truth.)")


class TrelloProvider:
    name = "trello"
    online = True
    API = "https://api.trello.com/1"
    def __init__(self):
        self.key = os.environ["TRELLO_API_KEY"]; self.token = os.environ["TRELLO_TOKEN"]; self.board = os.environ["TRELLO_BOARD_ID"]
    def _req(self, method, path, params=None, data=None):
        params = {**(params or {}), "key": self.key, "token": self.token}
        url = f"{self.API}{path}?{urllib.parse.urlencode(params)}"
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8"); return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            sys.exit(f"Trello API error {e.code}: {e.read().decode('utf-8','replace')}")
        except urllib.error.URLError as e:
            sys.exit(f"Network error talking to Trello: {e.reason}.")
    def pull(self, _):
        lists = self._req("GET", f"/boards/{self.board}/lists", {"cards": "none"})
        id2name = {l["id"]: l["name"] for l in lists}
        cards = self._req("GET", f"/boards/{self.board}/cards", {"fields": "name,desc,idList"})
        return {"lists": [l["name"] for l in lists],
                "cards": [{"name": c["name"], "list": id2name.get(c["idList"], "Backlog"), "desc": c.get("desc", "")} for c in cards]}
    def push(self, board):
        remote_lists = {l["name"]: l["id"] for l in self._req("GET", f"/boards/{self.board}/lists", {"cards": "none"})}
        for lst in board["lists"]:
            if lst not in remote_lists:
                remote_lists[lst] = self._req("POST", "/lists", data={"name": lst, "idBoard": self.board})["id"]
        remote = {c["name"].strip().lower(): c for c in self._req("GET", f"/boards/{self.board}/cards", {"fields": "name,idList"})}
        created = moved = 0
        for c in board["cards"]:
            tid = remote_lists[c["list"]]; ex = remote.get(c["name"].strip().lower())
            if ex:
                if ex["idList"] != tid: self._req("PUT", f"/cards/{ex['id']}", data={"idList": tid}); moved += 1
            else:
                self._req("POST", "/cards", data={"name": c["name"], "desc": c.get("desc", ""), "idList": tid}); created += 1
        return f"{created} created, {moved} moved"


class JiraProvider:
    """Maps a Jira issue's status <-> a board list (by name). Jira Cloud REST v3."""
    name = "jira"
    online = True
    def __init__(self):
        self.base = os.environ["JIRA_BASE_URL"].rstrip("/")
        self.proj = os.environ["JIRA_PROJECT_KEY"]
        tok = base64.b64encode(f'{os.environ["JIRA_EMAIL"]}:{os.environ["JIRA_API_TOKEN"]}'.encode()).decode()
        self.headers = {"Authorization": f"Basic {tok}", "Accept": "application/json"}
    def pull(self, _):
        jql = urllib.parse.quote(f"project={self.proj} ORDER BY rank ASC")
        data = _get_json(f"{self.base}/rest/api/3/search?jql={jql}&fields=summary,status&maxResults=200", self.headers)
        lists, seen, cards = [], set(), []
        for it in data.get("issues", []):
            status = it["fields"]["status"]["name"]
            if status not in seen: seen.add(status); lists.append(status)
            cards.append({"name": it["fields"]["summary"], "list": status, "desc": "", "key": it["key"]})
        return {"lists": lists or DEFAULT_LISTS, "cards": cards}
    def push(self, board):
        existing = {c["name"].strip().lower(): c for c in self.pull(None)["cards"]}
        created = moved = 0
        for c in board["cards"]:
            ex = existing.get(c["name"].strip().lower())
            if not ex:
                _get_json(f"{self.base}/rest/api/3/issue", self.headers, "POST",
                          {"fields": {"project": {"key": self.proj}, "summary": c["name"], "issuetype": {"name": "Task"}}})
                created += 1
            elif ex["list"] != c["list"]:
                tr = _get_json(f"{self.base}/rest/api/3/issue/{ex['key']}/transitions", self.headers)
                match = next((t for t in tr.get("transitions", []) if t["to"]["name"].lower() == c["list"].lower()), None)
                if match:
                    _get_json(f"{self.base}/rest/api/3/issue/{ex['key']}/transitions", self.headers, "POST", {"transition": {"id": match["id"]}})
                    moved += 1
        return f"{created} created, {moved} moved"


PROVIDERS = {"local": LocalProvider, "trello": TrelloProvider, "jira": JiraProvider}


def get_provider():
    name = detect_provider()
    if name not in PROVIDERS:
        sys.exit(f"Unknown PM_PROVIDER '{name}'. Known: {', '.join(PROVIDERS)}")
    return PROVIDERS[name]()


# ── local board ─────────────────────────────────────────────────────────────
def load(path):
    if not path.is_file(): sys.exit(f"No board at {path}. Run: python board.py init")
    return json.loads(path.read_text(encoding="utf-8"))
def save(path, b): path.write_text(json.dumps(b, indent=2, ensure_ascii=False), encoding="utf-8")
def find_card(b, name): return next((c for c in b["cards"] if c["name"].strip().lower() == name.strip().lower()), None)


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_init(a, path):
    if path.is_file() and not a.force: sys.exit(f"{path} exists. Use --force.")
    lists = [s.strip() for s in a.lists.split(",")] if a.lists else DEFAULT_LISTS
    save(path, {"lists": lists, "cards": []}); print(f"Initialized {path} with: {', '.join(lists)}")

def cmd_show(a, path):
    b = load(path); prov = get_provider()
    print(f"# Board — provider: {prov.name} ({'online' if prov.online else 'offline'})\n")
    for lst in b["lists"]:
        cards = [c for c in b["cards"] if c["list"] == lst]
        print(f"## {lst} ({len(cards)})")
        for c in cards: print(f"  - {c['name']}")
        if not cards: print("  (empty)")
        print()

def cmd_add(a, path):
    b = load(path)
    if find_card(b, a.name): sys.exit(f"Card exists: {a.name}")
    lst = a.list or b["lists"][0]
    if lst not in b["lists"]: sys.exit(f"Unknown list '{lst}'. Known: {', '.join(b['lists'])}")
    b["cards"].append({"name": a.name, "list": lst, "desc": a.desc or ""}); save(path, b); print(f"Added '{a.name}' to {lst}")

def cmd_move(a, path):
    b = load(path); c = find_card(b, a.name)
    if not c: sys.exit(f"No card: {a.name}")
    if a.to not in b["lists"]: sys.exit(f"Unknown list '{a.to}'. Known: {', '.join(b['lists'])}")
    c["list"] = a.to; save(path, b); print(f"Moved '{c['name']}' -> {a.to}")

def cmd_claim(a, path): a.to = CLAIM_LIST; cmd_move(a, path)
def cmd_ship(a, path):  a.to = SHIP_LIST;  cmd_move(a, path)

def cmd_pick(a, path):
    b = load(path)
    # "Most ready" = pre-progress list closest to In progress (rightmost). Iterate right-to-left.
    for lst in [l for l in b["lists"] if l not in (CLAIM_LIST, SHIP_LIST, "Done")][::-1]:
        for c in b["cards"]:
            if c["list"] == lst: print(c["name"]); return
    print("(no eligible cards)")

def cmd_rm(a, path):
    b = load(path); c = find_card(b, a.name)
    if not c: sys.exit(f"No card: {a.name}")
    b["cards"].remove(c); save(path, b); print(f"Removed '{a.name}'")

def cmd_status(a, path):
    prov = get_provider()
    if prov.online: print(f"ONLINE — provider: {prov.name}")
    else: print("OFFLINE — provider: local. Set TRELLO_* or JIRA_* env (see .env.example) to sync.")
    if path.is_file():
        b = load(path); print(f"{len(b['cards'])} cards / {len(b['lists'])} lists at {path}")

def cmd_pull(a, path):
    prov = get_provider()
    if not prov.online: prov.pull(None)
    save(path, prov.pull(load(path) if path.is_file() else None))
    print(f"Pulled from {prov.name} (remote wins).")

def cmd_push(a, path):
    prov = get_provider()
    if not prov.online: prov.push(None)
    print(f"Pushed to {prov.name}: {prov.push(load(path))}.")


COMMANDS = {"init": cmd_init, "show": cmd_show, "list": cmd_show, "add": cmd_add, "move": cmd_move,
            "claim": cmd_claim, "ship": cmd_ship, "pick": cmd_pick, "rm": cmd_rm,
            "status": cmd_status, "pull": cmd_pull, "push": cmd_push}


def main():
    p = argparse.ArgumentParser(description="Offline-first kanban with pluggable providers (local/trello/jira).")
    p.add_argument("command", choices=COMMANDS.keys())
    p.add_argument("name", nargs="?")
    p.add_argument("--file", default="board.json")
    p.add_argument("--list", "--lista", dest="list")
    p.add_argument("--to", "--a", dest="to")
    p.add_argument("--desc", dest="desc")
    p.add_argument("--lists", "--listas", dest="lists")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    path = Path(a.file).expanduser().resolve(); load_env(path.parent)
    if a.command in ("add", "move", "claim", "ship", "rm") and not a.name: sys.exit(f"'{a.command}' needs a card name.")
    if a.command == "move" and not a.to: sys.exit("'move' needs --to <list>.")
    COMMANDS[a.command](a, path)


if __name__ == "__main__":
    main()
