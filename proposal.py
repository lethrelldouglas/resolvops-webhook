"""
proposal.py — ResolvOps Proposal Generator
==========================================
Standalone script: enter prospect details, get a full sales proposal.

Run:
    python proposal.py

Or call generate_proposal() programmatically from your own code.
"""

import json
import sys
import urllib.request
import urllib.error
from config import AGENT_CONFIG, BUSINESS_KNOWLEDGE


PROPOSAL_SYSTEM = """You are a sales proposal writer for ResolvOps, an AI Front Desk company.
Generate a custom, persuasive, personalised proposal for a prospective client.

## Your Services, Pricing & Industry Playbooks
{knowledge}

## Instructions
Generate a professional proposal with these sections:
1. **Executive Summary** — personalised intro using their industry pain points
2. **Recommended Solution** — which package fits and why
3. **What's Included** — with industry-specific examples (e.g. for a plumber: AI collects problem, address, urgency)
4. **Pricing** — monthly cost, setup fee, any relevant add-ons
5. **ROI Estimate** — industry-specific calculation with real numbers
6. **Onboarding Timeline** — what the first 2-3 weeks look like
7. **Next Steps** — clear call to action

Make it warm, specific, and feel like it was written for this exact business.
Never sound generic. Max ~700 words.
"""


def call_claude(system_prompt: str, user_content: str, temperature: float = 0.3) -> str:
    api_key = AGENT_CONFIG.get("anthropic_api_key", "")
    if not api_key or api_key.startswith("sk-ant-YOUR"):
        raise ValueError("Set your ANTHROPIC_API_KEY in config.py first.")

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1500,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
        return "".join(
            b["text"] for b in body.get("content", []) if b.get("type") == "text"
        ).strip()


def generate_proposal(
    client_name: str,
    industry: str,
    needs: str,
    package: str = "Not sure - let AI recommend",
    call_volume: str = "Unknown",
    notes: str = "",
) -> str:
    system = PROPOSAL_SYSTEM.format(knowledge=BUSINESS_KNOWLEDGE)
    user_content = (
        f"Business Name: {client_name}\n"
        f"Industry: {industry}\n"
        f"Needs & Pain Points: {needs}\n"
        f"Recommended Package: {package}\n"
        f"Estimated Monthly Call Volume: {call_volume}\n"
        f"Additional Notes: {notes}"
    )
    return call_claude(system, user_content)


def main():
    print("\n═══════════════════════════════════════")
    print("  ResolvOps  ·  Proposal Generator")
    print("═══════════════════════════════════════\n")

    def prompt(label: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        val = input(f"{label}{suffix}: ").strip()
        return val or default

    client_name  = prompt("Prospect / Business Name")
    industry     = prompt("Their Industry (e.g. plumbing, HVAC, Airbnb host)")
    needs        = prompt("Needs & Pain Points")
    package      = prompt("Package", "Not sure - let AI recommend")
    call_volume  = prompt("Estimated Monthly Call Volume", "Unknown")
    notes        = prompt("Additional Notes (optional)", "")

    print("\nGenerating proposal… (this takes ~10 seconds)\n")

    try:
        proposal = generate_proposal(
            client_name, industry, needs, package, call_volume, notes
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    print("─" * 60)
    print(proposal)
    print("─" * 60)

    # optionally save to file
    save = input("\nSave to file? (y/N): ").strip().lower()
    if save == "y":
        filename = f"proposal_{client_name.replace(' ', '_').lower()}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(proposal)
        print(f"Saved to {filename}")


if __name__ == "__main__":
    main()
