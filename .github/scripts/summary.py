#!/usr/bin/env python3
"""Render GitHub Actions job summaries for the Falcon ECS Fargate samples.

Every subcommand prints Markdown to stdout; the workflow appends it to $GITHUB_STEP_SUMMARY.

  summary.py iac <report.sarif> <exit-code>
  summary.py image-scan <report.json> <exit-code> <image>
  summary.py image-diff <original-inspect.json> <patched-inspect.json>
  summary.py task-definition <describe-task-definition.json> <title> <description>

Values that identify the Falcon tenant (CID, provisioning tokens) are redacted, and ECR
registry hostnames are shortened so the AWS account ID is not shown on screen.
"""

import json
import re
import sys
from collections import Counter
from urllib.parse import unquote

FALCON_INIT = "crowdstrike-falcon-init-container"
SEVERITIES = ["critical", "high", "medium", "low", "informational"]
MATURITY = {"poc": "PoC", None: "—", "": "—"}

ECR_HOST = re.compile(r"^\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com(\.cn)?/")
CID_FLAG = re.compile(r"(--cid=)\S+", re.IGNORECASE)
CID_VALUE = re.compile(r"\b[0-9A-F]{32}-[0-9A-F]{2}\b", re.IGNORECASE)


def redact(value):
    value = CID_FLAG.sub(r"\1<redacted>", str(value))
    return CID_VALUE.sub("<redacted>", value)


def short_image(image):
    image = ECR_HOST.sub("<ecr>/", image or "")
    # Shorten commit SHA tags to 12 characters
    return re.sub(r":([0-9a-f]{40})$", lambda m: ":" + m.group(1)[:12], image)


def code(value):
    return f"`{value}`" if value else "—"


def falcon_env(environment):
    """FALCONCTL_* and CS_* variables, i.e. the sensor configuration."""
    items = []
    for item in environment or []:
        name, value = item["name"], item.get("value", "")
        if name.startswith(("FALCONCTL_", "CS_")):
            if "CID" in name or "TOKEN" in name:
                value = "<redacted>"
            items.append(f"`{name}={redact(value)}`")
    return items


def severity_table(counts, label):
    if not counts:
        return f"No {label} reported.\n"
    rows = [f"| {label.capitalize()} | Count |", "|---|---:|"]
    rows += [f"| {s.capitalize()} | {counts[s]} |" for s in SEVERITIES if counts.get(s)]
    rows += [f"| {s.capitalize()} | {n} |" for s, n in counts.items() if s not in SEVERITIES]
    return "\n".join(rows) + "\n"


def status_line(exit_code, passed, failed):
    return f"**Result:** {'✅ ' + passed if exit_code == '0' else '❌ ' + failed}\n"


# --------------------------------------------------------------------------------------------
# Falcon Cloud Security scans


def iac(sarif_path, exit_code):
    out = ["### 🔍 Infrastructure as Code scan (Falcon Cloud Security)", ""]
    try:
        with open(sarif_path) as f:
            sarif = json.load(f)
    except (OSError, ValueError):
        out.append("No SARIF report was produced; check the scan step log.")
        print("\n".join(out))
        return

    counts, findings = Counter(), []
    for run in sarif.get("runs", []):
        rules = {r.get("id"): r for r in run.get("tool", {}).get("driver", {}).get("rules", [])}
        for result in run.get("results", []):
            rule = rules.get(result.get("ruleId"), {})
            score = float(rule.get("properties", {}).get("security-severity", 0) or 0)
            severity = ("critical" if score >= 9 else "high" if score >= 7
                        else "medium" if score >= 4 else "low" if score > 0 else "informational")
            counts[severity] += 1
            loc = (result.get("locations") or [{}])[0].get("physicalLocation", {})
            path = unquote(loc.get("artifactLocation", {}).get("uri", ""))
            line = loc.get("region", {}).get("startLine")
            findings.append((SEVERITIES.index(severity), severity, rule.get("name") or result.get("ruleId", ""),
                             f"{path}:{line}" if line else path))

    out.append(status_line(exit_code, "within the fail_on thresholds", "exceeded the fail_on thresholds"))
    out.append(severity_table(counts, "findings"))
    if findings:
        out += ["", "<details><summary>Top findings</summary>", "",
                "| Severity | Rule | Location |", "|---|---|---|"]
        for _, sev, name, location in sorted(findings)[:15]:
            out.append(f"| {sev.capitalize()} | {name} | {code(location)} |")
        out += ["", "</details>", "",
                "All findings are in the repository **Security → Code scanning** tab and the Falcon console."]
    print("\n".join(out))


