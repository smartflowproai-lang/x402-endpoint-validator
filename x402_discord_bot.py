import asyncio
import os

import discord
from discord import app_commands

from x402_conformance_engine import AuditReport, X402Auditor


STATUS_COLORS = {
    "PASS": 0x2ECC71,
    "FAIL": 0xE67E22,
    "CRITICAL_FAIL": 0xE74C3C,
    "ERROR": 0xE74C3C,
}

STATUS_EMOJI = {
    "PASS": "✅",
    "FAIL": "⚠️",
    "CRITICAL_FAIL": "🔴",
    "ERROR": "❌",
}

CHECK_DISPLAY_NAMES = {
    "manifest_discovery": "Manifest Discovery",
    "caip2_compliance": "CAIP-2 Compliance",
    "json_resilience": "JSON Resilience",
}


class X402Bot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        print("Slash commands synced.")


bot = X402Bot()


def build_audit_embed(report: AuditReport) -> discord.Embed:
    color = STATUS_COLORS.get(report.overall_status, 0x95A5A6)

    embed = discord.Embed(
        title=f"x402 Conformance Audit — {report.overall_status}",
        description=f"**Target:** `{report.target_url}`\n**Timestamp:** {report.timestamp.isoformat()}",
        color=color,
    )

    for check in report.checks:
        display_name = CHECK_DISPLAY_NAMES.get(check.check_name, check.check_name)
        check_emoji = STATUS_EMOJI.get(check.status, "❓")

        field_value = f"{check_emoji} **{check.status}**\n{check.message}"

        if check.check_name == "json_resilience" and check.status == "CRITICAL_FAIL":
            field_value += (
                "\n\n**WARNING:** This endpoint returns a JSON primitive (string, array, null)"
                " instead of a JSON object. **This WILL crash the x402 strict-v2 reference verifier.**"
            )
            if check.details and check.details.get("sample"):
                field_value += f"\n`Payload sample: {check.details['sample'][:80]}`"

        if check.check_name == "caip2_compliance" and check.details:
            caip2_val = check.details.get("caip2_value")
            if caip2_val:
                field_value += f"\n`network: {caip2_val}`"
            header_name = check.details.get("header_name")
            if header_name:
                field_value += f"\n`header: {header_name}`"

        if check.check_name == "manifest_discovery" and check.details:
            has_accepts = check.details.get("has_accepts", False)
            status_code = check.details.get("status_code")
            if status_code:
                field_value += f"\n`HTTP {status_code}`"
            field_value += f"\n`accepts key: {'present' if has_accepts else 'missing'}`"

        embed.add_field(name=display_name, value=field_value, inline=False)

    embed.set_footer(text="x402 Conformance Engine v1.0 | strict-v2")
    return embed


@bot.tree.command(name="x402", description="Run x402 strict-v2 conformance audit on a URL")
@app_commands.describe(url="Target base URL to audit (e.g. https://api.example.com)")
async def x402_command(interaction: discord.Interaction, url: str) -> None:
    await interaction.response.defer(thinking=True)

    loading_embed = discord.Embed(
        title="x402 Audit in Progress...",
        description=f"Auditing `{url}`\nThis may take up to 30 seconds.",
        color=0x3498DB,
    )
    await interaction.followup.send(embed=loading_embed)

    try:
        async with X402Auditor(timeout=10.0) as auditor:
            report = await auditor.run_full_audit(url)

        embed = build_audit_embed(report)
        await interaction.edit_original_response(embed=embed)

    except Exception as e:
        error_embed = discord.Embed(
            title="x402 Audit — ERROR",
            description=f"An unexpected error occurred while auditing `{url}`:\n```{str(e)[:200]}```",
            color=0xE74C3C,
        )
        await interaction.edit_original_response(embed=error_embed)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} guild(s)")
    print("x402 Conformance Engine is online.")
    print(f"Use /x402 url:<URL> in any server")


def main() -> None:
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("Error: DISCORD_TOKEN environment variable is not set.")
        print("Usage: DISCORD_TOKEN=your_token python x402_discord_bot.py")
        raise SystemExit(1)

    bot.run(token)


if __name__ == "__main__":
    main()
