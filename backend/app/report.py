"""Rapport du soir : met à jour les données, lance le scan et envoie le résumé sur Telegram.

Utilisation :
    python -m app.report              -> mise à jour + scan + envoi Telegram
    python -m app.report --dry-run    -> affiche le message sans l'envoyer
    python -m app.report --no-refresh -> utilise les données déjà en base (test rapide)

Variables d'environnement (secrets GitHub) :
    TELEGRAM_BOT_TOKEN : code donné par @BotFather (obligatoire pour l'envoi)
    TELEGRAM_CHAT_ID   : ton identifiant Telegram (facultatif : sinon il est retrouvé
                         automatiquement si tu as écrit à ton bot dans les dernières 24 h)
"""
import argparse
import html
import os
import sys
from datetime import date

import requests

from .analysis.macro import market_regime
from .db import SessionLocal, init_db
from .services.analysis import recommendations, run_scan
from .services.ingest import refresh_all

TG_API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 3900  # limite Telegram : 4096 caractères par message
MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _num(v: float) -> str:
    if v is None:
        return "–"
    a = abs(v)
    dec = 5 if a < 2 else 4 if a < 10 else 2
    s = f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def _d(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]}"


def build_message(s, errors: list[str] | None = None, min_score: int = 60, max_trades: int = 6) -> str:
    from sqlalchemy import select

    from .models import Asset, Signal

    e = html.escape
    r = market_regime(s)
    reco = recommendations(s)
    lines = [f"📊 <b>Rapport du {_d(date.today().isoformat())}</b> · marché <b>{e(r['label'])}</b>"]
    ctx = []
    if r.get("vix") is not None:
        ctx.append(f"VIX {r['vix']:.1f}".replace(".", ","))
    ctx.append({1.0: "dollar fort", -1.0: "dollar faible"}.get(r.get("dollar"), "dollar neutre"))
    if r.get("us10y") is not None:
        ctx.append(f"taux US 10 ans {r['us10y']:.2f} %".replace(".", ","))
    lines.append(" · ".join(ctx))

    rows = s.execute(select(Signal, Asset).join(Asset).where(Signal.status == "active", Asset.active,
                                                             Signal.score >= min_score)
                     .order_by(Signal.score.desc())).all()
    lines.append("")
    lines.append(f"🎯 <b>Trades à considérer</b> ({len(rows)})")
    if not rows:
        lines.append("Aucun setup avec un score ≥ 60 ce soir. Patience : pas de trade, c'est aussi une décision.")
    for sig, a in rows[:max_trades]:
        icon = "🟢" if sig.direction == "long" else "🔴"
        sens = "achat" if sig.direction == "long" else "vente"
        lines.append(f"{icon} <b>{e(a.name)}</b> {sens} · score {sig.score}")
        lines.append(f"   entrée {_num(sig.entry_low)}–{_num(sig.entry_high)} · stop {_num(sig.stop)} · "
                     f"obj. {_num(sig.tp1)} / {_num(sig.tp2)} (R:R {f'{sig.rr_tp1:.1f}'.replace('.', ',')})")
        if any("Résultats" in w for w in sig.warnings):
            lines.append("   ⚠ publication de résultats pendant le trade")
    if len(rows) > max_trades:
        lines.append(f"   … et {len(rows) - max_trades} autre(s) dans l'app")

    if reco["watch"]:
        lines.append("")
        lines.append("👀 <b>À surveiller</b> (place une alerte)")
        for w in reco["watch"][:5]:
            long_ = w["direction"] == "long"
            what = {"pullback": (f"repli vers {_num(w['level'])}, zone d’achat potentielle" if long_ else
                                 f"rebond vers {_num(w['level'])}, zone de vente potentielle"),
                    "breakout": f"teste {'la résistance' if long_ else 'le support'} {_num(w['level'])}",
                    "oversold": f"{'survente' if long_ else 'surachat'} dans la tendance"}[w["kind"]]
            lines.append(f"{'🟢' if long_ else '🔴'} <b>{e(w['name'])}</b> : {what}")

    leaders = []
    for g in reco["momentum"].values():
        if g["leaders"]:
            x = g["leaders"][0]
            leaders.append(f"{e(x['name'])} (+{x['perf']['m3']:.0f} % en 3 mois)" if x["perf"].get("m3") is not None
                           else e(x["name"]))
    if leaders:
        lines.append("")
        lines.append("🚀 <b>Plus fortes tendances</b> : " + ", ".join(leaders))

    if reco["upcoming_events"]:
        lines.append("")
        ev = ", ".join(f"{e(x['name'])} {_d(x['date'])}" for x in reco["upcoming_events"][:6])
        lines.append(f"📅 <b>Résultats à venir</b> : {ev}")

    if errors:
        lines.append("")
        lines.append(f"⚙ {len(errors)} donnée(s) non mise(s) à jour ce soir : "
                     + e(", ".join(x.split(' ')[0] for x in errors[:8])))
    page_url = os.environ.get("PAGE_URL", "").strip()
    if page_url:
        lines.append("")
        lines.append(f'📈 <a href="{e(page_url)}">Voir les graphiques et le détail des trades</a>')
    lines.append("")
    lines.append("<i>Aide à la décision, pas un conseil en investissement.</i>")
    return "\n".join(lines)


