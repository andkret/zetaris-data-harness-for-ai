# 2.1 Sign Up and Deploy Your Cluster

## Links

- Zetaris: [zetaris.com](https://zetaris.com), sign up with **Start free** (Hobby tier)
- AWS account (you need one to deploy the cluster into)

## Settings used in the video

| Setting | Value |
|---|---|
| Plan | Hobby (free) |
| Setup | Quickstart (CloudFormation) |
| AWS region | `us-east-1` |
| Cluster size | Small |

## Known pitfalls

**"Not enough vCPU" when creating the cluster.** New AWS accounts have a low quota for on-demand instances. Request more:

1. AWS console → **Service Quotas** → **AWS services** → **Amazon Elastic Compute Cloud (Amazon EC2)**
2. Search for **Running On-Demand Standard** → **Request increase at account level**
3. Request at least **16** (the cluster needs 12).

**"Verify" fails right after the stack is created.** Wait a few minutes until the CloudFormation stack shows `CREATE_COMPLETE`, then click **Verify** again.

## Costs

Zetaris Hobby is free, but the cluster runs in your AWS account, and AWS bills you for it, even while the cluster is suspended. See the [teardown checklist](README.md#when-youre-done-tear-everything-down) when you finish the course.
