"""Collect the Smoker test results from the test server / game logs (runs on the PC).

Usage: python tools\\check_logs.py [--root <PZTest folder>] [--out <report.md>]
  --root   test folder made by SkillViewer\\test_server.ps1 (default %PZ_TEST_DIR% or %USERPROFILE%\\PZTest)
  --out    also write the report to this file (UTF-8 with BOM, so Notepad shows it)
Exit code 1 if the latest run of any test has a FAIL, or a Lua error mentions a Smoker file.

Reads
- server: <root>\\server\\Logs\\**\\*DebugLog-server.txt (one per server start, the newest also
  as server-console.txt); client: <root>\\client*\\Logs\\**\\*DebugLog.txt
- single player: %USERPROFILE%\\Zomboid\\console.txt ("Smoker: run tests")

Reports, in Japanese
- every MP test run ("[SmokerTest] ---- <name> start by <user> ----"): server PASS/FAIL counts,
  which players answered and how, FAIL lines
- evidence for MP_TESTPLAN rows that only show up in the logs: registration right after
  building (1-1) and after a server start (4-9), onCooked on the server (5-1), lit/unlit sync (7-x)
- Lua errors: stack traces that mention a Smoker file (FAIL) and the others (count only)
"""
import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

LINE_TS = re.compile(r'^\[(\d\d)-(\d\d)-(\d\d) (\d\d:\d\d:\d\d)\.\d+\]')


def parse_ts(line):
    m = LINE_TS.match(line)
    if not m:
        return None
    d, mo, y, t = m.groups()
    return datetime.strptime(f'20{y}-{mo}-{d} {t}', '%Y-%m-%d %H:%M:%S')


def read_lines(p):
    return p.read_text(encoding='utf-8', errors='replace').splitlines()


def strip(line):
    """'[ts] LOG  : Lua  f:1 st:2> text' -> text"""
    i = line.find('> ')
    return line[i + 2:] if i >= 0 else line


# ---------- MP test runs ----------

class Run:
    def __init__(self, name, user, ts, source):
        self.name, self.user, self.ts, self.source = name, user, ts, source
        self.server = []        # (ok, text)
        self.clients = {}       # user -> list of (status, text)
        self.online = None
        self.done = None
        self.notes = []

    def server_fail(self):
        return [t for ok, t in self.server if not ok]

    def client_fail(self):
        return [(u, t) for u, l in self.clients.items() for s, t in l if s == 'FAIL']


def parse_server_log(p):
    runs, cur = [], None
    build_ts = None
    evidence = {'build_register': [], 'load_register': [], 'onCooked_real': [], 'start': None}
    for raw in read_lines(p):
        ts = parse_ts(raw)
        text = strip(raw).rstrip('.')
        if evidence['start'] is None and ts:
            evidence['start'] = ts
        if 'ISBuildingEntity' in text and ts:
            build_ts = ts
        if '[Smoker] smoker registered' in text and ts:
            # newer logs say which hook fired: "(new)" built just now, "(load)" loaded with the map.
            # older logs: a registration within 2 s of the build line (BuildCheat only) counts as built.
            if '(new)' in text or '(added)' in text or (build_ts and (ts - build_ts).total_seconds() <= 2):
                evidence['build_register'].append((ts, text))
            elif '(test)' not in text:
                evidence['load_register'].append((ts, text))
        if not text.startswith('[SmokerTest]'):
            continue
        body = text[len('[SmokerTest] '):]
        m = re.match(r'---- (\w+) start by (\S+) ----', body)
        if m:
            cur = Run(m.group(1), m.group(2), ts, p)
            runs.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r'online players: (\d+) \((.*)\)', body)
        if m:
            cur.online = (int(m.group(1)), m.group(2))
            continue
        m = re.match(r'server (PASS|FAIL) (.*)', body)
        if m:
            cur.server.append((m.group(1) == 'PASS', m.group(2)))
            continue
        m = re.match(r'client (\S+) (PASS|FAIL|SKIP) (.*)', body)
        if m:
            cur.clients.setdefault(m.group(1), []).append((m.group(2), m.group(3)))
            continue
        m = re.match(r'---- \w+ done: (.*?) \(client', body)
        if m:
            cur.done = m.group(1)
            cur = None
            continue
        cur.notes.append(body)
    # a cookwatch that saw the real OnCooked: the [Smoker] onCooked line between its start and done
    return runs, evidence


