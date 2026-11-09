# 4.5 Bonus: Connect Google Antigravity to Zetaris

## Install

Download Antigravity from [antigravity.google](https://antigravity.google), install it like any other app, and sign in with a Google account.

## Before you start

You need the semantic layer from chapter 3 and the agent user from lesson 3.5 (`ai_analyst` role, column policy on `unit_cost`). This lesson uses the same setup as every agent in chapter 4.

## 1. Create the agent's API token

Log in **as the agent user**, not as admin, and open **Management → API Tokens → +**.

- **Name:** e.g. `ai-agents`
- **Expires at:** `+30d` (90 days is the maximum)

Copy the token right away, it's shown only once. The token carries exactly the permissions of the user who created it.

## 2. Clone Zetaris' getting-started repository

```bash
git clone https://github.com/zetaris/getting-started.git zetaris-getting-started
cd zetaris-getting-started
cp .env.example .env.local
open -e .env.local
```

`open -e` opens the file in TextEdit. Any editor works, e.g. VS Code. `.env.local` is in the repository's `.gitignore`, so your key never ends up in Git.

## 3. Fill in `.env.local`

| Variable | Value |
|---|---|
| `ZETARIS_REST_URL` | `https://api.<cluster-hostname>/api/v1.0`. Take the cluster hostname from the Zetaris Cloud Gateway (it already ends in `.cloud.zetaris.com`) and put `api.` in front of it. The variable sits in the lower block of the file: replace the `localhost` value there. |
| `ZETARIS_ORG_ID` | The numeric **ID** under **Management → Organisation** (admin account). Usually `1`. |
| `ZETARIS_API_KEY` | The agent's token from step 1. |
| `ZETARIS_USERNAME` | The agent user's email. Only used by the setup check. |
| `ZETARIS_PASSWORD` | The agent user's password. Only used by the setup check. |

> Every variable must appear **only once** in the file. A second, empty or `localhost` line further down overrides your value.

## Run

Open the `zetaris-getting-started` folder as a project (**New Project → Add Folder**). If Antigravity asks, choose **Local mode**, so the agent works directly in the folder with your `.env.local`.

Antigravity asks before it runs a command.

## The prompts

**1. Check the setup and the connection** (from Zetaris' repository guide):

```text
Read AGENTS.md and follow it. Run python3 scripts/preflight.py and show me the
result. Then connect over REST to the instance configured in .env.local and
confirm with SELECT 1 and SHOW LIGHTNING DATABASES.
```

**2. Let the agent discover the semantic layer:**

```text
What data can you see in the northbound namespace? Describe the tables and how they relate.
```

**3. The business question from chapter 3:**

```text
Which marketing campaign has the best return on ad spend?
```

## What to expect

- The setup check reports **READY**, with **0 data sources** and only the `northbound` namespace. That's governance at work: the agent user can't see the raw sources, only the semantic layer.
- **Expedition Partners** has the best return on ad spend: **8.73** before returns, **8.03** after. The same number as the SQL in lesson 3.3.
- Agents answer differently from run to run. The numbers stay the same, because they all read the same semantic layer.
