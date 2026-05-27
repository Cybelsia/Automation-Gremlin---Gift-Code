import discord
from discord.ext import commands
import aiohttp
import ssl
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import base64
import hashlib
import json
from datetime import datetime
import sqlite3
from discord.ext import tasks
import asyncio
import random
import re
from urllib.parse import parse_qsl
from .alliance_member_operations import AllianceSelectView
from .alliance import PaginatedChannelView
import os
import traceback
from .gift_operationsapi import GiftCodeAPI
from cogs.permissions import check_permission
from paths import *

class GiftOperations(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if hasattr(bot, 'conn'):
            self.conn = bot.conn
            self.cursor = self.conn.cursor()
        else:
            self.conn = sqlite3.connect(database_path(GIFT_CODE_DB, 'giftcode.sqlite'))
            self.cursor = self.conn.cursor()
            
        self.api = GiftCodeAPI(bot)
            
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS giftcodecontrol (
                alliance_id INTEGER PRIMARY KEY,
                status INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()
        
        self.settings_conn = sqlite3.connect(database_path(SETTINGS_DB, 'settings.sqlite'))
        self.settings_cursor = self.settings_conn.cursor()
        
        self.alliance_conn = sqlite3.connect(database_path(ALLIANCE_DB, 'alliance.sqlite'))
        self.alliance_cursor = self.alliance_conn.cursor()

        self.gift_operations_conn = sqlite3.connect(database_path(GIFT_OPERATIONS_DB, 'gift_operations.sqlite'))
        self.gift_operations_cursor = self.gift_operations_conn.cursor()
        self.gift_operations_cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_gift_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                results_channel_id INTEGER
            )
        """)
        self.gift_operations_cursor.execute("PRAGMA table_info(auto_gift_settings)")
        auto_gift_settings_columns = [column[1] for column in self.gift_operations_cursor.fetchall()]
        if "results_channel_id" not in auto_gift_settings_columns:
            self.gift_operations_cursor.execute("ALTER TABLE auto_gift_settings ADD COLUMN results_channel_id INTEGER")
        self.gift_operations_cursor.execute("""
            CREATE TABLE IF NOT EXISTS auto_gift_alliances (
                guild_id INTEGER,
                alliance_id INTEGER,
                PRIMARY KEY (guild_id, alliance_id)
            )
        """)
        self.gift_operations_cursor.execute("""
            CREATE TABLE IF NOT EXISTS redemption_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                redemption_id TEXT NOT NULL,
                job_type TEXT NOT NULL,
                final_state TEXT NOT NULL,
                gift_code TEXT NOT NULL,
                fid INTEGER,
                alliance_id INTEGER,
                alliance_name TEXT,
                guild_id INTEGER,
                error_reason TEXT,
                exception_message TEXT,
                exception_type TEXT,
                api_status_code INTEGER,
                api_response_body TEXT,
                retry_count INTEGER DEFAULT 0,
                status TEXT,
                created_at TEXT NOT NULL
            )
        """)
        self.gift_operations_cursor.execute("PRAGMA table_info(redemption_failures)")
        redemption_failure_columns = [column[1] for column in self.gift_operations_cursor.fetchall()]
        if "status" not in redemption_failure_columns:
            self.gift_operations_cursor.execute("ALTER TABLE redemption_failures ADD COLUMN status TEXT")

        # Step 1: unified gift code job tracking.
        # status values used across steps:
        #   pending           - found but not yet attempted (transient; usually flips to auto_succeeded or auto_failed_1 immediately)
        #   auto_failed_1     - failed first automation attempt; retry at next_attempt_at (~24h later)
        #   auto_succeeded    - automation completed successfully
        #   needs_manual      - failed automation twice; awaiting a mod
        #   manual_accepted   - a mod confirmed they applied this code in-game
        #   manual_rejected   - a mod marked this code as not worth applying / invalid
        self.gift_operations_cursor.execute("""
            CREATE TABLE IF NOT EXISTS gift_code_jobs (
                gift_code TEXT NOT NULL,
                alliance_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                next_attempt_at TEXT,
                last_error_reason TEXT,
                completed_at TEXT,
                completed_by INTEGER,
                created_at TEXT NOT NULL,
                PRIMARY KEY (gift_code, alliance_id)
            )
        """)
        self.gift_operations_cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_gift_code_jobs_status ON gift_code_jobs(status)"
        )
        self.gift_operations_cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_gift_code_jobs_guild ON gift_code_jobs(guild_id)"
        )

        self.gift_operations_conn.commit()
        
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS giftcode_channel (
                alliance_id INTEGER,
                channel_id INTEGER,
                PRIMARY KEY (alliance_id)
            )
        """)
        self.conn.commit()
        
        self.wos_player_info_url = "https://wos-giftcode-api.centurygame.com/api/player"
        self.wos_captcha_url = "https://wos-giftcode-api.centurygame.com/api/captcha"
        self.wos_giftcode_url = "https://wos-giftcode-api.centurygame.com/api/gift_code"
        self.wos_giftcode_redemption_url = "https://wos-giftcode.centurygame.com"
        self.wos_encrypt_key = "tB87#kPtkxqOS2"
        self.twocaptcha_api_key = os.getenv("TWOCAPTCHA_API_KEY")
        self.twocaptcha_submit_url = "https://2captcha.com/in.php"
        self.twocaptcha_result_url = "https://2captcha.com/res.php"
        self.twocaptcha_poll_interval = 5
        self.twocaptcha_max_wait = 120
        
        self.retry_config = Retry(
            total=20,
            backoff_factor=1,
            status_forcelist=[429],
            allowed_methods=["POST"]
        )

        self.log_directory = str(LOG_DIR)
        if not os.path.exists(self.log_directory):
            os.makedirs(self.log_directory)

        # Per-alliance scheduler: tracks last run time keyed by alliance_id
        self._last_run: dict[int, float] = {}
        self._alliance_scheduler_lock = asyncio.Lock()
        self.redemption_max_attempts = 3
        self.redemption_base_backoff = 1
        self.redemption_max_backoff = 30
        self.alliance_scheduler.start()
        self.weekly_member_scan.start()

    def cog_unload(self):
        if hasattr(self.api, "cancel"):
            self.api.cancel()
        self.alliance_scheduler.cancel()
        self.weekly_member_scan.cancel()

    def save_redemption_failure(self, details):
        self.gift_operations_cursor.execute(
            """
            INSERT INTO redemption_failures (
                redemption_id, job_type, final_state, gift_code, fid, alliance_id,
                alliance_name, guild_id, error_reason, exception_message,
                exception_type, api_status_code, api_response_body, retry_count, status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                details.get("redemption_id"),
                details.get("job_type", "unknown"),
                details.get("final_state", "failed"),
                details.get("gift_code"),
                details.get("fid"),
                details.get("alliance_id"),
                details.get("alliance_name"),
                details.get("guild_id"),
                details.get("error_reason"),
                details.get("exception_message"),
                details.get("exception_type"),
                details.get("api_status_code"),
                details.get("api_response_body"),
                details.get("retry_count", 0),
                details.get("status"),
                details.get("timestamp"),
            )
        )
        self.gift_operations_conn.commit()

    def get_alliance_log_channel_id(self, alliance_id: int):
        self.settings_cursor.execute(
            "SELECT channel_id FROM alliance_logs WHERE alliance_id = ?",
            (alliance_id,)
        )
        row = self.settings_cursor.fetchone()
        return row[0] if row else None

    async def send_redemption_failure_summary(self, guild, fallback_channel, details):
        channel_id = self.get_alliance_log_channel_id(details.get("alliance_id"))
        channel = guild.get_channel(channel_id) if channel_id else fallback_channel
        if channel is None:
            return
        embed = discord.Embed(
            title="⚠️ Scheduled Gift Redemption Failed",
            color=discord.Color.orange()
        )
        embed.add_field(name="Code", value=f"`{details.get('gift_code')}`", inline=True)
        embed.add_field(name="FID", value=f"`{details.get('fid')}`", inline=True)
        embed.add_field(name="State", value=f"`{details.get('final_state')}`", inline=True)
        embed.add_field(name="Reason", value=f"`{str(details.get('error_reason'))[:900]}`", inline=False)
        embed.add_field(name="HTTP", value=f"`{details.get('api_status_code')}`", inline=True)
        embed.add_field(name="Redemption ID", value=f"`{details.get('redemption_id')}`", inline=False)
        await channel.send(embed=embed)

    def classify_redemption_status(self, details):
        api_status_code = details.get("api_status_code")
        reason = str(details.get("error_reason") or "").lower()
        response_body = str(details.get("api_response_body") or "").lower()
        combined = f"{reason} {response_body}"
        if '"err_code":40008' in response_body or '"msg":"received."' in response_body or "received." in combined:
            return "code_not_claimable"
        if "captcha_solver_failed" in combined or "captcha solver" in combined:
            return "captcha_solver_failed"
        if api_status_code == 429 or "rate limit" in combined or "too many" in combined:
            return "code_rate_limited"
        if any(token in combined for token in ("params error", "invalid", "expired", "depleted", "blocked", "not found", "not exist")):
            return "code_invalid"
        return "member_failed"

    def is_code_terminal_status(self, status: str):
        return status in ("code_invalid", "code_rate_limited", "captcha_solver_failed", "code_not_claimable")

    def has_terminal_code_failure(self, gift_code: str, alliance_id: int, guild_id: int):
        self.gift_operations_cursor.execute(
            """
            SELECT 1
            FROM redemption_failures
            WHERE gift_code = ?
              AND alliance_id = ?
              AND guild_id = ?
              AND status IN ('code_invalid', 'code_rate_limited', 'captcha_solver_failed', 'code_not_claimable')
            LIMIT 1
            """,
            (gift_code, alliance_id, guild_id)
        )
        return self.gift_operations_cursor.fetchone() is not None

    # ---- Step 1: gift_code_jobs helpers ----

    def get_gift_code_job(self, gift_code: str, alliance_id: int):
        """Return the job row for (gift_code, alliance_id), or None if no row exists."""
        self.gift_operations_cursor.execute(
            """
            SELECT gift_code, alliance_id, guild_id, status, attempts,
                   last_attempt_at, next_attempt_at, last_error_reason,
                   completed_at, completed_by, created_at
            FROM gift_code_jobs
            WHERE gift_code = ? AND alliance_id = ?
            """,
            (gift_code, alliance_id),
        )
        row = self.gift_operations_cursor.fetchone()
        if not row:
            return None
        columns = [
            "gift_code", "alliance_id", "guild_id", "status", "attempts",
            "last_attempt_at", "next_attempt_at", "last_error_reason",
            "completed_at", "completed_by", "created_at",
        ]
        return dict(zip(columns, row))

    def should_skip_code_for_alliance(self, gift_code: str, alliance_id: int) -> bool:
        """Step 1 rule: if a job row exists at all for this (code, alliance), skip it.
        Step 2 will refine this to honor next_attempt_at and needs_manual handoff."""
        return self.get_gift_code_job(gift_code, alliance_id) is not None

    def record_gift_code_job_attempt(
        self,
        gift_code: str,
        alliance_id: int,
        guild_id: int,
        status: str,
        error_reason: str = None,
    ):
        """Insert or update the job row for this (code, alliance).
        Called once per scheduler/on_message attempt so we never re-attempt the same code."""
        now_iso = datetime.utcnow().isoformat()
        existing = self.get_gift_code_job(gift_code, alliance_id)
        if existing is None:
            self.gift_operations_cursor.execute(
                """
                INSERT INTO gift_code_jobs (
                    gift_code, alliance_id, guild_id, status, attempts,
                    last_attempt_at, last_error_reason, created_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (gift_code, alliance_id, guild_id, status, now_iso, error_reason, now_iso),
            )
        else:
            self.gift_operations_cursor.execute(
                """
                UPDATE gift_code_jobs
                SET status = ?,
                    attempts = attempts + 1,
                    last_attempt_at = ?,
                    last_error_reason = ?
                WHERE gift_code = ? AND alliance_id = ?
                """,
                (status, now_iso, error_reason, gift_code, alliance_id),
            )
        self.gift_operations_conn.commit()

    # ---- end Step 1 helpers ----

    @tasks.loop(seconds=60)
    async def alliance_scheduler(self):
        """Runs every 60 seconds. For each alliance, checks if its refresh_rate has elapsed
        since last run, then scans its gift code channel and redeems any found codes."""
        if self._alliance_scheduler_lock.locked():
            print("[SCHEDULER] Previous alliance_scheduler run still active, skipping overlapping pass")
            return

        async with self._alliance_scheduler_lock:
            await self._run_alliance_scheduler()

    async def _run_alliance_scheduler(self):
        try:
            now = asyncio.get_event_loop().time()
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name, discord_server_id, refresh_rate,
                       gift_code_channel_id, results_channel_id
                FROM alliance_list
                WHERE gift_code_channel_id IS NOT NULL
                  AND refresh_rate IS NOT NULL
                  AND refresh_rate > 0
                """
            )
            alliances = self.alliance_cursor.fetchall()

            for alliance_id, name, guild_id, refresh_rate, gift_channel_id, results_channel_id in alliances:
                last_run = self._last_run.get(alliance_id, 0)
                if now - last_run < refresh_rate:
                    continue

                self._last_run[alliance_id] = now
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    print(f"[SCHEDULER] Guild {guild_id} not found for alliance {alliance_id}, skipping")
                    continue

                gift_channel = guild.get_channel(gift_channel_id)
                if gift_channel is None:
                    print(f"[SCHEDULER] Gift code channel {gift_channel_id} not found for alliance {alliance_id}, skipping")
                    continue

                results_channel = guild.get_channel(results_channel_id) if results_channel_id else gift_channel

                print(f"[SCHEDULER] Scanning alliance_id={alliance_id} name={name} channel={gift_channel_id}")

                found_codes = []
                async for message in gift_channel.history(limit=200):
                    code = self.extract_auto_gift_code(message.content)
                    if code and code not in found_codes:
                        found_codes.append(code)
                        if len(found_codes) >= 5:
                            break

                if not found_codes:
                    print(f"[SCHEDULER] No codes found for alliance_id={alliance_id}")
                    continue

                # Step 1: filter out codes we've already recorded a job for on this alliance.
                # This stops the bot from re-attempting the same code every cycle.
                unprocessed_codes = [
                    c for c in found_codes
                    if not self.should_skip_code_for_alliance(c, alliance_id)
                ]
                skipped_already_processed = len(found_codes) - len(unprocessed_codes)
                if skipped_already_processed:
                    print(
                        f"[SCHEDULER] alliance_id={alliance_id} "
                        f"skipped_already_processed={skipped_already_processed} "
                        f"unprocessed_remaining={len(unprocessed_codes)}"
                    )
                if not unprocessed_codes:
                    print(f"[SCHEDULER] alliance_id={alliance_id} all_found_codes_already_processed")
                    continue
                found_codes = unprocessed_codes

                # Redeem only for this specific alliance
                with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
                    users_cursor = users_conn.cursor()
                    users_cursor.execute("SELECT fid FROM users WHERE alliance = ?", (alliance_id,))
                    members = users_cursor.fetchall()

                if not members:
                    print(f"[SCHEDULER] No members for alliance_id={alliance_id}, skipping")
                    continue

                total_success = 0
                failed_member_codes = 0
                failed_request_attempts = 0
                final_failed_jobs = 0
                failure_details = []
                skipped_codes = 0
                skipped_code_details = []
                already_redeemed_members = 0
                processed_pairs = set()
                for gift_code in found_codes:
                    if self.has_terminal_code_failure(gift_code, alliance_id, guild_id):
                        skipped_codes += 1
                        skipped_code_details.append(gift_code)
                        print(f"[SCHEDULER-SKIP] code={gift_code} alliance_id={alliance_id} reason=terminal_code_failure")
                        continue
                    first_fid = members[0][0]
                    if (gift_code, first_fid) in processed_pairs:
                        print(f"[SCHEDULER-FIRST-REDEEM] code={gift_code} fid={first_fid} status=skipped_duplicate_pair")
                        continue
                    processed_pairs.add((gift_code, first_fid))
                    print(f"[SCHEDULER-FIRST-REDEEM] code={gift_code} fid={first_fid} status=starting")
                    ok, result = await self.redeem_gift_code_for_fid(first_fid, gift_code)
                    # Step 1: record this (code, alliance) so we never retry it on the next tick.
                    # Step 2 will refine this with 24h retry logic.
                    if ok:
                        self.record_gift_code_job_attempt(
                            gift_code=gift_code,
                            alliance_id=alliance_id,
                            guild_id=guild_id,
                            status="auto_succeeded",
                        )
                        total_success += 1
                        print(f"[SCHEDULER-FIRST-REDEEM] code={gift_code} fid={first_fid} status=member_redeemed action=continue_member_fanout")
                        member_iterable = members[1:]
                    else:
                        failed_member_codes += 1
                        final_failed_jobs += 1
                        details = result if isinstance(result, dict) else {
                            "error_reason": str(result),
                            "gift_code": gift_code,
                            "fid": first_fid,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        status = self.classify_redemption_status(details)
                        if status == "code_not_claimable":
                            already_redeemed_members += 1
                        details.update({
                            "job_type": "scheduled",
                            "final_state": "job_failed_final" if self.is_code_terminal_status(status) else "member_failed",
                            "status": status,
                            "alliance_id": alliance_id,
                            "alliance_name": name,
                            "guild_id": guild_id,
                        })
                        failed_request_attempts += details.get("request_attempts", 1)
                        self.save_redemption_failure(details)
                        failure_details.append(details)
                        # Step 1: record the failure so we don't retry this same (code, alliance) next tick.
                        # In Step 2, "auto_failed_1" will get a 24h retry; for now it just blocks re-attempts.
                        self.record_gift_code_job_attempt(
                            gift_code=gift_code,
                            alliance_id=alliance_id,
                            guild_id=guild_id,
                            status="auto_failed_1",
                            error_reason=details.get("error_reason"),
                        )
                        print(f"[SCHEDULER-FIRST-REDEEM] code={gift_code} fid={first_fid} status={status}")
                        print(f"[SCHEDULER-REDEEM-FAIL] {json.dumps(details, ensure_ascii=False)}")
                        await self.send_redemption_failure_summary(guild, results_channel, details)
                        if self.is_code_terminal_status(status):
                            print(f"[SCHEDULER-FIRST-REDEEM] code={gift_code} status={status} action=stop_member_fanout")
                            await asyncio.sleep(1)
                            continue
                        member_iterable = members[1:]

                    for (fid,) in member_iterable:
                        if (gift_code, fid) in processed_pairs:
                            print(f"[SCHEDULER-REDEEM] code={gift_code} fid={fid} status=skipped_duplicate_pair")
                            continue
                        processed_pairs.add((gift_code, fid))
                        ok, result = await self.redeem_gift_code_for_fid(fid, gift_code)
                        if ok:
                            total_success += 1
                            print(f"[SCHEDULER-REDEEM] code={gift_code} fid={fid} status=member_redeemed")
                        else:
                            failed_member_codes += 1
                            final_failed_jobs += 1
                            details = result if isinstance(result, dict) else {
                                "error_reason": str(result),
                                "gift_code": gift_code,
                                "fid": fid,
                                "timestamp": datetime.utcnow().isoformat()
                            }
                            status = self.classify_redemption_status(details)
                            if status == "code_not_claimable":
                                already_redeemed_members += 1
                            failed_request_attempts += details.get("request_attempts", 1)
                            details.update({
                                "job_type": "scheduled",
                                "final_state": "job_failed_final" if self.is_code_terminal_status(status) else "member_failed",
                                "status": status,
                                "alliance_id": alliance_id,
                                "alliance_name": name,
                                "guild_id": guild_id,
                            })
                            self.save_redemption_failure(details)
                            failure_details.append(details)
                            print(f"[SCHEDULER-REDEEM-FAIL] {json.dumps(details, ensure_ascii=False)}")
                            await self.send_redemption_failure_summary(guild, results_channel, details)
                            if self.is_code_terminal_status(status):
                                print(f"[SCHEDULER-REDEEM] code={gift_code} status={status} action=stop_member_fanout")
                                await asyncio.sleep(1)
                                break
                        await asyncio.sleep(1)

                embed = discord.Embed(
                    title="⏰ Scheduled Gift Code Redemption",
                    description=f"Alliance: `{name}`",
                    color=discord.Color.green() if final_failed_jobs == 0 else discord.Color.orange()
                )
                embed.add_field(name="Codes Found", value=f"`{len(found_codes)}`", inline=True)
                embed.add_field(name="Members Processed", value=f"`{len(members)}`", inline=True)
                embed.add_field(name="Succeeded", value=f"`{total_success}`", inline=True)
                embed.add_field(name="Code Skipped", value=f"`{skipped_codes}`", inline=True)
                embed.add_field(name="Already Redeemed", value=f"`{already_redeemed_members}`", inline=True)
                embed.add_field(name="Failed Member/Codes", value=f"`{failed_member_codes}`", inline=True)
                embed.add_field(name="Failed Request Attempts", value=f"`{failed_request_attempts}`", inline=True)
                embed.add_field(name="Final Failed Jobs", value=f"`{final_failed_jobs}`", inline=True)
                if skipped_code_details:
                    skipped_preview = "\n".join(
                        f"Code `{code}`: `Code skipped for all members.`"
                        for code in skipped_code_details[:5]
                    )
                    embed.add_field(name="Skipped Codes", value=skipped_preview, inline=False)
                if failure_details:
                    preview = "\n".join(
                        f"FID `{item.get('fid')}`: `{str(item.get('error_reason'))[:80]}`"
                        for item in failure_details[:5]
                    )
                    embed.add_field(name="Failure Details", value=preview, inline=False)
                await results_channel.send(embed=embed)

        except Exception as e:
            print(f"[SCHEDULER] Error in alliance_scheduler: {e}")
            traceback.print_exc()

    @alliance_scheduler.before_loop
    async def before_alliance_scheduler(self):
        await self.bot.wait_until_ready()

    def upsert_scanned_member(self, fid, nickname, furnace_lv, kid, stove_lv_content, alliance_id):
        with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
            users_conn.execute(
                """
                INSERT INTO users (fid, nickname, furnace_lv, kid, stove_lv_content, alliance)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(fid) DO UPDATE SET
                    nickname = excluded.nickname,
                    furnace_lv = excluded.furnace_lv,
                    kid = excluded.kid,
                    stove_lv_content = excluded.stove_lv_content,
                    alliance = excluded.alliance
                """,
                (fid, nickname, furnace_lv, kid, stove_lv_content, alliance_id)
            )
            users_conn.commit()

    async def run_member_scan(self, label: str = "Weekly"):
        """Runs the member scan for all alliances with a results channel. Called by scheduler and manual trigger."""
        now = datetime.utcnow()
        print(f"[{label.upper()} SCAN] Starting member scan at {now}")
        try:
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name, discord_server_id, results_channel_id
                FROM alliance_list
                WHERE results_channel_id IS NOT NULL
                """
            )
            alliances = self.alliance_cursor.fetchall()

            for alliance_id, alliance_name, guild_id, results_channel_id in alliances:
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    print(f"[{label.upper()} SCAN] Guild {guild_id} not found for alliance {alliance_id}, skipping")
                    continue

                results_channel = guild.get_channel(results_channel_id)
                if results_channel is None:
                    print(f"[{label.upper()} SCAN] Results channel {results_channel_id} not found for alliance {alliance_id}, skipping")
                    continue

                with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
                    users_cursor = users_conn.cursor()
                    users_cursor.execute(
                        "SELECT fid, nickname, furnace_lv, kid, stove_lv_content FROM users WHERE alliance = ?",
                        (alliance_id,)
                    )
                    members = users_cursor.fetchall()

                if not members:
                    print(f"[{label.upper()} SCAN] No members for alliance {alliance_id}, skipping")
                    continue

                name_changes = []
                furnace_changes = []
                errors = []

                for fid, old_nickname, old_furnace_lv, old_kid, old_stove_lv_content in members:
                    try:
                        time_val = int(datetime.utcnow().timestamp())
                        form = f"fid={fid}&time={time_val}"
                        sign = hashlib.md5((form + self.wos_encrypt_key).encode('utf-8')).hexdigest()
                        form_data = f"fid={fid}&sign={sign}&time={time_val}"
                        headers = {
                            "accept": "application/json, text/plain, */*",
                            "content-type": "application/x-www-form-urlencoded",
                            "origin": self.wos_giftcode_redemption_url,
                            "referer": f"{self.wos_giftcode_redemption_url}/",
                            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        }
                        ssl_context = ssl.create_default_context()
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE

                        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                            async with session.post(self.wos_player_info_url, headers=headers, data=form_data) as response:
                                data = await response.json()

                        player = data.get('data', {})
                        new_nickname = player.get('nickname')
                        new_furnace_lv = player.get('stove_lv')
                        new_kid = player.get('kid')
                        new_stove_lv_content = player.get('stove_lv_content')

                        if new_nickname and new_nickname != old_nickname:
                            name_changes.append((fid, old_nickname, new_nickname))
                        if new_furnace_lv is not None and new_furnace_lv != old_furnace_lv:
                            furnace_changes.append((fid, old_furnace_lv, new_furnace_lv))

                        self.upsert_scanned_member(
                            fid,
                            new_nickname or old_nickname,
                            new_furnace_lv if new_furnace_lv is not None else old_furnace_lv,
                            new_kid if new_kid is not None else old_kid,
                            new_stove_lv_content or old_stove_lv_content,
                            alliance_id
                        )

                        await asyncio.sleep(1)

                    except Exception as e:
                        print(f"[{label.upper()} SCAN] Error fetching fid={fid}: {e}")
                        errors.append(fid)

                embed = discord.Embed(
                    title=f"📊 {label} Member Scan — {alliance_name}",
                    description=f"Scan completed for `{len(members)}` members.",
                    color=discord.Color.blue()
                )
                if name_changes:
                    name_lines = "\n".join(f"FID `{fid}`: `{old}` → `{new}`" for fid, old, new in name_changes[:20])
                    embed.add_field(name=f"✏️ Name Changes ({len(name_changes)})", value=name_lines, inline=False)
                else:
                    embed.add_field(name="✏️ Name Changes", value="None", inline=False)
                if furnace_changes:
                    furnace_lines = "\n".join(f"FID `{fid}`: Lv `{old}` → Lv `{new}`" for fid, old, new in furnace_changes[:20])
                    embed.add_field(name=f"🔥 Furnace Changes ({len(furnace_changes)})", value=furnace_lines, inline=False)
                else:
                    embed.add_field(name="🔥 Furnace Changes", value="None", inline=False)
                if errors:
                    embed.add_field(name="⚠️ Errors", value=f"`{len(errors)}` members could not be fetched", inline=False)
                embed.set_footer(text=f"Scan time: {now.strftime('%Y-%m-%d %H:%M UTC')}")
                await results_channel.send(embed=embed)
                print(f"[{label.upper()} SCAN] Done for alliance {alliance_id} — {len(name_changes)} name changes, {len(furnace_changes)} furnace changes")

        except Exception as e:
            print(f"[{label.upper()} SCAN] Fatal error: {e}")
            traceback.print_exc()

    @tasks.loop(hours=1)
    async def weekly_member_scan(self):
        """Runs every hour but only executes on Sunday at 00:00 UTC."""
        now = datetime.utcnow()
        if not (now.weekday() == 6 and now.hour == 0):
            return
        await self.run_member_scan(label="Weekly")

    @weekly_member_scan.before_loop
    async def before_weekly_member_scan(self):
        await self.bot.wait_until_ready()

    async def show_gift_menu(self, interaction: discord.Interaction):
        gift_menu_embed = discord.Embed(
            title="🎁 Gift Redemption",
            description=(
                "Please select an operation:\n\n"
                "**Available Operations**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "✍️ **Manual Gift Code**\n"
                "└ Enter a gift code and redeem it for each FID in the selected alliance\n\n"
                "� **Scan Last 5 Codes**\n"
                "└ Scan backward until 5 valid gift codes are found, then redeem each code for each FID once\n\n"
                "⏱️ **Scheduled Redemption**\n"
                "└ Configure scheduled gift code scanning and redemption intervals\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.gold()
        )
        
        view = GiftMenuView(self)
        await interaction.response.edit_message(embed=gift_menu_embed, view=view)

    async def show_create_gift_code_modal(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "mod"):
            await interaction.response.send_message("❌ You don't have permission to use this feature.", ephemeral=True)
            return

        await interaction.response.send_modal(CreateGiftCodeModal(self))

    async def show_auto_gift_settings(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        self.gift_operations_cursor.execute(
            "SELECT channel_id, results_channel_id FROM auto_gift_settings WHERE guild_id = ?",
            (interaction.guild_id,)
        )
        channel_row = self.gift_operations_cursor.fetchone()
        channel_text = f"<#{channel_row[0]}>" if channel_row and channel_row[0] else "`Not set`"
        results_channel_text = f"<#{channel_row[1]}>" if channel_row and channel_row[1] else "`Not set`"

        self.alliance_cursor.execute(
            """
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
            """,
            (interaction.guild_id,)
        )
        alliances = self.alliance_cursor.fetchall()
        enabled_alliances = self.get_auto_gift_enabled_alliances(interaction.guild_id, alliances)

        embed = discord.Embed(
            title="⏱️ Scheduled Redemption Settings",
            description=(
                "**Available Options**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📢 **Set Gift Code Channel**\n"
                "└ Save the channel used for gift code scanning\n\n"
                "📊 **Set Results Channel**\n"
                "└ Save the channel used for redemption results\n\n"
                "🛡️ **Configure Alliances**\n"
                "└ Toggle which alliances participate in scheduled redemption\n\n"
                "🔍 **Scan Last 5 Codes**\n"
                "└ Scan backward until 5 valid gift codes are found\n\n"
                "⏲️ **Redemption Intervals**\n"
                "└ 6h, 12h, 24h, 48h, 72h, 7d\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.gold()
        )
        embed.add_field(name="Gift Code Channel", value=channel_text, inline=False)
        embed.add_field(name="Results Channel", value=results_channel_text, inline=False)
        embed.add_field(name="Enabled Alliances", value=f"`{len(enabled_alliances)}` / `{len(alliances)}`", inline=False)
        await interaction.response.send_message(embed=embed, view=AutoGiftSettingsView(self), ephemeral=True)

    def get_auto_gift_enabled_alliances(self, guild_id: int, alliances):
        all_alliance_ids = [alliance_id for alliance_id, _ in alliances]
        self.gift_operations_cursor.execute(
            "SELECT alliance_id FROM auto_gift_alliances WHERE guild_id = ?",
            (guild_id,)
        )
        rows = self.gift_operations_cursor.fetchall()
        if not rows:
            return all_alliance_ids
        return [row[0] for row in rows]

    async def save_auto_gift_channel(self, interaction: discord.Interaction, channel):
        self.gift_operations_cursor.execute(
            """
            INSERT OR REPLACE INTO auto_gift_settings (guild_id, channel_id)
            VALUES (?, ?)
            """,
            (interaction.guild_id, channel.id)
        )
        self.gift_operations_conn.commit()
        embed = discord.Embed(
            title="✅ Gift Code Channel Updated",
            description=f"Auto gift codes will now be read from {channel.mention}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Channel", value=channel.name, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def save_auto_gift_results_channel(self, interaction: discord.Interaction, channel):
        self.gift_operations_cursor.execute(
            """
            INSERT INTO auto_gift_settings (guild_id, results_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET results_channel_id = excluded.results_channel_id
            """,
            (interaction.guild_id, channel.id)
        )
        self.gift_operations_conn.commit()
        embed = discord.Embed(
            title="✅ Results Channel Updated",
            description=f"Auto gift redemption results will now be posted in {channel.mention}.",
            color=discord.Color.green()
        )
        embed.add_field(name="Channel", value=channel.name, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def show_auto_gift_alliance_select(self, interaction: discord.Interaction):
        self.alliance_cursor.execute(
            """
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
            """,
            (interaction.guild_id,)
        )
        alliances = self.alliance_cursor.fetchall()

        if not alliances:
            await interaction.response.send_message("❌ No alliances found for this server.", ephemeral=True)
            return

        enabled_alliances = self.get_auto_gift_enabled_alliances(interaction.guild_id, alliances)
        embed = discord.Embed(
            title="🛡️ Configure Auto Gift Alliances",
            description="Select the alliances that should participate in auto-redemption.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(
            embed=embed,
            view=AutoGiftAllianceSelectView(self, alliances, enabled_alliances),
            ephemeral=True
        )

    async def save_auto_gift_alliances(self, interaction: discord.Interaction, alliance_ids):
        self.gift_operations_cursor.execute(
            "DELETE FROM auto_gift_alliances WHERE guild_id = ?",
            (interaction.guild_id,)
        )
        self.gift_operations_cursor.executemany(
            """
            INSERT OR IGNORE INTO auto_gift_alliances (guild_id, alliance_id)
            VALUES (?, ?)
            """,
            [(interaction.guild_id, alliance_id) for alliance_id in alliance_ids]
        )
        self.gift_operations_conn.commit()
        await interaction.response.send_message(f"✅ Auto gift alliances updated. Enabled: `{len(alliance_ids)}`.", ephemeral=True)

    def extract_auto_gift_code(self, content: str):
        content = content.strip()
        if not content:
            return None

        code_match = re.search(r"Code:\s*(\S+)", content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()

        if re.fullmatch(r"[A-Za-z0-9]+", content):
            return content

        return None

    def get_auto_gift_channel_id(self, guild_id: int):
        self.gift_operations_cursor.execute(
            "SELECT channel_id FROM auto_gift_settings WHERE guild_id = ?",
            (guild_id,)
        )
        row = self.gift_operations_cursor.fetchone()
        return row[0] if row else None

    def get_auto_gift_results_channel_id(self, guild_id: int):
        self.gift_operations_cursor.execute(
            "SELECT results_channel_id FROM auto_gift_settings WHERE guild_id = ?",
            (guild_id,)
        )
        row = self.gift_operations_cursor.fetchone()
        return row[0] if row else None

    def get_guild_alliances(self, guild_id: int):
        self.alliance_cursor.execute(
            """
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
            """,
            (guild_id,)
        )
        return self.alliance_cursor.fetchall()

    def get_enabled_auto_gift_alliances_for_guild(self, guild_id: int):
        alliances = self.get_guild_alliances(guild_id)
        self.gift_operations_cursor.execute(
            "SELECT alliance_id FROM auto_gift_alliances WHERE guild_id = ?",
            (guild_id,)
        )
        enabled_rows = self.gift_operations_cursor.fetchall()

        if not enabled_rows:
            return alliances

        enabled_ids = {row[0] for row in enabled_rows}
        return [(alliance_id, name) for alliance_id, name in alliances if alliance_id in enabled_ids]

    def get_auto_gift_results_channel(self, guild: discord.Guild, fallback_channel):
        results_channel_id = self.get_auto_gift_results_channel_id(guild.id)
        results_channel = guild.get_channel(results_channel_id) if results_channel_id else fallback_channel
        if results_channel is None:
            results_channel = fallback_channel
        return results_channel

    async def redeem_auto_gift_codes(self, guild_id: int, gift_codes):
        alliances = self.get_enabled_auto_gift_alliances_for_guild(guild_id)
        total_success = 0
        total_failed = 0
        processed_alliances = 0
        processed_codes = 0

        for gift_code in gift_codes:
            processed_codes += 1
            for alliance_id, alliance_name in alliances:
                if self.has_terminal_code_failure(gift_code, alliance_id, guild_id):
                    print(f"[AUTO-GIFT-SKIP] code={gift_code} alliance_id={alliance_id} reason=terminal_code_failure")
                    continue
                with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
                    users_cursor = users_conn.cursor()
                    users_cursor.execute("SELECT fid FROM users WHERE alliance = ?", (alliance_id,))
                    members = users_cursor.fetchall()

                if members:
                    processed_alliances += 1

                for (fid,) in members:
                    ok, result = await self.redeem_gift_code_for_fid(fid, gift_code)
                    if ok:
                        total_success += 1
                        print(f"[AUTO-GIFT] SUCCESS fid={fid} code={gift_code}")
                    else:
                        total_failed += 1
                        print(f"[AUTO-GIFT] FAIL fid={fid} code={gift_code} reason={result}")
                        status = self.classify_redemption_status(result if isinstance(result, dict) else {"error_reason": str(result)})
                        if self.is_code_terminal_status(status):
                            print(f"[AUTO-GIFT] code={gift_code} status={status} action=stop_member_fanout")
                            break
                    await asyncio.sleep(1)

        return {
            "alliances": alliances,
            "processed_codes": processed_codes,
            "processed_alliances": processed_alliances,
            "total_success": total_success,
            "total_failed": total_failed
        }

    async def scan_gift_code_channel(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        configured_channel_id = self.get_auto_gift_channel_id(interaction.guild_id)
        if not configured_channel_id:
            await interaction.response.send_message("❌ Gift code channel is not configured.", ephemeral=True)
            return

        gift_channel = interaction.guild.get_channel(configured_channel_id)
        if gift_channel is None:
            await interaction.response.send_message("❌ Configured gift code channel was not found.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        found_codes = []
        async for message in gift_channel.history(limit=200):
            gift_code = self.extract_auto_gift_code(message.content)
            if gift_code and gift_code not in found_codes:
                found_codes.append(gift_code)
                if len(found_codes) >= 5:
                    break

        results_channel = self.get_auto_gift_results_channel(interaction.guild, gift_channel)

        if not found_codes:
            embed = discord.Embed(
                title="🔍 Gift Code Channel Scan Complete",
                description="No valid gift codes were found while scanning recent messages.",
                color=discord.Color.orange()
            )
            await results_channel.send(embed=embed)
            await interaction.followup.send("✅ Scan complete. No gift codes found.", ephemeral=True)
            return

        results = await self.redeem_auto_gift_codes(interaction.guild_id, found_codes)
        embed = discord.Embed(
            title="🔍 Gift Code Channel Scan Complete",
            color=discord.Color.green() if results["total_failed"] == 0 else discord.Color.orange()
        )
        embed.add_field(name="Codes Found", value=f"`{len(found_codes)}`", inline=True)
        embed.add_field(name="Codes Processed", value=f"`{results['processed_codes']}`", inline=True)
        embed.add_field(name="Total Succeeded", value=f"`{results['total_success']}`", inline=True)
        embed.add_field(name="Total Failed", value=f"`{results['total_failed']}`", inline=True)
        await results_channel.send(embed=embed)
        await interaction.followup.send("✅ Gift code channel scan complete.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        try:
            configured_channel_id = self.get_auto_gift_channel_id(message.guild.id)
            if not configured_channel_id or message.channel.id != configured_channel_id:
                return

            gift_code = self.extract_auto_gift_code(message.content)
            if not gift_code:
                return

            results_channel = self.get_auto_gift_results_channel(message.guild, message.channel)
            results = await self.redeem_auto_gift_codes(message.guild.id, [gift_code])
            if not results["alliances"]:
                await results_channel.send("❌ No enabled alliances found for auto gift redemption.")
                return

            embed = discord.Embed(
                title="🎁 Auto Gift Code Redemption Complete",
                color=discord.Color.green() if results["total_failed"] == 0 else discord.Color.orange()
            )
            embed.add_field(name="Gift Code Used", value=f"`{gift_code}`", inline=False)
            embed.add_field(name="Alliances Processed", value=f"`{results['processed_alliances']}`", inline=True)
            embed.add_field(name="Total Succeeded", value=f"`{results['total_success']}`", inline=True)
            embed.add_field(name="Total Failed", value=f"`{results['total_failed']}`", inline=True)
            await results_channel.send(embed=embed)

        except Exception as e:
            print(f"[ERROR] Auto gift code redemption failed: {e}")
            traceback.print_exc()

    async def get_alliance_by_input(self, alliance_value: str, guild_id: int):
        if alliance_value.isdigit():
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name
                FROM alliance_list
                WHERE alliance_id = ? AND discord_server_id = ?
                """,
                (int(alliance_value), guild_id)
            )
        else:
            self.alliance_cursor.execute(
                """
                SELECT alliance_id, name
                FROM alliance_list
                WHERE LOWER(name) = LOWER(?) AND discord_server_id = ?
                """,
                (alliance_value, guild_id)
            )
        return self.alliance_cursor.fetchone()

    def get_gift_code_failure_reason(self, data):
        if not isinstance(data, dict):
            return "WOS rejected the request, but the response format was invalid."

        msg = str(data.get("msg") or "").strip()
        err_code = data.get("err_code")

        if err_code == 40008 or msg.upper() == "RECEIVED.":
            return "Code not claimable for this FID (already redeemed, expired, or otherwise rejected by WOS)."

        reason_mapping = {
            "same gift code": "Already redeemed",
            "expired": "Code expired",
            "params error": "Request error (params)",
            "gift code not found": "Invalid code",
            "not login.": "WOS session/login required before redemption.",
            "captcha check error.": "Captcha verification failed.",
        }

        normalized_msg = msg.lower()
        if normalized_msg in reason_mapping:
            return reason_mapping[normalized_msg]

        if msg:
            return f"WOS rejected the request: {msg}"

        if err_code is not None:
            return f"WOS rejected the request with err_code {err_code}."

        return "WOS rejected the request, but no detailed reason was provided."

    def build_wos_form_sign(self, form: str):
        return hashlib.md5((form + self.wos_encrypt_key).encode('utf-8')).hexdigest()

    def build_wos_headers(self):
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://wos-giftcode.centurygame.com",
            "pragma": "no-cache",
            "referer": "https://wos-giftcode.centurygame.com/",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0",
        }

    def extract_captcha_image_base64(self, captcha_response):
        if not isinstance(captcha_response, dict) or not isinstance(captcha_response.get("data"), dict):
            return None
        image_data = captcha_response["data"].get("img")
        if not isinstance(image_data, str):
            return None
        if "," in image_data and "base64" in image_data[:50]:
            image_data = image_data.split(",", 1)[1]
        try:
            decoded = base64.b64decode(image_data, validate=True)
        except Exception:
            return None
        if len(decoded) < 100:
            return None
        return image_data

    async def fetch_wos_player_info_for_redemption(self, session, fid_value: str, headers: dict):
        time_val = str(int(datetime.now().timestamp()))
        form = f"fid={fid_value}&time={time_val}"
        payload = {
            "fid": fid_value,
            "sign": self.build_wos_form_sign(form),
            "time": time_val,
        }
        async with session.post(self.wos_player_info_url, headers=headers, data=payload) as response:
            response_text = await response.text()
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            print(f"[WOS-PLAYER-ERROR] invalid_json body={response_text}")
            return None, "wos_player_failed: invalid player JSON"
        if data.get("code") != 0:
            print(f"[WOS-PLAYER-ERROR] response={json.dumps(data, ensure_ascii=False)}")
            return None, f"wos_player_failed: {data.get('msg')}"
        return data.get("data", {}), None

    async def fetch_wos_captcha_image_base64(self, session, fid_value: str, headers: dict):
        time_val = str(int(datetime.now().timestamp() * 1000))
        form = f"fid={fid_value}&init=0&time={time_val}"
        payload = {
            "fid": fid_value,
            "sign": self.build_wos_form_sign(form),
            "time": time_val,
            "init": "0",
        }
        async with session.post(self.wos_captcha_url, headers=headers, data=payload) as response:
            response_text = await response.text()
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            print(f"[WOS-CAPTCHA-ERROR] invalid_json body={response_text}")
            return None, "wos_captcha_failed: invalid captcha JSON"
        if data.get("code") != 0:
            print(f"[WOS-CAPTCHA-ERROR] response={json.dumps(data, ensure_ascii=False)}")
            return None, f"wos_captcha_failed: {data.get('msg')}"
        captcha_base64 = self.extract_captcha_image_base64(data)
        if not captcha_base64:
            print(f"[WOS-CAPTCHA-ERROR] image_missing response={json.dumps(data, ensure_ascii=False)}")
            return None, "wos_captcha_failed: captcha image missing"
        return captcha_base64, None

    async def solve_captcha_with_2captcha(self, session, captcha_base64: str):
        if not self.twocaptcha_api_key:
            return None, "captcha_solver_failed: TWOCAPTCHA_API_KEY missing"
        submit_payload = {
            "key": self.twocaptcha_api_key,
            "method": "base64",
            "body": captcha_base64,
            "json": 1,
        }
        async with session.post(self.twocaptcha_submit_url, data=submit_payload) as response:
            submit_text = await response.text()
        try:
            submit_data = json.loads(submit_text)
        except json.JSONDecodeError:
            return None, "captcha_solver_failed: 2Captcha submit invalid JSON"
        if submit_data.get("status") != 1:
            return None, f"captcha_solver_failed: 2Captcha submit {submit_data.get('request')}"

        captcha_id = submit_data.get("request")
        deadline = asyncio.get_event_loop().time() + self.twocaptcha_max_wait
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(self.twocaptcha_poll_interval)
            result_params = {
                "key": self.twocaptcha_api_key,
                "action": "get",
                "id": captcha_id,
                "json": 1,
            }
            async with session.get(self.twocaptcha_result_url, params=result_params) as response:
                result_text = await response.text()
            try:
                result_data = json.loads(result_text)
            except json.JSONDecodeError:
                return None, "captcha_solver_failed: 2Captcha poll invalid JSON"
            if result_data.get("status") == 1:
                return result_data.get("request"), None
            if result_data.get("request") != "CAPCHA_NOT_READY":
                return None, f"captcha_solver_failed: 2Captcha poll {result_data.get('request')}"
        return None, "captcha_solver_failed: 2Captcha timeout"

    def build_captcha_solver_failed_result(self, fid: int, gift_code: str, redemption_id: str, reason: str):
        result = self.build_redemption_result(
            fid=fid,
            gift_code=gift_code,
            redemption_id=redemption_id,
            success=False,
            status="captcha_solver_failed",
            attempts_used=0,
            retry_after_used=False,
            final_error_reason=reason,
            api_status_code=None,
            api_response_body=None,
        )
        result["final_state"] = "failed"
        return result

    async def show_gift_code_alliance_select(self, interaction: discord.Interaction, gift_code: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ This can only be used in a server.", ephemeral=True)
            return

        self.alliance_cursor.execute(
            """
            SELECT alliance_id, name
            FROM alliance_list
            WHERE discord_server_id = ?
            ORDER BY name
            """,
            (interaction.guild_id,)
        )
        alliances = self.alliance_cursor.fetchall()

        if not alliances:
            await interaction.response.send_message("❌ No alliances found for this server.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎁 Select Alliance",
            description=f"Select the alliance to redeem `{gift_code}` for.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(
            embed=embed,
            view=GiftCodeAllianceSelectView(self, gift_code, alliances),
            ephemeral=True
        )

    async def redeem_gift_code_for_fid(self, fid: int, gift_code: str):
        time_val = str(int(datetime.now().timestamp()))
        fid_value = str(fid)
        redemption_id = f"{gift_code}:{fid}:{time_val}"
        headers = self.build_wos_headers()

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        if not self.twocaptcha_api_key:
            return False, self.build_captcha_solver_failed_result(
                fid,
                gift_code,
                redemption_id,
                "captcha_solver_failed: TWOCAPTCHA_API_KEY missing",
            )

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            player_data, player_error = await self.fetch_wos_player_info_for_redemption(session, fid_value, headers)
            if player_error:
                return False, self.build_captcha_solver_failed_result(fid, gift_code, redemption_id, player_error)

            captcha_base64, captcha_error = await self.fetch_wos_captcha_image_base64(session, fid_value, headers)
            if captcha_error:
                return False, self.build_captcha_solver_failed_result(fid, gift_code, redemption_id, captcha_error)

            captcha_solution, solver_error = await self.solve_captcha_with_2captcha(session, captcha_base64)
            if solver_error or not captcha_solution:
                return False, self.build_captcha_solver_failed_result(
                    fid,
                    gift_code,
                    redemption_id,
                    solver_error or "captcha_solver_failed: empty 2Captcha solution",
                )

            form = f"captcha_code={captcha_solution}&cdk={gift_code}&fid={fid_value}&time={time_val}"
            sign = self.build_wos_form_sign(form)
            form_data = {"cdk": gift_code, "fid": fid_value, "time": time_val, "sign": sign, "captcha_code": captcha_solution}

            self.log_redemption_request_shape(gift_code, fid, self.wos_giftcode_url, form_data, headers)

            return await self.request_redemption_with_backoff(
                session=session,
                fid=fid,
                gift_code=gift_code,
                form_data=form_data,
                headers=headers,
                redemption_id=redemption_id,
            )

    async def request_redemption_with_backoff(self, session: aiohttp.ClientSession, fid: int, gift_code: str, form_data: dict, headers: dict, redemption_id: str):
        last_result = None
        for attempt in range(1, self.redemption_max_attempts + 1):
            try:
                print(f"[WOS-REDEEM-REQUEST] function=request_redemption_with_backoff fid={fid} code={gift_code} attempt={attempt}")
                async with session.post(self.wos_giftcode_url, headers=headers, data=form_data) as response:
                    response_text = await response.text()
                    self.log_redemption_response_shape(gift_code, fid, attempt, response.status, response_text)
                    last_result = self.build_redemption_result(
                        fid=fid,
                        gift_code=gift_code,
                        redemption_id=redemption_id,
                        success=False,
                        status="code_rate_limited" if response.status == 429 else "member_failed",
                        attempts_used=attempt,
                        retry_after_used=False,
                        final_error_reason=f"HTTP {response.status}" if response.status != 200 else None,
                        api_status_code=response.status,
                        api_response_body=response_text,
                    )
                    if response.status == 429:
                        if attempt < self.redemption_max_attempts:
                            delay, retry_after_used = self.get_redemption_retry_delay(response, attempt)
                            last_result["retry_after_used"] = retry_after_used
                            self.log_redemption_retry(gift_code, fid, attempt, delay, "HTTP 429")
                            await asyncio.sleep(delay)
                            continue
                        last_result["final_error_reason"] = "HTTP 429 rate limited"
                        last_result["error_reason"] = "HTTP 429 rate limited"
                        last_result["final_state"] = "failed"
                        return False, last_result
                    if response.status != 200:
                        return False, last_result
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        last_result.update({
                            "final_error_reason": "Invalid JSON response",
                            "error_reason": "Invalid JSON response",
                            "exception_message": str(e),
                            "exception_type": type(e).__name__,
                        })
                        return False, last_result
                    if data.get("code") == 0 or data.get("success") is True:
                        return True, self.build_redemption_result(
                            fid=fid,
                            gift_code=gift_code,
                            redemption_id=redemption_id,
                            success=True,
                            status="member_redeemed",
                            attempts_used=attempt,
                            retry_after_used=last_result.get("retry_after_used", False) if last_result else False,
                            final_error_reason=None,
                            api_status_code=response.status,
                            api_response_body=response_text,
                        )
                    failure_reason = self.get_gift_code_failure_reason(data)
                    failure_status = self.classify_redemption_status({
                        "api_status_code": response.status,
                        "error_reason": failure_reason,
                        "api_response_body": response_text,
                    })
                    last_result.update({
                        "status": failure_status,
                        "final_error_reason": failure_reason,
                        "error_reason": failure_reason,
                        "exception_message": data.get("msg"),
                        "exception_type": "WOSApiError",
                    })
                    return False, last_result
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_result = self.build_redemption_result(
                    fid=fid,
                    gift_code=gift_code,
                    redemption_id=redemption_id,
                    success=False,
                    status="member_failed",
                    attempts_used=attempt,
                    retry_after_used=False,
                    final_error_reason=str(e),
                    api_status_code=None,
                    api_response_body=None,
                    exception=e,
                )
                if attempt < self.redemption_max_attempts:
                    delay, retry_after_used = self.get_redemption_retry_delay(None, attempt)
                    last_result["retry_after_used"] = retry_after_used
                    self.log_redemption_retry(gift_code, fid, attempt, delay, type(e).__name__)
                    await asyncio.sleep(delay)
                    continue
                return False, last_result
            except Exception as e:
                return False, self.build_redemption_result(
                    fid=fid,
                    gift_code=gift_code,
                    redemption_id=redemption_id,
                    success=False,
                    status="member_failed",
                    attempts_used=attempt,
                    retry_after_used=False,
                    final_error_reason=str(e),
                    api_status_code=None,
                    api_response_body=None,
                    exception=e,
                )

        if last_result:
            return False, last_result

        return False, self.build_redemption_result(
                fid=fid,
                gift_code=gift_code,
                redemption_id=redemption_id,
                success=False,
                status="member_failed",
                attempts_used=self.redemption_max_attempts,
                retry_after_used=False,
                final_error_reason="Redemption failed without response",
                api_status_code=None,
                api_response_body=None,
            )

    def build_redemption_result(self, fid: int, gift_code: str, redemption_id: str, success: bool, status: str, attempts_used: int, retry_after_used: bool, final_error_reason, api_status_code, api_response_body, exception=None):
        return {
            "success": success,
            "status": status,
            "attempts_used": attempts_used,
            "request_attempts": attempts_used,
            "retry_count": max(attempts_used - 1, 0),
            "retry_after_used": retry_after_used,
            "final_error_reason": final_error_reason,
            "redemption_id": redemption_id,
            "gift_code": gift_code,
            "fid": fid,
            "error_reason": final_error_reason,
            "exception_message": str(exception) if exception else None,
            "exception_type": type(exception).__name__ if exception else None,
            "api_status_code": api_status_code,
            "api_response_body": api_response_body,
            "timestamp": datetime.utcnow().isoformat(),
            "final_state": "failed" if not success else "succeeded",
        }

    def log_redemption_retry(self, gift_code: str, fid: int, attempt: int, delay: float, reason: str):
        print(f"[WOS-REDEEM-RETRY] function=request_redemption_with_backoff code={gift_code} fid={fid} attempt={attempt} delay={delay:.2f}s reason={reason}")

    def log_redemption_request_shape(self, gift_code: str, fid: int, endpoint: str, form_data, headers: dict):
        body_fields = dict(form_data) if isinstance(form_data, dict) else dict(parse_qsl(form_data, keep_blank_values=True))
        body_types = {key: type(value).__name__ for key, value in body_fields.items()}
        header_keys = sorted(headers.keys())
        print(
            "[WOS-REDEEM-SHAPE] "
            f"code={gift_code} fid={fid} endpoint={endpoint} "
            f"query_keys=[] body_keys={sorted(body_fields.keys())} "
            f"body_value_types={body_types} header_keys={header_keys}"
        )

    def log_redemption_response_shape(self, gift_code: str, fid: int, attempt: int, response_status: int, response_body: str):
        print(
            "[WOS-REDEEM-RESPONSE] "
            f"function=request_redemption_with_backoff fid={fid} code={gift_code} "
            f"attempt={attempt} status={response_status} body={response_body}"
        )

    def get_redemption_retry_delay(self, response, attempt: int):
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after), self.redemption_max_backoff), True
                except ValueError:
                    pass
        exponential = min(self.redemption_base_backoff * (2 ** (attempt - 1)), self.redemption_max_backoff)
        return exponential + random.uniform(0, 1), False

    async def create_gift_code_for_alliance(self, interaction: discord.Interaction, gift_code: str, alliance_id: int, alliance_name: str):
        if interaction.guild_id is None:
            await interaction.followup.send("❌ This can only be used in a server.", ephemeral=True)
            return

        with sqlite3.connect(database_path(USERS_DB, 'users.sqlite')) as users_conn:
            users_cursor = users_conn.cursor()
            users_cursor.execute("SELECT fid FROM users WHERE alliance = ?", (alliance_id,))
            members = users_cursor.fetchall()

        if not members:
            await interaction.followup.send(f"❌ No members found for `{alliance_name}`.", ephemeral=True)
            return

        success_count = 0
        already_redeemed_count = 0
        already_processed_count = 0
        failed = []
        processed_pairs = set()

        for (fid,) in members:
            pair_key = (gift_code, fid)

            if pair_key in processed_pairs:
                already_processed_count += 1
                continue

            processed_pairs.add(pair_key)

            ok, result = await self.redeem_gift_code_for_fid(fid, gift_code)
            if ok:
                success_count += 1
            else:
                status_value = str(result.get("status") or "unknown") if isinstance(result, dict) else "unknown"
                if status_value == "code_not_claimable":
                    already_redeemed_count += 1
                failed.append((fid, result))
            await asyncio.sleep(1)

        embed = discord.Embed(
            title="🎁 Gift Code Redemption Complete",
            description=f"Redeemed `{gift_code}` for `{alliance_name}`.",
            color=discord.Color.green() if not failed else discord.Color.orange()
        )
        embed.add_field(name="Total Members", value=f"`{len(members)}`", inline=True)
        embed.add_field(name="Succeeded", value=f"`{success_count}`", inline=True)
        embed.add_field(name="Already Redeemed", value=f"`{already_redeemed_count}`", inline=True)
        embed.add_field(name="Already Processed", value=f"`{already_processed_count}`", inline=True)
        embed.add_field(name="Failed", value=f"`{len(failed)}`", inline=True)

        if failed:
            failed_preview = "\n".join(f"FID {fid}: {reason}" for fid, reason in failed[:10])
            embed.add_field(name="Failures", value=failed_preview, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


    async def show_redeem_diagnostics_menu(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🧪 Redeem Diagnostics",
            description=(
                "Run a one-off manual redemption test.\n\n"
                "Use this for admin diagnostics when gift redemption is failing.\n"
                "You will enter one FID and one gift code, and the bot will attempt exactly one redemption."
            ),
            color=discord.Color.orange()
        )
        view = RedeemDiagnosticsView(self)
        try:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class RedeemDiagnosticsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Run Manual Redeem Test", emoji="🧪", style=discord.ButtonStyle.primary, row=0)
    async def run_manual_redeem_test_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins can run Redeem Diagnostics.", ephemeral=True)
            return
        await interaction.response.send_modal(RedeemDiagnosticsModal(self.cog))

    @discord.ui.button(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        other_features_cog = self.cog.bot.get_cog("OtherFeatures")
        if other_features_cog:
            await other_features_cog.show_other_features_menu(interaction)
        else:
            await interaction.response.send_message("❌ Other Features module not found.", ephemeral=True)


class RedeemDiagnosticsModal(discord.ui.Modal, title="Redeem Diagnostics"):
    fid = discord.ui.TextInput(
        label="FID",
        placeholder="Enter one player FID",
        required=True,
        max_length=32
    )

    gift_code = discord.ui.TextInput(
        label="Gift Code",
        placeholder="Enter one gift code",
        required=True,
        max_length=64
    )

    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins can run Redeem Diagnostics.", ephemeral=True)
            return

        fid_value = str(self.fid.value).strip()
        gift_code_value = str(self.gift_code.value).strip()

        if not fid_value.isdigit():
            await interaction.response.send_message("❌ FID must be numeric.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, result = await self.cog.redeem_gift_code_for_fid(int(fid_value), gift_code_value)

        embed = discord.Embed(
            title="🧪 Redeem Diagnostics Result",
            color=discord.Color.green() if ok else discord.Color.orange()
        )
        embed.add_field(name="FID", value=f"`{fid_value}`", inline=True)
        embed.add_field(name="Gift Code", value=f"`{gift_code_value}`", inline=True)
        embed.add_field(name="Success", value=f"`{ok}`", inline=True)
        embed.add_field(name="Status", value=f"`{result.get('status')}`", inline=True)
        embed.add_field(name="Final State", value=f"`{result.get('final_state')}`", inline=True)
        embed.add_field(name="Attempts", value=f"`{result.get('attempts_used')}`", inline=True)

        status_value = str(result.get("status") or "unknown")
        already_redeemed_value = "Yes" if status_value == "code_not_claimable" else "No"

        error_reason = str(result.get("error_reason") or "None")
        api_status = result.get("api_status_code")
        response_body = str(result.get("api_response_body") or "None")

        embed.add_field(name="Already Redeemed", value=f"`{already_redeemed_value}`", inline=True)
        embed.add_field(name="Error Reason", value=f"```{error_reason[:900]}```", inline=False)
        embed.add_field(name="API Status", value=f"`{api_status}`", inline=True)
        embed.add_field(name="Redemption ID", value=f"`{result.get('redemption_id')}`", inline=False)
        embed.add_field(name="API Response", value=f"```{response_body[:900]}```", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


class GiftMenuView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    async def _not_configured(self, interaction: discord.Interaction, operation: str):
        await interaction.response.send_message(f"❌ {operation} is not configured in this build.", ephemeral=True)

    @discord.ui.button(label="Manual Gift Code", emoji="✍️", style=discord.ButtonStyle.primary, row=0)
    async def manual_gift_code_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_create_gift_code_modal(interaction)

    @discord.ui.button(label="Scan Last 5 Codes", emoji="�", style=discord.ButtonStyle.secondary, row=0)
    async def scan_last_5_codes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_auto_gift_settings(interaction)

    @discord.ui.button(label="Scheduled Redemption", emoji="⏱️", style=discord.ButtonStyle.primary, row=1)
    async def scheduled_redemption_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_auto_gift_settings(interaction)

    @discord.ui.button(label="Main Menu", emoji="🏠", style=discord.ButtonStyle.secondary, row=2)
    async def main_menu_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        alliance_cog = self.cog.bot.get_cog("Alliance")
        if alliance_cog:
            await alliance_cog.show_main_menu(interaction)
        else:
            await interaction.response.send_message("❌ Settings menu not found.", ephemeral=True)


class GiftCodeAllianceSelectView(discord.ui.View):
    def __init__(self, cog, gift_code: str, alliances):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(GiftCodeAllianceSelect(cog, gift_code, alliances))


class GiftCodeAllianceSelect(discord.ui.Select):
    def __init__(self, cog, gift_code: str, alliances):
        self.cog = cog
        self.gift_code = gift_code
        self.alliance_names = {str(alliance_id): name for alliance_id, name in alliances[:25]}
        options = [
            discord.SelectOption(label=name[:100], value=str(alliance_id))
            for alliance_id, name in alliances[:25]
        ]
        super().__init__(
            placeholder="Select an alliance",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        alliance_id = int(self.values[0])
        alliance_name = self.alliance_names.get(self.values[0], f"Alliance {alliance_id}")
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.create_gift_code_for_alliance(interaction, self.gift_code, alliance_id, alliance_name)


class AutoGiftSettingsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="Set Gift Code Channel", emoji="📢", style=discord.ButtonStyle.primary, row=0)
    async def set_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📢 Select Gift Code Channel",
            description="Choose the channel where auto gift codes will be detected.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=AutoGiftChannelSelectView(self.cog), ephemeral=True)

    @discord.ui.button(label="Set Results Channel", emoji="📊", style=discord.ButtonStyle.primary, row=0)
    async def set_results_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📊 Select Results Channel",
            description="Choose the channel where auto gift redemption results will be posted.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, view=AutoGiftResultsChannelSelectView(self.cog), ephemeral=True)

    @discord.ui.button(label="Configure Alliances", emoji="🛡️", style=discord.ButtonStyle.secondary, row=0)
    async def configure_alliances_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return
        await self.cog.show_auto_gift_alliance_select(interaction)

    @discord.ui.button(label="Scan Last 5 Codes", emoji="🔍", style=discord.ButtonStyle.success, row=1)
    async def scan_gift_code_channel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.scan_gift_code_channel(interaction)




class AutoGiftChannelSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(AutoGiftChannelSelect(cog))


class AutoGiftChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        super().__init__(
            placeholder="Select gift code channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        channel = self.values[0]
        await self.cog.save_auto_gift_channel(interaction, channel)


class AutoGiftResultsChannelSelectView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(AutoGiftResultsChannelSelect(cog))


class AutoGiftResultsChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, cog):
        super().__init__(
            placeholder="Select results channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text]
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        channel = self.values[0]
        await self.cog.save_auto_gift_results_channel(interaction, channel)


class AutoGiftAllianceSelectView(discord.ui.View):
    def __init__(self, cog, alliances, enabled_alliances):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(AutoGiftAllianceSelect(cog, alliances, enabled_alliances))


class AutoGiftAllianceSelect(discord.ui.Select):
    def __init__(self, cog, alliances, enabled_alliances):
        self.cog = cog
        options = [
            discord.SelectOption(
                label=name[:100],
                value=str(alliance_id),
                default=alliance_id in enabled_alliances
            )
            for alliance_id, name in alliances[:25]
        ]
        super().__init__(
            placeholder="Select enabled auto gift alliances",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if not check_permission(interaction.user.id, interaction.guild_id, "admin"):
            await interaction.response.send_message("❌ Only admins or the bot owner can use this feature.", ephemeral=True)
            return

        alliance_ids = [int(value) for value in self.values]
        await self.cog.save_auto_gift_alliances(interaction, alliance_ids)


class CreateGiftCodeModal(discord.ui.Modal, title="Create Gift Code"):
    gift_code = discord.ui.TextInput(
        label="Gift Code",
        placeholder="Enter gift code",
        max_length=100
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        gift_code_value = str(self.gift_code.value).strip()

        if not gift_code_value:
            await interaction.response.send_message("❌ Gift Code is required.", ephemeral=True)
            return

        try:
            await self.cog.show_gift_code_alliance_select(interaction, gift_code_value)
        except Exception as e:
            print(f"[ERROR] Failed to show alliance select for gift_code={gift_code_value}: {e}")
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred while loading alliances.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(GiftOperations(bot))