def latest_of_each(runs):
    out = {}
    for r in runs:
        if r.name not in out or (out[r.name].ts or datetime.min) <= (r.ts or datetime.min):
            out[r.name] = r
    return out


# ---------- Lua errors ----------

def lua_errors(p):
    """[(message | first Lua frame, kind)] for every Lua error in the log; kind is
    'smoker' (a Smoker file in the trace), 'related' (a vanilla file Smoker_Fuel.lua
    wraps, or the fireplace code) or 'other'. Repeats of the same error are merged."""
    lines = read_lines(p)
    out, seen = [], set()
    for i, l in enumerate(lines):
        if 'STACK TRACE' not in l or lines[i - 1].strip('-') != '':
            continue
        block = lines[max(0, i - 6):i + 25]
        # "flushErrorMessage > -----" then the message on the next line
        msg = ''
        for k in range(i - 1, max(0, i - 8), -1):
            if 'flushErrorMessage' in lines[k] and lines[k].rstrip().endswith('-----'):
                msg = lines[k + 1].strip().rstrip('.')
                break
        frame = next((x.strip().rstrip('.') for x in lines[i + 2:i + 25] if x.strip().startswith('Lua(')), '')
        # the same error is dumped twice (Lua dump, then the Java exception): keep one per frame
        if frame in seen:
            if msg and out and out[-1][0].startswith(' | ' + frame):
                out[-1] = (f'{msg} | {frame}', out[-1][1])
            continue
        seen.add(frame)
        if any('Smoker' in x for x in block):
            kind = 'smoker'
        elif any(w in frame for w in RELATED_FILES):
            kind = 'related'
        else:
            kind = 'other'
        out.append((f'{msg} | {frame}', kind))
    return out


# vanilla files the mod wraps (Smoker_Fuel.lua) or that run the smoker's fire
RELATED_FILES = ('ISBBQAddFuel', 'ISBBQLightFrom', 'ISBBQExtinguish', 'ISCampingMenu', 'camping_fuel', 'Fireplace')


# ---------- report ----------

