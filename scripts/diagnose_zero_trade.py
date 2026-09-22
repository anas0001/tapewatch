"""
Read-only diagnostic for a zero-trade drought. Scp'd to /tmp on the host by
`.github/workflows/diagnose-zero-trade.yml`, run once with the venv's
python3, then deleted — never installed under DEPLOY_PATH, never touches the
running service.

Opens the DB connection with `readonly=True`: a real Postgres READ ONLY
transaction, so an accidental write raises instead of merely being
discouraged by convention.

Usage: DB_URL=... SINCE_DAYS=15 python3 diagnose_zero_trade.py
"""

import os
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras


def show(cur, title, sql, params=()):
    print(f"\n=== {title} ===")
    cur.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        print("(no rows)")
        return
    for r in rows:
        print(dict(r))


def main() -> None:
    since_days = int(os.environ.get("SINCE_DAYS") or 15)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")

    conn = psycopg2.connect(os.environ["DB_URL"])
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    show(
        cur,
        "Last 20 trades (any mode)",
        "SELECT id, mode, ticker, buy_time, sell_time, status, exit_reason, "
        "profit_loss_pct FROM trades ORDER BY buy_time DESC LIMIT 20",
    )

    show(
        cur,
        f"Trades per day, last {since_days} days",
        "SELECT (buy_time::timestamptz AT TIME ZONE 'Europe/London')::date AS d, "
        "mode, count(*) FROM trades WHERE buy_time::timestamptz > %s::timestamptz "
        "GROUP BY 1, 2 ORDER BY 1 DESC",
        (cutoff,),
    )

    show(
        cur,
        f"sentiment_scores volume per day, last {since_days} days",
        "SELECT (scored_at::timestamptz AT TIME ZONE 'Europe/London')::date AS d, "
        "catalyst_type, sentiment, count(*), "
        "round(avg(confidence)::numeric, 2) AS avg_conf, "
        "sum(already_moved) AS already_moved_count "
        "FROM sentiment_scores WHERE scored_at::timestamptz > %s::timestamptz "
        "GROUP BY 1, 2, 3 ORDER BY 1 DESC, 4 DESC",
        (cutoff,),
    )

    show(
        cur,
        "guidance_raise positive candidates specifically (last 40)",
        "SELECT scored_at, ticker, headline, confidence, catalyst_magnitude, "
        "already_moved FROM sentiment_scores "
        "WHERE scored_at::timestamptz > %s::timestamptz "
        "AND catalyst_type = 'guidance_raise' AND sentiment = 'positive' "
        "ORDER BY scored_at DESC LIMIT 40",
        (cutoff,),
    )

    show(
        cur,
        f"news_signals (tradeable-catalyst candidates that reached the price gate), "
        f"last {since_days} days",
        "SELECT (created_at::timestamptz AT TIME ZONE 'Europe/London')::date AS d, "
        "rejection_code, acted_on, count(*) FROM news_signals "
        "WHERE created_at::timestamptz > %s::timestamptz "
        "GROUP BY 1, 2, 3 ORDER BY 1 DESC",
        (cutoff,),
    )

    show(
        cur,
        f"classifier_calls liveness per day, last {since_days} days",
        "SELECT (called_at::timestamptz AT TIME ZONE 'Europe/London')::date AS d, "
        "provider, ok, error_type, count(*) FROM classifier_calls "
        "WHERE called_at::timestamptz > %s::timestamptz "
        "GROUP BY 1, 2, 3, 4 ORDER BY 1 DESC",
        (cutoff,),
    )

    show(
        cur,
        f"system_events, last {since_days} days",
        "SELECT event_day, event_type, severity, detail, created_at "
        "FROM system_events WHERE event_day >= %s ORDER BY created_at DESC",
        (cutoff_date,),
    )

    show(cur, "heartbeat (last beat per job)", "SELECT job, last_beat_at FROM heartbeat ORDER BY job")

    show(
        cur,
        f"premarket_candidates per day, last {since_days} days",
        "SELECT (created_at::timestamptz AT TIME ZONE 'Europe/London')::date AS d, "
        "status, count(*) FROM premarket_candidates "
        "WHERE created_at::timestamptz > %s::timestamptz GROUP BY 1, 2 ORDER BY 1 DESC",
        (cutoff,),
    )

    show(
        cur,
        f"premarket_candidates full detail, last {since_days} days",
        "SELECT id, ticker, catalyst_type, confidence, catalyst_magnitude, "
        "status, eval_note, created_at FROM premarket_candidates "
        "WHERE created_at::timestamptz > %s::timestamptz ORDER BY created_at DESC",
        (cutoff,),
    )

    cur.close()
    conn.close()
    print("\nDone. DB session was opened readonly=True — no write could have been issued.")


if __name__ == "__main__":
    main()