def image_scan(report_path, exit_code, image):
    out = ["### 🔍 Container image assessment (Falcon Cloud Security)", "",
           f"Image: {code(short_image(image))}", ""]
    try:
        with open(report_path) as f:
            report = json.load(f)
    except (OSError, ValueError):
        out.append("No JSON report was produced; check the scan step log.")
        print("\n".join(out))
        return

    policy = report.get("PolicyResponse") or {}
    policy_name = (policy.get("policy") or {}).get("name", "unknown")
    if policy.get("deny"):
        out.append(f"**Image Assessment policy `{policy_name}`:** ❌ deny, this image would be blocked")
    elif policy:
        out.append(f"**Image Assessment policy `{policy_name}`:** ✅ allowed")
    else:
        out.append(status_line(exit_code, "passed the Image Assessment policy", "failed the Image Assessment policy"))
    out.append("")

    vulns = [v.get("Vulnerability", {}) for v in report.get("Vulnerabilities") or []]

    def exprt(v):
        rating = ((v.get("Details") or {}).get("cps_rating") or {}).get("CurrentRating") or {}
        return (rating.get("Rating") or "unknown").lower()

    def cvss(v):
        return ((v.get("Details") or {}).get("severity") or "unknown").lower()

    by_exprt, by_cvss = Counter(map(exprt, vulns)), Counter(map(cvss, vulns))
    exploitable = [v for v in vulns if (v.get("ExploitDetails") or {}).get("exploit_found")]

    if vulns:
        out += [f"**{len(vulns)} vulnerabilities**, {len(exploitable)} with a known exploit. "
                "ExPRT is CrowdStrike's rating of how likely a vulnerability is to be exploited, so it is "
                "usually the better way to prioritize than CVSS severity.", "",
                "| Rating | ExPRT | CVSS |", "|---|---:|---:|"]
        out += [f"| {s.capitalize()} | {by_exprt.get(s, 0)} | {by_cvss.get(s, 0)} |"
                for s in ["critical", "high", "medium", "low"]]
        rank = {s: i for i, s in enumerate(SEVERITIES)}
        top = sorted(vulns, key=lambda v: (rank.get(exprt(v), 9), not (v.get("ExploitDetails") or {}).get("exploit_found"),
                                           -((v.get("Details") or {}).get("base_score") or 0)))[:10]
        out += ["", "<details open><summary>Top vulnerabilities by ExPRT rating</summary>", "",
                "| CVE | ExPRT | CVSS | Exploit | Package | Fix |", "|---|---|---|---|---|---|"]
        for v in top:
            product = v.get("Product") or {}
            maturity = (v.get("ExploitDetails") or {}).get("max_exploit_maturity")
            fix = "; ".join(v.get("Remediation") or []) or ", ".join(v.get("FixedVersions") or []) or "—"
            out.append(f"| {v.get('CVEID', '')} | {exprt(v).capitalize()} | {cvss(v).capitalize()} "
                       f"({(v.get('Details') or {}).get('base_score', '')}) | {MATURITY.get(maturity, (maturity or '—').capitalize())} "
                       f"| {product.get('Product', '')} {product.get('MajorVersion', '')} | {fix} |")
        out += ["", "</details>", ""]
    else:
        out += ["No vulnerabilities reported.", ""]

    detections = [d.get("Detection", {}) for d in report.get("Detections") or []]
    if detections:
        out += [f"**{len(detections)} detection(s)** (malware, secrets and misconfigurations)", "",
                "| Type | Severity | Finding |", "|---|---|---|"]
        out += [f"| {d.get('Type', '')} | {d.get('Severity', '')} | {d.get('Title', '')} |" for d in detections]
        out.append("")
    out.append("All findings are also in **Security → Code scanning** (category `crowdstrike-fcs-image`) "
               "and in the Falcon console under Image Assessment.")
    print("\n".join(out))


# --------------------------------------------------------------------------------------------
# Sample 01: what falconutil changed in the image