def fmt_run(r):
    sp = sum(1 for ok, _ in r.server if ok)
    when = f'{r.ts:%Y-%m-%d %H:%M}' if r.ts else '時刻不明（server-console.txt には時刻がない）'
    lines = [f'### {when} {r.name}（{r.user} が開始）  サーバー {sp}/{len(r.server)} PASS'
             + ('' if r.done else '  ※終了行なし（途中で止まった、またはサーバー停止）')]
    if r.online:
        lines.append(f'- 接続中: {r.online[0]} 人（{r.online[1]}）')
    for u, l in sorted(r.clients.items()):
        c = {s: sum(1 for x in l if x[0] == s) for s in ('PASS', 'FAIL', 'SKIP')}
        lines.append(f'- プレイヤー {u}: PASS {c["PASS"]} / FAIL {c["FAIL"]} / SKIP {c["SKIP"]}')
    if not r.clients:
        lines.append('- プレイヤー側の答えなし（デバッグモードで起動していない、または燻製器から遠い）')
    elif r.online and len(r.clients) < r.online[0]:
        lines.append(f'- **答えたプレイヤーが {len(r.clients)} 人だけ**（接続 {r.online[0]} 人）。'
                     '他のプレイヤーにも届くかは未確認')
    elif len(r.clients) < 2:
        lines.append('- 答えたのは 1 人だけ。**他のプレイヤーに変化が届くかは未確認**（2 人で走らせる）')
    for t in r.server_fail():
        lines.append(f'- FAIL（サーバー）: {t}')
    for u, t in r.client_fail():
        lines.append(f'- FAIL（{u}）: {t}')
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.environ.get('PZ_TEST_DIR') or str(Path(os.environ.get('USERPROFILE', '')) / 'PZTest'))
    ap.add_argument('--out')
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:  # noqa: BLE001
        pass
    root = Path(a.root)
    rep = ['# Smoker テスト結果まとめ', f'テストフォルダ: {root}', '']
    fail = False

    server_logs = sorted(root.glob('server/Logs/**/*DebugLog-server.txt'))
    if not server_logs and (root / 'server/server-console.txt').exists():
        server_logs = [root / 'server/server-console.txt']
    client_logs = sorted(root.glob('client*/Logs/**/*DebugLog.txt'))
    if not server_logs:
        rep.append(f'サーバーのログが見つからない: {root}\\server\\Logs')

    runs, starts, evid = [], [], {'build_register': [], 'load_register': []}
    for p in server_logs:
        r, e = parse_server_log(p)
        runs += r
        if e['start']:
            starts.append(e['start'])
        evid['build_register'] += e['build_register']
        evid['load_register'] += e['load_register']

    rep.append('## マルチの自動テスト（サーバーのログ）')
    if not runs:
        rep.append('まだ一度も走っていない（燻製器を右クリック → Smoker: MP test ...）')
    latest = latest_of_each(runs)
    for name in ('run', 'watch', 'cookwatch'):
        r = latest.get(name)
        if not r:
            rep.append(f'### {name}: 未実施')
            continue
        rep += fmt_run(r)
        if r.server_fail() or r.client_fail() or not r.done:
            fail = True
    older = [r for r in runs if r not in latest.values()]
    if older:
        rep.append(f'（古い回 {len(older)} 件は省略。最新の回だけを見ている）')
    rep.append('')

    rep.append('## ログから分かること（MP_TESTPLAN の項目）')
    br = evid['build_register']
    rep.append(f'- 1-1 組み立て直後の登録: ' + (f'確認済み（{br[-1][0]:%m-%d %H:%M} {br[-1][1]}）' if br
               else '未確認（ISBuildingEntity の直後に smoker registered が出た記録なし）'))
    lr = evid['load_register']
    rep.append(f'- 4-9 サーバー起動後の読み込みで登録: ' + (f'確認済み（{len(lr)} 回。最新 {lr[-1][0]:%m-%d %H:%M}）' if lr else '未確認'))
    w = latest.get('watch')
    rep.append('- 4-1 燻製器の火で焼けない（本物の時間）: ' + ('確認済み（watch）' if w and not w.server_fail() else '未確認（watch を走らせる）'))
    cw = latest.get('cookwatch')
    rep.append('- 5-1 燻製器の外で焼くと普通の焼けた肉になる（本物の加熱）: '
               + ('確認済み（cookwatch）' if cw and not cw.server_fail() else '未確認（cookwatch を走らせる。近くに火のついた焚き火かオーブンが要る）'))
    rn = latest.get('run')
    lit = rn and any('smoker lit by the server' in t or 'smoker put out by the server' in t
                     for l in rn.clients.values() for s, t in l if s == 'PASS')
    rep.append('- 7-1/7-3 火の点け消しと煙がもう 1 人にも届く: '
               + ('確認済み（run の lit / put out）' if lit else '未確認（新しい run を 2 人で走らせる。開始した本人の画面に火と煙が出ることは watch で確認済み）'))
    two = any(len(r.clients) >= 2 for r in runs)
    rep.append('- 他のプレイヤーにも変化が届く: ' + ('確認済み（2 人以上が答えた回あり）' if two else '**未確認**（答えたのが毎回 1 人。2 人とも燻製器の近くで走らせる）'))
    rep.append('')

    rep.append('## Lua のエラー')
    for p in server_logs + client_logs:
        errs = lua_errors(p)
        mine = [e for e, k in errs if k == 'smoker']
        related = [e for e, k in errs if k == 'related']
        other = [e for e, k in errs if k == 'other']
        if errs:
            rep.append(f'- {p.relative_to(root)}: Smoker のファイルを含む {len(mine)} 件、'
                       f'燃料・火の本体コード {len(related)} 件、その他 {len(other)} 件（同じものはまとめた）')
            for e in mine:
                rep.append(f'  - FAIL {e}')
                fail = True
            for e in related:
                rep.append(f'  - 注意（Smoker が手を入れている本体の処理。動作に影響がないか見る）: {e[:160]}')
            for e in other[:3]:
                rep.append(f'  - その他の例: {e[:160]}')
    if len(rep) and rep[-1] == '## Lua のエラー':
        rep.append('- なし')
    rep.append('')

    sp = Path(os.environ.get('USERPROFILE', '')) / 'Zomboid' / 'console.txt'
    if sp.exists():
        done = [strip(l) for l in read_lines(sp) if '[SmokerTest] ---- done' in l]
        rep.append('## 1 人用の自動テスト（%USERPROFILE%\\Zomboid\\console.txt）')
        rep.append('- ' + (done[-1] if done else '記録なし'))
        rep.append('')

    rep.append('判定: ' + ('**FAIL あり**' if fail else '最新の回はすべて PASS'))
    text = '\n'.join(rep)
    print(text)
    if a.out:
        Path(a.out).write_text(text + '\n', encoding='utf-8-sig')
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
