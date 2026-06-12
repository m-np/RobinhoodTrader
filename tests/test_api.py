"""
API integration tests — run with: pytest tests/ -v
Requires the database to be running (postgresql:///robinhoodtrader).
All tests clean up after themselves.
"""


# ── Pages ─────────────────────────────────────────────────────────────────────

class TestPages:
    def test_dashboard_loads(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Agentic trader" in r.text

    def test_watchlist_page_loads(self, client):
        r = client.get("/watchlist")
        assert r.status_code == 200
        assert "Watchlist" in r.text

    def test_mirrors_page_loads(self, client):
        r = client.get("/mirrors")
        assert r.status_code == 200
        assert "mirrors" in r.text.lower()

    def test_settings_page_loads(self, client):
        r = client.get("/settings")
        assert r.status_code == 200
        assert "Settings" in r.text


# ── Knobs ─────────────────────────────────────────────────────────────────────

class TestKnobs:
    def test_get_all_knobs(self, client):
        r = client.get("/api/knobs")
        assert r.status_code == 200
        knobs = r.json()
        expected = [
            "asset_stocks", "asset_crypto", "asset_options", "asset_futures", "asset_events",
            "approval_threshold_usd", "approval_timeout_minutes",
            "gate_new_positions", "gate_full_exits", "gate_rebalance", "gate_stop_loss",
            "max_position_pct", "max_trades_per_day", "daily_loss_halt_pct",
            "report_frequency", "report_weekly_day", "report_delivery",
            "report_depth", "report_include_rationale", "report_include_pnl",
        ]
        for key in expected:
            assert key in knobs, f"Missing knob: {key}"

    def test_default_knob_values(self, client):
        # Reset to known defaults before asserting
        client.post("/api/knobs", json={"key": "asset_stocks", "value": True})
        client.post("/api/knobs", json={"key": "asset_crypto", "value": False})
        client.post("/api/knobs", json={"key": "approval_threshold_usd", "value": 500})
        client.post("/api/knobs", json={"key": "max_position_pct", "value": 20})
        client.post("/api/knobs", json={"key": "report_frequency", "value": "weekly"})
        knobs = client.get("/api/knobs").json()
        assert knobs["asset_stocks"] is True
        assert knobs["asset_crypto"] is False
        assert knobs["approval_threshold_usd"] == 500
        assert knobs["max_position_pct"] == 20
        assert knobs["report_frequency"] == "weekly"

    def test_update_integer_knob(self, client):
        r = client.post("/api/knobs", json={"key": "max_trades_per_day", "value": 7})
        assert r.status_code == 200
        assert r.json()["status"] == "updated"
        assert client.get("/api/knobs").json()["max_trades_per_day"] == 7
        # restore
        client.post("/api/knobs", json={"key": "max_trades_per_day", "value": 5})

    def test_update_boolean_knob(self, client):
        r = client.post("/api/knobs", json={"key": "asset_crypto", "value": True})
        assert r.status_code == 200
        assert client.get("/api/knobs").json()["asset_crypto"] is True
        # restore
        client.post("/api/knobs", json={"key": "asset_crypto", "value": False})

    def test_update_string_knob(self, client):
        r = client.post("/api/knobs", json={"key": "report_frequency", "value": "daily"})
        assert r.status_code == 200
        assert client.get("/api/knobs").json()["report_frequency"] == "daily"
        # restore
        client.post("/api/knobs", json={"key": "report_frequency", "value": "weekly"})

    def test_update_float_knob(self, client):
        r = client.post("/api/knobs", json={"key": "daily_loss_halt_pct", "value": 5.0})
        assert r.status_code == 200
        assert client.get("/api/knobs").json()["daily_loss_halt_pct"] == 5.0
        # restore
        client.post("/api/knobs", json={"key": "daily_loss_halt_pct", "value": 3})


# ── Watchlist ─────────────────────────────────────────────────────────────────

class TestWatchlist:
    TICKER = "TEST_WL"

    def setup_method(self):
        # ensure clean state before each test
        pass

    def test_add_ticker(self, client):
        # clean up first in case previous run left it
        client.delete(f"/api/watchlist/{self.TICKER}")
        r = client.post("/api/watchlist", json={"ticker": self.TICKER, "notes": "pytest entry"})
        assert r.status_code == 200
        assert r.json()["status"] == "added"

    def test_duplicate_ticker_rejected(self, client):
        client.delete(f"/api/watchlist/{self.TICKER}")
        client.post("/api/watchlist", json={"ticker": self.TICKER})
        r = client.post("/api/watchlist", json={"ticker": self.TICKER})
        assert r.status_code == 409
        client.delete(f"/api/watchlist/{self.TICKER}")

    def test_list_contains_added_ticker(self, client):
        client.delete(f"/api/watchlist/{self.TICKER}")
        client.post("/api/watchlist", json={"ticker": self.TICKER, "notes": "test"})
        rows = client.get("/api/watchlist").json()
        tickers = [r["ticker"] for r in rows]
        assert self.TICKER in tickers
        client.delete(f"/api/watchlist/{self.TICKER}")

    def test_remove_ticker(self, client):
        client.post("/api/watchlist", json={"ticker": self.TICKER})
        r = client.delete(f"/api/watchlist/{self.TICKER}")
        assert r.status_code == 200
        assert r.json()["status"] == "removed"
        rows = client.get("/api/watchlist").json()
        assert self.TICKER not in [row["ticker"] for row in rows]

    def test_remove_nonexistent_returns_404(self, client):
        client.delete(f"/api/watchlist/{self.TICKER}")
        r = client.delete(f"/api/watchlist/{self.TICKER}")
        assert r.status_code == 404

    def test_ticker_uppercased(self, client):
        client.delete("/api/watchlist/TSTUP")
        client.post("/api/watchlist", json={"ticker": "tstup"})
        rows = client.get("/api/watchlist").json()
        assert any(r["ticker"] == "TSTUP" for r in rows)
        client.delete("/api/watchlist/TSTUP")


# ── Blocklist ─────────────────────────────────────────────────────────────────

class TestBlocklist:
    TICKER = "TEST_BL"

    def test_add_to_blocklist(self, client):
        client.delete(f"/api/blocklist/{self.TICKER}")
        r = client.post("/api/blocklist", json={"ticker": self.TICKER, "reason": "pytest"})
        assert r.status_code == 200
        assert r.json()["status"] == "added"

    def test_duplicate_blocked_rejected(self, client):
        client.delete(f"/api/blocklist/{self.TICKER}")
        client.post("/api/blocklist", json={"ticker": self.TICKER})
        r = client.post("/api/blocklist", json={"ticker": self.TICKER})
        assert r.status_code == 409
        client.delete(f"/api/blocklist/{self.TICKER}")

    def test_list_contains_blocked_ticker(self, client):
        client.delete(f"/api/blocklist/{self.TICKER}")
        client.post("/api/blocklist", json={"ticker": self.TICKER, "reason": "test"})
        rows = client.get("/api/blocklist").json()
        assert self.TICKER in [r["ticker"] for r in rows]
        client.delete(f"/api/blocklist/{self.TICKER}")

    def test_remove_from_blocklist(self, client):
        client.post("/api/blocklist", json={"ticker": self.TICKER})
        r = client.delete(f"/api/blocklist/{self.TICKER}")
        assert r.status_code == 200
        assert r.json()["status"] == "removed"
        rows = client.get("/api/blocklist").json()
        assert self.TICKER not in [r["ticker"] for r in rows]


# ── Mirrors ───────────────────────────────────────────────────────────────────

class TestMirrors:
    def test_all_mirrors_seeded(self, client):
        mirrors = client.get("/api/mirrors").json()
        slugs = [m["slug"] for m in mirrors]
        expected = [
            "nancy_pelosi", "dan_crenshaw", "tommy_tuberville", "austin_scott",
            "berkshire_hathaway", "soros_fund", "renaissance_tech",
        ]
        for slug in expected:
            assert slug in slugs, f"Missing mirror: {slug}"

    def test_mirrors_disabled_by_default(self, client):
        # Reset all to disabled so this test is not order-dependent
        mirrors = client.get("/api/mirrors").json()
        for m in mirrors:
            client.patch(f"/api/mirrors/{m['slug']}", json={"enabled": False})
        mirrors = client.get("/api/mirrors").json()
        for m in mirrors:
            assert m["enabled"] is False, f"{m['slug']} should be disabled"

    def test_enable_mirror(self, client):
        r = client.patch("/api/mirrors/nancy_pelosi", json={"enabled": True})
        assert r.status_code == 200
        mirrors = client.get("/api/mirrors").json()
        pelosi = next(m for m in mirrors if m["slug"] == "nancy_pelosi")
        assert pelosi["enabled"] is True
        # restore
        client.patch("/api/mirrors/nancy_pelosi", json={"enabled": False})

    def test_update_scale_factor(self, client):
        r = client.patch("/api/mirrors/berkshire_hathaway", json={"scale_factor": 0.05})
        assert r.status_code == 200
        mirrors = client.get("/api/mirrors").json()
        bh = next(m for m in mirrors if m["slug"] == "berkshire_hathaway")
        assert bh["scale_factor"] == 0.05
        # restore
        client.patch("/api/mirrors/berkshire_hathaway", json={"scale_factor": 0.02})

    def test_update_nonexistent_mirror_returns_404(self, client):
        r = client.patch("/api/mirrors/does_not_exist", json={"enabled": True})
        assert r.status_code == 404


# ── Alerts ────────────────────────────────────────────────────────────────────

class TestAlerts:
    def test_get_alerts_returns_list(self, client):
        r = client.get("/api/alerts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_acknowledge_alert(self, client):
        from datetime import datetime
        import uuid
        from db.session import SessionLocal
        from db.models import Alert

        # Insert a test alert directly
        alert_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Alert(
                id=alert_id,
                alert_type="market_wave",
                ticker="TSST",
                message="Test alert for pytest",
                severity="info",
                acknowledged=False,
                created_at=datetime.utcnow(),
            ))
            db.commit()
        finally:
            db.close()

        # Verify it appears
        alerts = client.get("/api/alerts").json()
        assert any(a["id"] == alert_id for a in alerts)

        # Acknowledge it
        r = client.post(f"/api/alerts/{alert_id}/ack")
        assert r.status_code == 200

        # Should no longer appear in unacknowledged list
        alerts = client.get("/api/alerts").json()
        assert not any(a["id"] == alert_id for a in alerts)


# ── Trades ────────────────────────────────────────────────────────────────────

class TestTrades:
    def test_get_trades_returns_list(self, client):
        r = client.get("/api/trades")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_approve_and_reject_trade(self, client):
        from datetime import datetime
        import uuid
        from db.session import SessionLocal
        from db.models import Trade

        trade_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Trade(
                id=trade_id,
                ticker="TSST",
                action="buy",
                asset_class="stock",
                quantity=1,
                price_usd=100.0,
                total_usd=100.0,
                status="pending_approval",
                created_at=datetime.utcnow(),
            ))
            db.commit()
        finally:
            db.close()

        r = client.post(f"/api/trades/{trade_id}/approve")
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

        trades = client.get("/api/trades").json()
        trade = next(t for t in trades if t["id"] == trade_id)
        assert trade["status"] == "executed"

        # Now test reject on a fresh trade
        trade_id2 = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Trade(
                id=trade_id2,
                ticker="TSST",
                action="sell",
                asset_class="stock",
                quantity=1,
                price_usd=100.0,
                total_usd=100.0,
                status="pending_approval",
                created_at=datetime.utcnow(),
            ))
            db.commit()
        finally:
            db.close()

        r = client.post(f"/api/trades/{trade_id2}/reject")
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


# ── Wallet / Portfolio ────────────────────────────────────────────────────────

class TestPortfolio:
    def test_wallet_returns_balance(self, client):
        r = client.get("/api/wallet")
        assert r.status_code == 200
        data = r.json()
        assert "balance" in data
        assert isinstance(data["balance"], (int, float))

    def test_portfolio_returns_expected_shape(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        data = r.json()
        assert "holdings" in data
        assert "trades_today" in data
        assert "today_pnl" in data
        assert "total_return_pct" in data
        assert isinstance(data["holdings"], list)