def image_diff(original_path, patched_path):
    def config(path):
        with open(path) as f:
            data = json.load(f)
        return (data[0] if isinstance(data, list) else data).get("Config", {})

    before, after = config(original_path), config(patched_path)
    before_env = {e.split("=", 1)[0] for e in before.get("Env") or []}
    added_env = [e for e in after.get("Env") or [] if e.split("=", 1)[0] not in before_env]

    def show(value):
        return code(" ".join(value)) if isinstance(value, list) else code(value)

    out = ["#### What `falconutil patch-image` changed in the image", "",
           "| Image config | Before | After |", "|---|---|---|"]
    for key in ("Entrypoint", "Cmd", "User", "WorkingDir"):
        if before.get(key) != after.get(key):
            out.append(f"| {key} | {show(before.get(key))} | {show(after.get(key))} |")
    if added_env:
        out.append("| Env (added) | — | " + "<br>".join(
            code(redact(e) if not re.search("CID|TOKEN", e.split('=', 1)[0]) else e.split('=', 1)[0] + "=<redacted>")
            for e in added_env) + " |")
    print("\n".join(out) + "\n")


# --------------------------------------------------------------------------------------------
# All samples: the registered task definition


def entrypoint_summary(container):
    entry = container.get("entryPoint") or []
    command = container.get("command") or []
    if container["name"] == FALCON_INIT:
        return "copies the sensor into the shared volume, then exits"
    if any(e.endswith("entrypoint-ecs.sh") for e in entry):
        wrapped = entry[[i for i, e in enumerate(entry) if e.endswith("entrypoint-ecs.sh")][0] + 1:]
        return f"Falcon wrapper → {code(' '.join(wrapped + command))}"
    if entry or command:
        return code(" ".join(entry + command))
    return "image ENTRYPOINT"


def task_definition(path, title, description):
    with open(path) as f:
        td = json.load(f)["taskDefinition"]

    region = td["taskDefinitionArn"].split(":")[3]
    family, revision = td["family"], td["revision"]
    console = (f"https://{region}.console.aws.amazon.com/ecs/v2/task-definitions/"
               f"{family}/{revision}/containers?region={region}")
    platform = td.get("runtimePlatform", {}).get("cpuArchitecture", "X86_64")
    containers = td.get("containerDefinitions", [])
    apps = [c for c in containers if c["name"] != FALCON_INIT]
    has_init = len(apps) != len(containers)

    out = [f"### {title}", "", description, "",
           f"**Task definition:** [`{family}:{revision}`]({console}) · "
           f"{td.get('cpu')} CPU / {td.get('memory')} MiB · {platform} · "
           f"Falcon init container: {'yes' if has_init else 'no (sensor is in the image)'}", "",
           "| Container | Image | Essential | Starts after | Launches |", "|---|---|---|---|---|"]
    for c in containers:
        depends = ", ".join(f"{d['containerName']} {d['condition']}" for d in c.get("dependsOn") or []) or "—"
        name = f"**{c['name']}** (Falcon)" if c["name"] == FALCON_INIT else c["name"]
        out.append(f"| {name} | {code(short_image(c.get('image')))} | {'yes' if c.get('essential', True) else 'no'} "
                   f"| {depends} | {entrypoint_summary(c)} |")

    out += ["", "**Falcon settings on each application container**", "",
            "| Container | SYS_PTRACE | Falcon volume mounts | Sensor configuration |", "|---|---|---|---|"]
    for c in apps:
        caps = (c.get("linuxParameters") or {}).get("capabilities", {}).get("add") or []
        mounts = [m["containerPath"] for m in c.get("mountPoints") or [] if "CrowdStrike" in m["containerPath"]]
        env = falcon_env(c.get("environment"))
        out.append(f"| {c['name']} | {'✅' if 'SYS_PTRACE' in caps else '❌'} "
                   f"| {'<br>'.join(code(m) for m in mounts) or '— (in image)'} "
                   f"| {'<br>'.join(env) or '— (built into the image)'} |")
    print("\n".join(out) + "\n")


if __name__ == "__main__":
    commands = {"iac": iac, "image-scan": image_scan, "image-diff": image_diff,
                "task-definition": task_definition}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]](*sys.argv[2:])
