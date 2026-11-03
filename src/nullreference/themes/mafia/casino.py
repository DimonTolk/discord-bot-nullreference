"""Casino rules and presentation. Random draws are independent and wallet-only."""

from datetime import datetime, timezone

from nullreference.core.theme import RuleError

SYMBOLS = ("🍒", "🍋", "🔔", "💎")
SUITS = ("♠️", "♥️", "♦️", "♣️")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


def check(ok, text):
    if not ok:
        raise RuleError(text)


def total(cards):
    values = [min(c % 13 + 1, 10) for c in cards]
    score = sum(values)
    return score + 10 if 1 in values and score + 10 <= 21 else score


def cards_text(cards):
    return "  ".join(f"`{RANKS[c % 13]}`{SUITS[c // 13]}" for c in cards)


def component_action(payload):
    parts = payload.get("data", {}).get("custom_id", "").split(":")
    check(len(parts) == 5 and parts[0] == "blackjack", "Неизвестная кнопка")
    _, owner, hand, revision, action = parts
    check(owner == payload["member"]["user"]["id"], "Это чужая раздача")
    check(
        hand.isdecimal() and revision.isdecimal() and action in ("hit", "stand"),
        "Некорректная кнопка",
    )
    return {"hand": hand, "revision": int(revision), "decision": action}


class MafiaCasino:
    def __init__(self, roll):
        self.roll = roll

    def bet(self, player, amount, minimum, maximum=None):
        check(
            type(amount) is int and amount >= minimum and (maximum is None or amount <= maximum),
            "Ставка вне разрешённых границ",
        )
        check(amount <= player["money"], "Недостаточно личных денег")

    def allowance(self, player, now):
        date = datetime.fromtimestamp(now, timezone.utc).isocalendar()
        key = f"{date.year}-{date.week}"
        usage = player.setdefault("casino_usage", {"week": key, "count": 0})
        if usage["week"] != key:
            usage.update(week=key, count=0)
        check(usage["count"] < 5, "Лимит казино: 5 игр в неделю. Сброс в понедельник 00:00 UTC")
        usage["count"] += 1

    def slots(self, season, state, actor, now, amount):
        p = season.player(state, actor)
        self.bet(p, amount, 5, 20)
        self.allowance(p, now)
        reels = [self.roll(4) for _ in range(3)]
        multiplier = 3 if len(set(reels)) == 1 else 2 if reels.count(0) == 2 else 0
        payout = amount * multiplier
        p["money"] += payout - amount
        return {
            "casino": "slots",
            "reels": reels,
            "bet": amount,
            "payout": payout,
            "money": p["money"],
            "used": p["casino_usage"]["count"],
        }

    def start(self, season, state, actor, now, amount):
        p = season.player(state, actor)
        previous = p.get("blackjack")
        check(
            not previous or previous["status"] != "active",
            "У вас уже есть активная раздача. Используйте кнопки или /blackjack_table",
        )
        self.bet(p, amount, 10)
        self.allowance(p, now)
        p["money"] -= amount
        hand = {
            "id": season.identifier(state),
            "revision": 0,
            "bet": amount,
            "player": [self.roll(52), self.roll(52)],
            "dealer": [self.roll(52), self.roll(52)],
            "until": now + 86400,
            "status": "active",
            "payout": 0,
            "outcome": "",
        }
        p["blackjack"] = hand
        if total(hand["player"]) == 21 or total(hand["dealer"]) == 21:
            self.settle(p, hand, natural=True)
        return self.result(p, actor)

    def settle(self, player, hand, natural=False):
        a, b = total(hand["player"]), total(hand["dealer"])
        if not natural and a <= 21:
            while total(hand["dealer"]) < 17:
                hand["dealer"].append(self.roll(52))
            b = total(hand["dealer"])
        if a > 21:
            outcome, payout = "💥 Перебор. Ставка проиграна.", 0
        elif a == b:
            outcome, payout = "🤝 Ничья. Ставка возвращена.", hand["bet"]
        elif natural and a == 21:
            outcome = "🃏 Блэкджек! Выплата 3:2 (дробная прибыль округляется вниз)."
            payout = hand["bet"] + hand["bet"] * 3 // 2
        elif b > 21 or (a > b and not (natural and b == 21)):
            outcome, payout = "🏆 Победа! Выплата ×2.", hand["bet"] * 2
        else:
            outcome, payout = "🎩 Победил дилер. Ставка проиграна.", 0
        player["money"] += payout
        hand.update(status="done", payout=payout, outcome=outcome)

    def move(self, season, state, actor, now, hand, revision, decision):
        p = season.player(state, actor)
        game = p.get("blackjack")
        check(game and game["id"] == hand, "Эта раздача устарела. Откройте /blackjack_table")
        check(decision in ("hit", "stand"), "Неверное действие")
        # Repeated/stale clicks never draw another card or pay twice.
        if game["status"] == "active" and revision == game["revision"]:
            game["revision"] += 1
            if decision == "hit":
                game["player"].append(self.roll(52))
            if decision == "stand" or total(game["player"]) >= 21:
                self.settle(p, game)
        return self.result(p, actor)

    def result(self, player, actor):
        game = player.get("blackjack")
        check(game, "У вас нет раздачи. Начните: /blackjack amount:10")
        # The unrevealed dealer card must never enter a public response or event result.
        active = game["status"] == "active"
        return {
            "casino": "blackjack",
            "owner": actor,
            "hand": {k: v for k, v in game.items() if k != "dealer"},
            "dealer": game["dealer"][:1] if active else game["dealer"],
            "money": player["money"],
        }

    def expire(self, state, now):
        for player in state["players"].values():
            game = player.get("blackjack")
            if game and game["status"] == "active" and game["until"] <= now:
                self.settle(player, game)
                game["outcome"] += " ⏳ Автоматическое вскрытие после 24 часов."


def render(result):
    if result["casino"] == "slots":
        text = (
            "## 🎰 Слоты\n"
            + " │ ".join(SYMBOLS[i] for i in result["reels"])
            + f"\nСтавка: {result['bet']} · Выплата: {result['payout']}"
            + ("\n🎉 Выигрыш!" if result["payout"] else "\n💨 В этот раз без выигрыша.")
            + f"\nЛичные деньги: {result['money']} · Игр на этой неделе: {result['used']}/5"
        )
        return {"content": text, "components": []}
    h = result["hand"]
    active = h["status"] == "active"
    dealer = cards_text(result["dealer"]) + ("  🂠" if active else "")
    text = (
        f"## 🃏 Блэкджек · раздача №{h['id']}\nИгрок: <@{result['owner']}> · Ставка: {h['bet']}"
        + f"\nВы: {cards_text(h['player'])} — **{total(h['player'])}**"
        + f"\nДилер: {dealer}"
        + ("" if active else f" — **{total(result['dealer'])}**")
        + (
            f"\nЕщё или открываемся? Срок: <t:{int(h['until'])}:f>."
            if active
            else f"\n{h['outcome']}\nВыплата: {h['payout']}"
        )
        + f"\nЛичные деньги: {result['money']}"
    )
    buttons = [
        {
            "type": 2,
            "style": 1 if action == "hit" else 2,
            "label": label,
            "custom_id": f"blackjack:{result['owner']}:{h['id']}:{h['revision']}:{action}",
        }
        for action, label in (("hit", "🃏 Ещё"), ("stand", "✋ Открываемся!"))
    ]
    return {"content": text, "components": [{"type": 1, "components": buttons}] if active else []}