def _split(text: str) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > MAX_LEN:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    return parts + [cur] if cur.strip() else parts


def find_chat_id(token: str) -> str | None:
    """Retrouve ton identifiant à partir du dernier message que tu as envoyé à ton bot."""
    r = requests.get(TG_API.format(token=token, method="getUpdates"), timeout=30)
    r.raise_for_status()
    for upd in reversed(r.json().get("result", [])):
        msg = upd.get("message") or upd.get("edited_message") or {}
        if msg.get("chat", {}).get("id"):
            return str(msg["chat"]["id"])
    return None


def send(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN manquant : ajoute-le dans les secrets GitHub.")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    discovered = False
    if not chat_id:
        chat_id = find_chat_id(token)
        discovered = True
    if not chat_id:
        sys.exit("Identifiant Telegram introuvable. Dans Telegram, ouvre la conversation avec TON bot "
                 "(celui créé avec @BotFather), appuie sur « Démarrer » ou envoie « bonjour », "
                 "puis relance la tâche dans les 24 h.")
    for part in _split(text):
        r = requests.post(TG_API.format(token=token, method="sendMessage"), timeout=30,
                          json=dict(chat_id=chat_id, text=part, parse_mode="HTML",
                                    link_preview_options={"is_disabled": True}))
        if not r.ok:
            sys.exit(f"Envoi Telegram refusé ({r.status_code}) : {r.json().get('description', r.text)}")
    print("Rapport envoyé sur Telegram.")
    if discovered:
        # Telegram n'expose le message « bonjour » que 24 h : sans ce secret, les soirs suivants échoueraient.
        print("::warning::Ton identifiant Telegram est " + chat_id + ". Ajoute-le maintenant comme secret "
              "TELEGRAM_CHAT_ID (Settings > Secrets and variables > Actions) pour que le rapport "
              "fonctionne tous les soirs.")


def main() -> None:
    p = argparse.ArgumentParser(description="Rapport du soir")
    p.add_argument("--dry-run", action="store_true", help="affiche le message sans l'envoyer")
    p.add_argument("--no-refresh", action="store_true", help="ne retélécharge pas les données")
    p.add_argument("--site", metavar="DOSSIER", help="génère aussi la page du soir dans ce dossier")
    args = p.parse_args()

    init_db()
    errors: list[str] = []
    if not args.no_refresh:
        st = refresh_all()
        errors = list(st["errors"])
        print(f"Mise à jour terminée : {st['done']}/{st['total']} produits, {len(errors)} erreur(s).")
    with SessionLocal() as s:
        run_scan(s)
        if args.site:
            from .site import build_site
            print(f"Page du soir générée dans {build_site(s, args.site)}")
        msg = build_message(s, errors)
    if args.dry_run:
        print(msg)
    else:
        send(msg)


if __name__ == "__main__":
    main()
