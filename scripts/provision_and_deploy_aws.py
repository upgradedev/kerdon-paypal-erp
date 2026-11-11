#!/usr/bin/env python3
"""One-command owner bootstrap for private GitHub repo, OIDC role, and AWS SAM deploy.

Executes in independent, idempotent stages so GitHub repo creation and push
succeed even if AWS CLI credentials are not yet active in the current shell:
1. Checks `gh auth status` and ensures `upgradedev/kerdon-aws-msp` exists as a
   PRIVATE repository (`Trap T3`), pushing `main` to `origin`.
2. Checks `aws sts get-caller-identity` (for account `308857099262` in `eu-west-1`)
   and creates/updates IAM OIDC role `kerdon-github-deploy` with `StringLike`
   `repo:upgradedev*/kerdon-aws-msp*:*` (`Trap T6`) and scoped `infra/deploy-policy.json`.
3. Sets GitHub Actions secret `AWS_DEPLOY_ROLE_ARN` and triggers `.github/workflows/ci.yml`
   (`deploy_action=deploy`).

Usage:
  python scripts/provision_and_deploy_aws.py --check-only
  python scripts/provision_and_deploy_aws.py --execute
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_FULL_NAME = "upgradedev/kerdon-aws-msp"
ROLE_NAME = "kerdon-github-deploy"
POLICY_NAME = "KerdonSamDeployPolicy"
AWS_REGION = "eu-west-1"
DEFAULT_ACCOUNT_ID = "308857099262"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if check and res.returncode != 0:
        if res.stdout:
            print(res.stdout, file=sys.stderr)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
        raise subprocess.CalledProcessError(
            res.returncode, cmd, output=res.stdout, stderr=res.stderr
        )
    return res


def build_oidc_trust_policy(account_id: str) -> dict[str, object]:
    """Build OIDC trust policy using StringLike wildcard for numeric GitHub sub IDs (Trap T6)."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": "repo:upgradedev*/kerdon-aws-msp*:*"
                    },
                },
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision OIDC and deploy Kerdon MSP")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate local policy JSON and print planned OIDC trust policy without calling AWS/GitHub",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute GitHub private repo creation, IAM OIDC role setup, push, and CI deploy",
    )
    parser.add_argument(
        "--profile",
        default="",
        help="Optional AWS CLI profile name",
    )
    args = parser.parse_args()

    policy_path = REPO_ROOT / "infra" / "deploy-policy.json"
    policy_doc = json.loads(policy_path.read_text(encoding="utf-8"))
    trust_doc = build_oidc_trust_policy(DEFAULT_ACCOUNT_ID)

    if args.check_only or not args.execute:
        print(
            json.dumps(
                {
                    "status": "READY",
                    "repo": REPO_FULL_NAME,
                    "visibility": "PRIVATE",
                    "role_name": ROLE_NAME,
                    "policy_statements": len(policy_doc.get("Statement", [])),
                    "trust_policy": trust_doc,
                },
                indent=2,
            )
        )
        return 0

    # Stage 1: Verify GitHub CLI authentication and create/push PRIVATE repository
    gh_auth = _run(["gh", "auth", "status"], check=False)
    if gh_auth.returncode != 0:
        print(
            "\n[ACTION NEEDED - GitHub CLI]: Not logged into GitHub CLI in this shell.\n"
            "  Run:  gh auth login\n"
            "  Then re-run:  python scripts\\provision_and_deploy_aws.py --execute",
            file=sys.stderr,
        )
        return 1

    view = _run(["gh", "repo", "view", REPO_FULL_NAME, "--json", "isPrivate"], check=False)
    if view.returncode != 0:
        _run(
            [
                "gh",
                "repo",
                "create",
                REPO_FULL_NAME,
                "--private",
                "--source=.",
                "--remote=origin",
                "--push",
            ]
        )
        print(f"[OK] Created PRIVATE repository {REPO_FULL_NAME} and pushed main.")
    else:
        meta = json.loads(view.stdout)
        if not meta.get("isPrivate"):
            raise RuntimeError(f"CRITICAL: {REPO_FULL_NAME} must be PRIVATE (Trap T3)")
        rem = _run(["git", "remote", "get-url", "origin"], check=False)
        if rem.returncode != 0:
            _run(
                [
                    "git",
                    "remote",
                    "add",
                    "origin",
                    f"https://github.com/{REPO_FULL_NAME}.git",
                ]
            )
        _run(["git", "push", "-u", "origin", "main"])
        print(f"[OK] Verified {REPO_FULL_NAME} is PRIVATE and pushed main.")

    # Stage 2: Verify AWS CLI credentials and provision OIDC role + deploy policy
    aws_prefix = ["aws"]
    if args.profile:
        aws_prefix.extend(["--profile", args.profile])

    sts_res = _run([*aws_prefix, "sts", "get-caller-identity", "--output", "json"], check=False)
    if sts_res.returncode != 0:
        default_role_arn = f"arn:aws:iam::{DEFAULT_ACCOUNT_ID}:role/{ROLE_NAME}"
        _run(
            [
                "gh",
                "secret",
                "set",
                "AWS_DEPLOY_ROLE_ARN",
                "--repo",
                REPO_FULL_NAME,
                "--body",
                default_role_arn,
            ],
            check=False,
        )
        print(
            "\n[STAGE 1 COMPLETE]: Private GitHub repo is pushed and AWS_DEPLOY_ROLE_ARN secret is set.\n"
            "[ACTION NEEDED - AWS CLI]: AWS credentials are not configured in this shell.\n"
            "  Configure AWS credentials for account 308857099262 (eu-west-1):\n"
            "    aws configure\n"
            "  (or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in your shell)\n"
            "  Then re-run:\n"
            "    python scripts\\provision_and_deploy_aws.py --execute",
            file=sys.stderr,
        )
        return 2

    sts = json.loads(sts_res.stdout)
    account_id = str(sts["Account"])
    trust_json = json.dumps(build_oidc_trust_policy(account_id))

    get_role = _run([*aws_prefix, "iam", "get-role", "--role-name", ROLE_NAME], check=False)
    if get_role.returncode != 0:
        _run(
            [
                *aws_prefix,
                "iam",
                "create-role",
                "--role-name",
                ROLE_NAME,
                "--assume-role-policy-document",
                trust_json,
            ]
        )
    else:
        _run(
            [
                *aws_prefix,
                "iam",
                "update-assume-role-policy",
                "--role-name",
                ROLE_NAME,
                "--policy-document",
                trust_json,
            ]
        )

    _run(
        [
            *aws_prefix,
            "iam",
            "put-role-policy",
            "--role-name",
            ROLE_NAME,
            "--policy-name",
            POLICY_NAME,
            "--policy-document",
            json.dumps(policy_doc),
        ]
    )

    role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_NAME}"
    _run(
        [
            "gh",
            "secret",
            "set",
            "AWS_DEPLOY_ROLE_ARN",
            "--repo",
            REPO_FULL_NAME,
            "--body",
            role_arn,
        ]
    )

    # Stage 3: Trigger CI workflow dispatch for deploy
    _run(
        [
            "gh",
            "workflow",
            "run",
            "ci.yml",
            "--repo",
            REPO_FULL_NAME,
            "-f",
            "deploy_action=deploy",
        ]
    )
    print(f"[OK] Deployment triggered on {REPO_FULL_NAME} with role {role_arn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
